"""VIP 추종 트레이딩 API 라우터.

SPEC-VIP-001 REQ-VIP-007: REST API 엔드포인트 제공
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.stock import Stock
from app.models.vip_trading import VIPDisclosure, VIPTrade

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vip-trading", tags=["VIP Trading"])


def _require_admin(request: Request) -> None:
    """관리자 인증 의존성.

    fund_manager 라우터와 동일한 인메모리 토큰 방식 사용.
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
async def get_vip_portfolio(db: Session = Depends(get_db)):
    """VIP 포트폴리오 현황 조회.

    현금, 포지션 평가금액, 총 손익을 반환한다.
    """
    try:
        from app.services.vip_follow_trading import get_vip_portfolio_stats
        stats = await get_vip_portfolio_stats(db)
        return stats
    except Exception as e:
        logger.error("VIP 포트폴리오 현황 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail="포트폴리오 조회 실패")


@router.get("/positions")
async def get_vip_positions(db: Session = Depends(get_db)):
    """현재 오픈 포지션 목록 조회 (미실현 수익률 포함)."""
    from app.services.vip_follow_trading import get_or_create_vip_portfolio, _fetch_prices_batch

    portfolio = get_or_create_vip_portfolio(db)
    open_trades = (
        db.query(VIPTrade)
        .filter(
            VIPTrade.portfolio_id == portfolio.id,
            VIPTrade.is_open.is_(True),
        )
        .order_by(VIPTrade.entry_date.desc())
        .all()
    )

    # 종목/공시 정보 일괄 로드 — N+1 쿼리 방지: IN 쿼리로 일괄 조회
    trade_stock_ids = [t.stock_id for t in open_trades]
    trade_disclosure_ids = [t.vip_disclosure_id for t in open_trades if t.vip_disclosure_id]
    stocks_map = {s.id: s for s in db.query(Stock).filter(Stock.id.in_(trade_stock_ids)).all()} if trade_stock_ids else {}
    disclosures_map = {d.id: d for d in db.query(VIPDisclosure).filter(VIPDisclosure.id.in_(trade_disclosure_ids)).all()} if trade_disclosure_ids else {}
    trade_info = [
        (trade, stocks_map.get(trade.stock_id), disclosures_map.get(trade.vip_disclosure_id))
        for trade in open_trades
    ]

    # 현재가 배치 조회 (1회 API 호출)
    batch_codes = [s.stock_code for _, s, _ in trade_info if s and s.stock_code]
    prices_map = await _fetch_prices_batch(batch_codes)
    prices = [prices_map.get(s.stock_code) if s and s.stock_code else None for _, s, _ in trade_info]

    result = []
    for (trade, stock, disclosure), current_price in zip(trade_info, prices):
        invest_amount = trade.entry_price * trade.quantity
        current_value = (current_price * trade.quantity) if current_price else invest_amount
        unrealized_pct = round(
            (current_price - trade.entry_price) / trade.entry_price * 100, 2
        ) if current_price and trade.entry_price else None

        result.append({
            "id": trade.id,
            "stock_code": stock.stock_code if stock else None,
            "stock_name": stock.name if stock else "Unknown",
            "split_sequence": trade.split_sequence,
            "entry_price": trade.entry_price,
            "current_price": current_price,
            "quantity": trade.quantity,
            "invest_amount": invest_amount,
            "current_value": current_value,
            "unrealized_pct": unrealized_pct,
            "entry_date": trade.entry_date.isoformat() if trade.entry_date else None,
            "partial_sold": trade.partial_sold,
            "disclosure_type": disclosure.disclosure_type if disclosure else None,
            "stake_pct": disclosure.stake_pct if disclosure else None,
        })

    return result


@router.get("/trades")
def get_vip_trades(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """전체 매매 내역 조회 (페이지네이션 지원)."""
    from app.services.vip_follow_trading import get_or_create_vip_portfolio

    portfolio = get_or_create_vip_portfolio(db)
    trades = (
        db.query(VIPTrade)
        .filter(VIPTrade.portfolio_id == portfolio.id)
        .order_by(VIPTrade.entry_date.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    result = []
    for trade in trades:
        stock = db.query(Stock).filter(Stock.id == trade.stock_id).first()
        result.append({
            "id": trade.id,
            "stock_code": stock.stock_code if stock else None,
            "stock_name": stock.name if stock else "Unknown",
            "split_sequence": trade.split_sequence,
            "entry_price": trade.entry_price,
            "quantity": trade.quantity,
            "entry_date": trade.entry_date.isoformat() if trade.entry_date else None,
            "exit_price": trade.exit_price,
            "exit_date": trade.exit_date.isoformat() if trade.exit_date else None,
            "exit_reason": trade.exit_reason,
            "pnl": trade.pnl,
            "return_pct": trade.return_pct,
            "partial_sold": trade.partial_sold,
            "is_open": trade.is_open,
        })

    return result


@router.get("/disclosures")
def get_vip_disclosures(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """수집된 VIP 공시 내역 조회 (페이지네이션 지원)."""
    disclosures = (
        db.query(VIPDisclosure)
        .order_by(VIPDisclosure.rcept_dt.desc(), VIPDisclosure.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    result = []
    for d in disclosures:
        result.append({
            "id": d.id,
            "rcept_no": d.rcept_no,
            "corp_name": d.corp_name,
            "stock_code": d.stock_code,
            "stake_pct": d.stake_pct,
            "avg_price": d.avg_price,
            "disclosure_type": d.disclosure_type,
            "rcept_dt": d.rcept_dt,
            "flr_nm": d.flr_nm,
            "report_nm": d.report_nm,
            "processed": d.processed,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        })

    return result


@router.post("/rebalance", dependencies=[Depends(_require_admin)])
def rebalance_positions(db: Session = Depends(get_db)):
    """기존 오픈 포지션 수량을 초기자본 5% 기준으로 재조정한다.

    관리자 전용 엔드포인트. 기존 매수 비중이 불균일한 경우 1회 실행.
    - full_quantity = initial_capital * 0.05 // entry_price
    - partial_sold=True 포지션은 full_quantity * 0.7 (30% 익절 반영)
    - current_cash: 투자금 변동분만큼 조정
    """
    from app.services.vip_follow_trading import get_or_create_vip_portfolio

    portfolio = get_or_create_vip_portfolio(db)
    target_invest = int(portfolio.initial_capital * 0.05)  # 5%

    open_trades = (
        db.query(VIPTrade)
        .filter(VIPTrade.portfolio_id == portfolio.id, VIPTrade.is_open.is_(True))
        .all()
    )

    if not open_trades:
        return {"status": "ok", "message": "오픈 포지션 없음", "adjusted": 0}

    old_total_invest = sum(t.entry_price * t.quantity for t in open_trades)

    adjusted = []
    for trade in open_trades:
        if trade.entry_price <= 0:
            continue
        full_qty = max(1, target_invest // trade.entry_price)
        new_qty = max(1, round(full_qty * 0.7)) if trade.partial_sold else full_qty
        old_qty = trade.quantity
        if old_qty != new_qty:
            adjusted.append({
                "trade_id": trade.id,
                "stock_id": trade.stock_id,
                "split_sequence": trade.split_sequence,
                "old_qty": old_qty,
                "new_qty": new_qty,
                "old_invest": trade.entry_price * old_qty,
                "new_invest": trade.entry_price * new_qty,
            })
            trade.quantity = new_qty

    new_total_invest = sum(t.entry_price * t.quantity for t in open_trades)
    cash_diff = old_total_invest - new_total_invest  # 양수면 현금 증가, 음수면 감소
    portfolio.current_cash = portfolio.current_cash + cash_diff

    db.commit()
    return {
        "status": "ok",
        "target_invest_per_position": target_invest,
        "old_total_invest": old_total_invest,
        "new_total_invest": new_total_invest,
        "cash_diff": cash_diff,
        "current_cash": portfolio.current_cash,
        "adjusted": len(adjusted),
        "details": adjusted,
    }


@router.post("/trigger-check", dependencies=[Depends(_require_admin)])
async def trigger_vip_check(
    days: int = Query(3, ge=1, le=365, description="공시 조회 기간 (일). 백필 시 최대 365일."),
    db: Session = Depends(get_db),
):
    """VIP 공시 수집 및 청산 조건 체크를 수동으로 트리거한다.

    관리자 전용 엔드포인트. Authorization: Bearer <admin_token> 헤더 필수.
    SPEC-VIP-001 REQ-VIP-008
    """
    try:
        from app.services.vip_disclosure_crawler import (
            fetch_vip_disclosures,
            process_unhandled_vip_disclosures,
        )
        from app.services.vip_follow_trading import (
            check_second_buy_pending,
            check_exit_conditions,
        )

        # 1. 신규 공시 수집
        fetched = await fetch_vip_disclosures(db, days=days)

        # 2. 미처리 공시 처리
        processed = await process_unhandled_vip_disclosures(db)

        # 3. 2차 매수 체크
        second_buys = await check_second_buy_pending(db)

        # 4. 청산 조건 체크
        exit_stats = await check_exit_conditions(db)

        return {
            "status": "ok",
            "fetched_disclosures": fetched,
            "processed_disclosures": processed,
            "second_buys_executed": second_buys,
            "partial_sold": exit_stats["partial_sold"],
            "full_exits": exit_stats["full_exit"],
        }
    except Exception as e:
        logger.error("VIP 수동 트리거 실패: %s", e)
        raise HTTPException(status_code=500, detail=f"수동 트리거 실패: {e}")
