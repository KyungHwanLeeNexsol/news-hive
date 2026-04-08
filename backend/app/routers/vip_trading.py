"""VIP 추종 트레이딩 API 라우터.

SPEC-VIP-001 REQ-VIP-007: REST API 엔드포인트 제공
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.stock import Stock
from app.models.vip_trading import VIPDisclosure, VIPPortfolio, VIPTrade

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vip-trading", tags=["VIP Trading"])


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
def get_vip_positions(db: Session = Depends(get_db)):
    """현재 오픈 포지션 목록 조회."""
    from app.services.vip_follow_trading import get_or_create_vip_portfolio

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

    result = []
    for trade in open_trades:
        stock = db.query(Stock).filter(Stock.id == trade.stock_id).first()
        disclosure = db.query(VIPDisclosure).filter(
            VIPDisclosure.id == trade.vip_disclosure_id
        ).first()

        invest_amount = trade.entry_price * trade.quantity
        result.append({
            "id": trade.id,
            "stock_code": stock.stock_code if stock else None,
            "stock_name": stock.name if stock else "Unknown",
            "split_sequence": trade.split_sequence,
            "entry_price": trade.entry_price,
            "quantity": trade.quantity,
            "invest_amount": invest_amount,
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


@router.post("/trigger-check")
async def trigger_vip_check(db: Session = Depends(get_db)):
    """VIP 공시 수집 및 청산 조건 체크를 수동으로 트리거한다.

    관리자 전용 엔드포인트.
    SPEC-VIP-001 REQ-VIP-008: 인증 없이 호출되어서는 안 되나,
    현재는 내부 관리 API로 운영 (별도 인증 레이어 추가 권장).
    """
    # @MX:TODO: REQ-VIP-008 — 관리자 인증 미들웨어 추가 필요
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
        fetched = await fetch_vip_disclosures(db, days=3)

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
