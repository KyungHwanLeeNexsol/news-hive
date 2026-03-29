"""AI 펀드매니저 API 라우터."""

import logging
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models.daily_briefing import DailyBriefing
from app.models.fund_signal import FundSignal
from app.models.portfolio_report import PortfolioReport
from app.models.stock import Stock
from app.models.sector import Sector
from app.schemas.fund_manager import (
    AccuracyStatsResponse,
    AnalyzeRequest,
    DailyBriefingResponse,
    FundSignalResponse,
    PortfolioReportResponse,
)

logger = logging.getLogger(__name__)


def _require_admin(request: Request):
    """관리자 인증 의존성. Authorization 헤더의 Bearer 토큰을 검증."""
    from app.routers.auth import _verify_admin_token

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="관리자 인증이 필요합니다.")
    token = auth[7:]
    if not _verify_admin_token(token):
        raise HTTPException(status_code=401, detail="인증 토큰이 만료되었거나 유효하지 않습니다.")


router = APIRouter(
    prefix="/api/fund",
    tags=["fund-manager"],
    dependencies=[Depends(_require_admin)],
)


def _enrich_signal(signal: FundSignal) -> FundSignalResponse:
    """시그널에 종목/섹터명을 추가하여 응답 객체로 변환.

    selectinload로 미리 로드된 relationship을 사용한다.
    N+1 쿼리 최적화: 개별 DB 쿼리 대신 eager loading된 관계 참조.
    """
    stock = signal.stock
    sector = stock.sector if stock else None

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
        price_at_signal=signal.price_at_signal,
        price_after_1d=signal.price_after_1d,
        price_after_3d=signal.price_after_3d,
        price_after_5d=signal.price_after_5d,
        is_correct=signal.is_correct,
        return_pct=signal.return_pct,
        verified_at=signal.verified_at,
    )


# ---- 투자 시그널 ----


@router.get("/signals", response_model=list[FundSignalResponse])
async def get_latest_signals(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """최근 AI 투자 시그널 목록을 조회합니다."""
    # 종목별 최신 시그널 ID 서브쿼리
    from sqlalchemy import func
    latest_ids = (
        db.query(func.max(FundSignal.id))
        .group_by(FundSignal.stock_id)
        .subquery()
    )
    # N+1 쿼리 방지: selectinload로 Stock과 Sector를 한번에 로드
    signals = (
        db.query(FundSignal)
        .options(selectinload(FundSignal.stock).selectinload(Stock.sector))
        .filter(FundSignal.id.in_(latest_ids))
        .order_by(FundSignal.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_enrich_signal(s) for s in signals]


@router.get("/signals/{stock_id}", response_model=list[FundSignalResponse])
async def get_stock_signals(
    stock_id: int,
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """특정 종목의 시그널 이력을 조회합니다."""
    # N+1 쿼리 방지: selectinload로 Stock과 Sector를 한번에 로드
    signals = (
        db.query(FundSignal)
        .options(selectinload(FundSignal.stock).selectinload(Stock.sector))
        .filter(FundSignal.stock_id == stock_id)
        .order_by(FundSignal.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_enrich_signal(s) for s in signals]


# ---- 적중률 통계 ----

@router.get("/accuracy", response_model=AccuracyStatsResponse)
async def get_accuracy_stats_endpoint(
    days: int = Query(30, ge=7, le=90),
    db: Session = Depends(get_db),
):
    """최근 N일간 시그널 적중률 통계를 조회합니다."""
    from app.services.signal_verifier import get_accuracy_stats
    return get_accuracy_stats(db, days=days)


@router.post("/verify", response_model=dict)
async def verify_signals_endpoint(db: Session = Depends(get_db)):
    """미검증 시그널의 적중 여부를 수동으로 검증합니다."""
    from app.services.signal_verifier import verify_signals
    stats = await verify_signals(db)
    return stats


@router.delete("/signals/reset", response_model=dict)
async def reset_signals(db: Session = Depends(get_db)):
    """모든 시그널 데이터를 초기화합니다."""
    count = db.query(FundSignal).delete()
    db.commit()
    return {"deleted": count, "message": f"시그널 {count}건 초기화 완료"}


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
async def generate_briefing_endpoint(
    regenerate: bool = Query(False),
    db: Session = Depends(get_db),
):
    """오늘의 데일리 브리핑을 생성합니다. regenerate=true면 기존 브리핑 삭제 후 재생성."""
    from app.config import settings
    if not settings.GEMINI_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="AI API 키가 설정되지 않았습니다. GEMINI_API_KEY를 설정하세요.",
        )
    try:
        from app.services.fund_manager import generate_daily_briefing
        briefing = await generate_daily_briefing(db, regenerate=regenerate)
        if not briefing:
            raise HTTPException(status_code=500, detail="브리핑 생성에 실패했습니다. AI 응답을 파싱할 수 없습니다.")
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
