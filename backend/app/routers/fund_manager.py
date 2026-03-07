"""AI 펀드매니저 API 라우터."""

import logging
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.daily_briefing import DailyBriefing
from app.models.fund_signal import FundSignal
from app.models.portfolio_report import PortfolioReport
from app.models.stock import Stock
from app.models.sector import Sector
from app.schemas.fund_manager import (
    AnalyzeRequest,
    DailyBriefingResponse,
    FundSignalResponse,
    PortfolioReportResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/fund", tags=["fund-manager"])


def _enrich_signal(signal: FundSignal, db: Session) -> FundSignalResponse:
    """Add stock/sector names to signal response."""
    stock = db.query(Stock).filter(Stock.id == signal.stock_id).first()
    sector = None
    if stock:
        sector = db.query(Sector).filter(Sector.id == stock.sector_id).first()

    return FundSignalResponse(
        id=signal.id,
        stock_id=signal.stock_id,
        stock_name=stock.name if stock else None,
        stock_code=stock.stock_code if stock else None,
        sector_name=sector.name if sector else None,
        signal=signal.signal,
        confidence=signal.confidence,
        target_price=signal.target_price,
        stop_loss=signal.stop_loss,
        reasoning=signal.reasoning,
        news_summary=signal.news_summary,
        financial_summary=signal.financial_summary,
        market_summary=signal.market_summary,
        created_at=signal.created_at,
    )


# ---- 투자 시그널 ----

@router.post("/analyze/{stock_id}", response_model=FundSignalResponse)
async def analyze_stock_endpoint(stock_id: int, db: Session = Depends(get_db)):
    """특정 종목에 대한 AI 투자 시그널을 생성합니다."""
    stock = db.query(Stock).filter(Stock.id == stock_id).first()
    if not stock:
        raise HTTPException(status_code=404, detail="종목을 찾을 수 없습니다.")

    from app.services.fund_manager import analyze_stock
    signal = await analyze_stock(db, stock_id)
    if not signal:
        raise HTTPException(status_code=500, detail="AI 분석에 실패했습니다. Gemini API 키를 확인하세요.")

    return _enrich_signal(signal, db)


@router.get("/signals", response_model=list[FundSignalResponse])
async def get_latest_signals(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """최근 AI 투자 시그널 목록을 조회합니다."""
    # Get the latest signal per stock (subquery for max id per stock_id)
    from sqlalchemy import func
    latest_ids = (
        db.query(func.max(FundSignal.id))
        .group_by(FundSignal.stock_id)
        .subquery()
    )
    signals = (
        db.query(FundSignal)
        .filter(FundSignal.id.in_(latest_ids))
        .order_by(FundSignal.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_enrich_signal(s, db) for s in signals]


@router.get("/signals/{stock_id}", response_model=list[FundSignalResponse])
async def get_stock_signals(
    stock_id: int,
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """특정 종목의 시그널 이력을 조회합니다."""
    signals = (
        db.query(FundSignal)
        .filter(FundSignal.stock_id == stock_id)
        .order_by(FundSignal.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_enrich_signal(s, db) for s in signals]


# ---- 데일리 브리핑 ----

@router.get("/briefing", response_model=DailyBriefingResponse | None)
async def get_daily_briefing(
    target_date: date | None = None,
    db: Session = Depends(get_db),
):
    """데일리 브리핑을 조회합니다. 날짜 미지정 시 오늘 날짜."""
    d = target_date or date.today()
    briefing = db.query(DailyBriefing).filter(DailyBriefing.briefing_date == d).first()
    if not briefing:
        return None
    return DailyBriefingResponse.model_validate(briefing)


@router.post("/briefing/generate", response_model=DailyBriefingResponse)
async def generate_briefing_endpoint(db: Session = Depends(get_db)):
    """오늘의 데일리 브리핑을 생성합니다."""
    from app.config import settings
    if not settings.GEMINI_API_KEY or settings.GEMINI_API_KEY.startswith("your_"):
        raise HTTPException(
            status_code=500,
            detail=f"GEMINI_API_KEY가 설정되지 않았습니다. (현재값: '{settings.GEMINI_API_KEY[:10]}...' len={len(settings.GEMINI_API_KEY)})",
        )
    try:
        from app.services.fund_manager import generate_daily_briefing
        briefing = await generate_daily_briefing(db)
        if not briefing:
            raise HTTPException(status_code=500, detail="브리핑 생성에 실패했습니다. Gemini 응답을 파싱할 수 없습니다.")
        return DailyBriefingResponse.model_validate(briefing)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Briefing generation failed")
        raise HTTPException(status_code=500, detail=f"브리핑 생성 오류: {type(e).__name__}: {e}")


@router.get("/briefings", response_model=list[DailyBriefingResponse])
async def get_briefing_history(
    limit: int = Query(7, ge=1, le=30),
    db: Session = Depends(get_db),
):
    """최근 데일리 브리핑 이력을 조회합니다."""
    briefings = (
        db.query(DailyBriefing)
        .order_by(DailyBriefing.briefing_date.desc())
        .limit(limit)
        .all()
    )
    return [DailyBriefingResponse.model_validate(b) for b in briefings]


# ---- 포트폴리오 분석 ----

@router.post("/portfolio/analyze", response_model=PortfolioReportResponse)
async def analyze_portfolio_endpoint(
    req: AnalyzeRequest,
    db: Session = Depends(get_db),
):
    """포트폴리오(관심종목) 종합 분석 리포트를 생성합니다."""
    if not req.stock_ids or len(req.stock_ids) == 0:
        raise HTTPException(status_code=400, detail="분석할 종목 ID를 입력하세요.")

    from app.services.fund_manager import analyze_portfolio
    report = await analyze_portfolio(db, req.stock_ids)
    if not report:
        raise HTTPException(status_code=500, detail="포트폴리오 분석에 실패했습니다.")
    return PortfolioReportResponse.model_validate(report)


@router.get("/portfolio/latest", response_model=PortfolioReportResponse | None)
async def get_latest_portfolio_report(db: Session = Depends(get_db)):
    """가장 최근 포트폴리오 분석 리포트를 조회합니다."""
    report = (
        db.query(PortfolioReport)
        .order_by(PortfolioReport.created_at.desc())
        .first()
    )
    if not report:
        return None
    return PortfolioReportResponse.model_validate(report)
