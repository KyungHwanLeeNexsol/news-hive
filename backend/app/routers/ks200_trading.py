"""KOSPI 200 스토캐스틱+이격도 트레이딩 API 라우터.

SPEC-KS200-001 REST API 엔드포인트 제공
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.ks200_trading import KS200Signal, KS200Trade

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ks200-trading", tags=["KS200 Trading"])


def _require_admin(request: Request) -> None:
    """관리자 인증 의존성.

    VIP 라우터와 동일한 인메모리 토큰 방식 사용.
    Authorization: Bearer <token> 헤더를 검증한다.
    """
    from app.routers.auth import _verify_admin_token

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="관리자 인증이 필요합니다.")
    token = auth[7:]
    if not _verify_admin_token(token):
        raise HTTPException(status_code=401, detail="인증 토큰이 만료되었거나 유효하지 않습니다.")


@router.get("/portfolio")
async def get_ks200_portfolio(db: Session = Depends(get_db)):
    """KS200 포트폴리오 현황 조회.

    현금, 포지션 평가금액, 총 손익, 수익률을 반환한다.
    """
    try:
        from app.services.ks200_trading import get_ks200_portfolio_stats

        stats = await get_ks200_portfolio_stats(db)
        return stats
    except Exception as e:
        logger.error("KS200 포트폴리오 현황 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail="포트폴리오 조회 실패")


@router.get("/positions")
async def get_ks200_positions(db: Session = Depends(get_db)):
    """현재 오픈 포지션 목록 조회 (미실현 수익률 포함)."""
    from app.models.stock import Stock
    from app.services.ks200_trading import get_or_create_ks200_portfolio
    from app.services.vip_follow_trading import _fetch_prices_batch

    portfolio = get_or_create_ks200_portfolio(db)
    open_trades = (
        db.query(KS200Trade)
        .filter(
            KS200Trade.portfolio_id == portfolio.id,
            KS200Trade.is_open.is_(True),
        )
        .order_by(KS200Trade.entry_date.desc())
        .all()
    )

    # 종목명 조회
    stock_ids = [t.stock_id for t in open_trades if t.stock_id]
    stocks = db.query(Stock).filter(Stock.id.in_(stock_ids)).all()
    stock_name_map: dict[int, str] = {s.id: s.name for s in stocks}

    # 현재가 배치 조회 (배치 API 1회 호출 — 개별 semaphore 조회 대비 대폭 빠름)
    stock_codes = [t.stock_code for t in open_trades if t.stock_code]
    price_map = await _fetch_prices_batch(stock_codes)

    result = []
    for trade in open_trades:
        current_price = price_map.get(trade.stock_code) if trade.stock_code else None
        invest_amount = trade.entry_price * trade.quantity
        current_value = (current_price * trade.quantity) if current_price else invest_amount
        unrealized_pct = round(
            (current_price - trade.entry_price) / trade.entry_price * 100, 2
        ) if current_price and trade.entry_price else None

        result.append({
            "id": trade.id,
            "stock_code": trade.stock_code,
            "stock_name": stock_name_map.get(trade.stock_id, trade.stock_code),
            "entry_price": trade.entry_price,
            "current_price": current_price,
            "quantity": trade.quantity,
            "entry_date": trade.entry_date.isoformat() if trade.entry_date else None,
            "current_value": current_value,
            "unrealized_pct": unrealized_pct,
        })

    return result


@router.get("/trades")
def get_ks200_trades(
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """거래 이력 조회 (최신순)."""
    from app.models.stock import Stock
    from app.services.ks200_trading import get_or_create_ks200_portfolio

    portfolio = get_or_create_ks200_portfolio(db)
    trades = (
        db.query(KS200Trade)
        .filter(KS200Trade.portfolio_id == portfolio.id)
        .order_by(KS200Trade.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    # 종목명 조회
    stock_ids = [t.stock_id for t in trades if t.stock_id]
    stocks = db.query(Stock).filter(Stock.id.in_(stock_ids)).all()
    stock_name_map: dict[int, str] = {s.id: s.name for s in stocks}

    return [
        {
            "id": t.id,
            "stock_code": t.stock_code,
            "stock_name": stock_name_map.get(t.stock_id, t.stock_code),
            "entry_price": t.entry_price,
            "quantity": t.quantity,
            "entry_date": t.entry_date.isoformat() if t.entry_date else None,
            "exit_price": t.exit_price,
            "exit_date": t.exit_date.isoformat() if t.exit_date else None,
            "exit_reason": t.exit_reason,
            "pnl": t.pnl,
            "return_pct": t.return_pct,
            "is_open": t.is_open,
        }
        for t in trades
    ]


@router.get("/signals")
def get_ks200_signals(
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
    signal_type: str | None = Query(default=None, description="buy 또는 sell 필터"),
):
    """최근 신호 목록 조회 (최신순)."""
    from app.models.stock import Stock

    query = db.query(KS200Signal)
    if signal_type in ("buy", "sell"):
        query = query.filter(KS200Signal.signal_type == signal_type)
    signals = query.order_by(KS200Signal.signal_date.desc()).limit(limit).all()

    # 종목명 조회
    stock_ids = [s.stock_id for s in signals if s.stock_id]
    stocks = db.query(Stock).filter(Stock.id.in_(stock_ids)).all()
    stock_name_map: dict[int, str] = {s.id: s.name for s in stocks}

    return [
        {
            "id": s.id,
            "stock_code": s.stock_code,
            "stock_name": stock_name_map.get(s.stock_id, s.stock_code) if s.stock_id else s.stock_code,
            "signal_type": s.signal_type,
            "stoch_k": round(s.stoch_k, 2),
            "disparity": round(s.disparity, 2),
            "price_at_signal": s.price_at_signal,
            "executed": s.executed,
            "signal_date": s.signal_date.isoformat() if s.signal_date else None,
        }
        for s in signals
    ]


@router.post("/trigger-backfill", dependencies=[Depends(_require_admin)])
async def trigger_ks200_backfill(
    trading_days: int = Query(30, ge=1, le=90, description="소급 계산할 거래일 수 (최대 90일)"),
    db: Session = Depends(get_db),
):
    """KS200 과거 N 거래일 신호를 소급 계산하고 시뮬레이션 매매를 실행한다.

    관리자 전용 엔드포인트. Authorization: Bearer <admin_token> 헤더 필수.
    1단계: backfill_historical_signals — 과거 신호 DB 저장
    2단계: execute_backfill_signals — 날짜 순서대로 시뮬레이션 매매 실행
    """
    try:
        from app.services.ks200_signal import backfill_historical_signals
        from app.services.ks200_trading import execute_backfill_signals

        scan_result = await backfill_historical_signals(db, trading_days)
        exec_result = await execute_backfill_signals(db)
        return {
            "backfill_scan": scan_result,
            "backfill_execution": exec_result,
        }
    except Exception as e:
        logger.error("KS200 백필 실패: %s", e)
        raise HTTPException(status_code=500, detail=f"백필 실패: {e}")


@router.post("/trigger-scan", dependencies=[Depends(_require_admin)])
async def trigger_ks200_scan(db: Session = Depends(get_db)):
    """수동 신호 스캔 및 매매 실행 트리거 (관리자 전용).

    KOSPI 200 전종목 신호 스캔 후 미실행 신호를 즉시 실행한다.
    """
    try:
        from app.services.ks200_signal import run_daily_signal_scan
        from app.services.ks200_trading import execute_pending_signals

        scan_result = await run_daily_signal_scan(db)
        exec_result = await execute_pending_signals(db)
        return {
            "scan": scan_result,
            "execution": exec_result,
        }
    except Exception as e:
        logger.error("KS200 수동 스캔 실패: %s", e)
        raise HTTPException(status_code=500, detail=f"스캔 실패: {e}")
