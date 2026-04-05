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
        disclosure_id=signal.disclosure_id,
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


# ---- 백테스트 ----


@router.get("/backtest")
async def backtest_signals(
    days: int = Query(90, ge=7, le=365),
    stock_id: int | None = Query(None),
    sector_id: int | None = Query(None),
    signal_type: str | None = Query(None, description="buy / sell / hold"),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    db: Session = Depends(get_db),
):
    """AI 시그널 백테스트 — 기간/종목/섹터/시그널 유형별 성과 분석.

    검증 완료된(is_correct IS NOT NULL) 시그널을 기반으로
    승률, 평균 수익률, MDD, 샤프 비율, KOSPI 벤치마크 수익률을 계산한다.
    """
    import math
    from collections import defaultdict
    from sqlalchemy import func as sqlfunc

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # 기본 쿼리: 검증 완료된 시그널만
    query = (
        db.query(FundSignal)
        .options(selectinload(FundSignal.stock).selectinload(Stock.sector))
        .filter(
            FundSignal.created_at >= cutoff,
            FundSignal.is_correct.isnot(None),
            FundSignal.confidence >= min_confidence,
        )
    )

    if stock_id:
        query = query.filter(FundSignal.stock_id == stock_id)
    if sector_id:
        query = query.filter(Stock.sector_id == sector_id)
        query = query.join(Stock, FundSignal.stock_id == Stock.id)
    if signal_type:
        query = query.filter(FundSignal.signal == signal_type.lower())

    signals = query.order_by(FundSignal.created_at.asc()).all()

    total_signals = len(signals)
    if total_signals == 0:
        return {
            "summary": {
                "total_signals": 0,
                "win_rate": 0.0,
                "avg_return": 0.0,
                "max_drawdown": 0.0,
                "sharpe_ratio": 0.0,
                "kospi_return": 0.0,
            },
            "timeline": [],
            "by_stock": [],
        }

    # 승률 및 수익률 계산
    correct_count = sum(1 for s in signals if s.is_correct is True)
    returns = [s.return_pct for s in signals if s.return_pct is not None]
    win_rate = correct_count / total_signals if total_signals > 0 else 0.0
    avg_return = sum(returns) / len(returns) if returns else 0.0

    # MDD 계산 (누적 수익률 기반)
    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for r in returns:
        cumulative += r
        if cumulative > peak:
            peak = cumulative
        drawdown = peak - cumulative
        if drawdown > max_drawdown:
            max_drawdown = drawdown

    # 샤프 비율 (연간 무위험이자율 3.5% → 일간 환산)
    risk_free_daily = 3.5 / 365.0
    if len(returns) >= 2:
        mean_r = sum(returns) / len(returns)
        variance = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
        std_dev = math.sqrt(variance) if variance > 0 else 0.001
        sharpe_ratio = (mean_r - risk_free_daily) / std_dev
    else:
        sharpe_ratio = 0.0

    # KOSPI 벤치마크 수익률: 첫 시그널~마지막 시그널 기간의 KOSPI 등락률
    kospi_return = 0.0
    try:
        from app.services.naver_finance import fetch_index_price_history
        needed_pages = max(1, days // 10 + 1)
        kospi_history = await fetch_index_price_history("KOSPI", pages=needed_pages)
        if len(kospi_history) >= 2:
            # 최신순 정렬 → 가장 오래된 값이 last, 최신이 first
            latest_close = kospi_history[0]["close"]
            oldest_close = kospi_history[-1]["close"]
            if oldest_close > 0:
                kospi_return = round((latest_close - oldest_close) / oldest_close * 100, 2)
    except Exception as _e:
        logger.debug("KOSPI 벤치마크 조회 실패: %s", _e)

    # 일별 타임라인
    daily_data: dict[str, dict] = {}
    cum_return = 0.0
    for s in signals:
        date_str = s.created_at.strftime("%Y-%m-%d") if s.created_at else "unknown"
        r = s.return_pct or 0.0
        cum_return += r
        if date_str not in daily_data:
            daily_data[date_str] = {"date": date_str, "cumulative_return": 0.0, "signal_count": 0}
        daily_data[date_str]["cumulative_return"] = round(cum_return, 2)
        daily_data[date_str]["signal_count"] += 1

    timeline = sorted(daily_data.values(), key=lambda x: x["date"])

    # 종목별 분석
    stock_stats: dict[int, dict] = defaultdict(lambda: {
        "stock_name": "",
        "signals": 0,
        "correct": 0,
        "returns": [],
    })

    for s in signals:
        sid = s.stock_id
        stock_stats[sid]["stock_name"] = s.stock.name if s.stock else f"Stock-{sid}"
        stock_stats[sid]["signals"] += 1
        if s.is_correct is True:
            stock_stats[sid]["correct"] += 1
        if s.return_pct is not None:
            stock_stats[sid]["returns"].append(s.return_pct)

    by_stock = []
    for sid, data in stock_stats.items():
        s_returns = data["returns"]
        by_stock.append({
            "stock_name": data["stock_name"],
            "signals": data["signals"],
            "win_rate": round(data["correct"] / data["signals"], 4) if data["signals"] > 0 else 0.0,
            "avg_return": round(sum(s_returns) / len(s_returns), 2) if s_returns else 0.0,
        })

    by_stock.sort(key=lambda x: x["avg_return"], reverse=True)

    return {
        "summary": {
            "total_signals": total_signals,
            "win_rate": round(win_rate, 4),
            "avg_return": round(avg_return, 2),
            "max_drawdown": round(max_drawdown, 2),
            "sharpe_ratio": round(sharpe_ratio, 4),
            "kospi_return": round(kospi_return, 2),
        },
        "timeline": timeline,
        "by_stock": by_stock,
    }


# ---- 공시 기반 시그널 (SPEC-AI-004) ----

@router.get("/disclosure-signals", response_model=list[FundSignalResponse])
async def get_disclosure_signals(
    limit: int = Query(20, ge=1, le=50),
    signal_type: str | None = Query(
        None,
        description="disclosure_impact / sector_ripple / gap_pullback_candidate",
    ),
    db: Session = Depends(get_db),
):
    """공시 기반 활성 시그널 목록 조회 (REQ-DISC-017)."""
    q = (
        db.query(FundSignal)
        .options(selectinload(FundSignal.stock).selectinload(Stock.sector))
        .filter(
            FundSignal.signal_type.in_(
                ["disclosure_impact", "sector_ripple", "gap_pullback_candidate"]
            )
        )
    )
    if signal_type:
        q = q.filter(FundSignal.signal_type == signal_type)

    signals = q.order_by(FundSignal.created_at.desc()).limit(limit).all()
    return [_enrich_signal(s) for s in signals]


@router.get("/backtest-stats", response_model=dict)
async def backtest_stats_by_disclosure_type(
    days: int = Query(30, ge=7, le=90),
    db: Session = Depends(get_db),
):
    """공시 기반 시그널 유형별 백테스트 통계 (AC-008).

    hit_rate, avg_return_pct, total_signals, winning_signals를
    공시 시그널 유형(disclosure_impact / sector_ripple / gap_pullback_candidate)별로 반환한다.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    disclosure_signal_types = [
        "disclosure_impact",
        "sector_ripple",
        "gap_pullback_candidate",
    ]
    result: dict = {}

    for stype in disclosure_signal_types:
        q = db.query(FundSignal).filter(
            FundSignal.created_at >= cutoff,
            FundSignal.signal_type == stype,
            FundSignal.is_correct.isnot(None),
        )
        signals = q.all()
        total = len(signals)

        if total == 0:
            result[stype] = {
                "hit_rate": 0.0,
                "avg_return_pct": 0.0,
                "total_signals": 0,
                "winning_signals": 0,
            }
            continue

        winning = sum(1 for s in signals if s.is_correct is True)
        returns = [s.return_pct for s in signals if s.return_pct is not None]

        result[stype] = {
            "hit_rate": round(winning / total, 4),
            "avg_return_pct": round(sum(returns) / len(returns), 2) if returns else 0.0,
            "total_signals": total,
            "winning_signals": winning,
        }

    return result


@router.get("/backtest-by-type", response_model=dict)
async def backtest_by_signal_type(
    days: int = Query(30, ge=7, le=90),
    db: Session = Depends(get_db),
):
    """시그널 유형별 백테스트 통계 (REQ-DISC-016, REQ-DISC-017)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    signal_types: list[str | None] = [
        None,
        "disclosure_impact",
        "sector_ripple",
        "gap_pullback_candidate",
    ]
    result: dict = {}

    for stype in signal_types:
        q = db.query(FundSignal).filter(
            FundSignal.created_at >= cutoff,
            FundSignal.is_correct.isnot(None),
        )
        if stype is None:
            q = q.filter(FundSignal.signal_type.is_(None))
            key = "ai_signal"
        else:
            q = q.filter(FundSignal.signal_type == stype)
            key = stype

        signals = q.all()
        total = len(signals)
        if total == 0:
            result[key] = {
                "total_signals": 0,
                "win_rate": 0.0,
                "avg_return_pct": 0.0,
                "winning_signals": 0,
            }
            continue

        correct = sum(1 for s in signals if s.is_correct is True)
        returns = [s.return_pct for s in signals if s.return_pct is not None]

        result[key] = {
            "total_signals": total,
            "win_rate": round(correct / total, 4),
            "avg_return_pct": round(sum(returns) / len(returns), 2) if returns else 0.0,
            "winning_signals": correct,
        }

    return result
