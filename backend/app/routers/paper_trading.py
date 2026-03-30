"""페이퍼 트레이딩 API 라우터."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.stock import Stock
from app.models.virtual_portfolio import PortfolioSnapshot, VirtualPortfolio, VirtualTrade
from app.services.paper_trading import get_or_create_portfolio, get_portfolio_stats

router = APIRouter(prefix="/api/paper-trading", tags=["paper-trading"])


@router.get("/stats")
def get_stats(db: Session = Depends(get_db)):
    """포트폴리오 종합 성과 통계."""
    return get_portfolio_stats(db)


@router.get("/positions")
def get_positions(db: Session = Depends(get_db)):
    """오픈 포지션 목록."""
    portfolio = get_or_create_portfolio(db)
    trades = (
        db.query(VirtualTrade)
        .filter(
            VirtualTrade.portfolio_id == portfolio.id,
            VirtualTrade.is_open.is_(True),
        )
        .all()
    )
    result = []
    for t in trades:
        stock = db.query(Stock).filter(Stock.id == t.stock_id).first()
        result.append({
            "id": t.id,
            "stock_name": stock.name if stock else "Unknown",
            "stock_code": stock.stock_code if stock else "",
            "direction": t.direction,
            "entry_price": t.entry_price,
            "quantity": t.quantity,
            "target_price": t.target_price,
            "stop_loss": t.stop_loss,
            "entry_date": t.entry_date.isoformat() if t.entry_date else None,
            "invest_amount": t.entry_price * t.quantity,
        })
    return result


@router.get("/trades")
def get_trade_history(limit: int = 50, db: Session = Depends(get_db)):
    """청산된 매매 이력."""
    portfolio = get_or_create_portfolio(db)
    trades = (
        db.query(VirtualTrade)
        .filter(
            VirtualTrade.portfolio_id == portfolio.id,
            VirtualTrade.is_open.is_(False),
        )
        .order_by(VirtualTrade.exit_date.desc())
        .limit(limit)
        .all()
    )
    result = []
    for t in trades:
        stock = db.query(Stock).filter(Stock.id == t.stock_id).first()
        result.append({
            "id": t.id,
            "stock_name": stock.name if stock else "Unknown",
            "direction": t.direction,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "quantity": t.quantity,
            "pnl": t.pnl,
            "return_pct": t.return_pct,
            "exit_reason": t.exit_reason,
            "entry_date": t.entry_date.isoformat() if t.entry_date else None,
            "exit_date": t.exit_date.isoformat() if t.exit_date else None,
        })
    return result


@router.get("/snapshots")
def get_snapshots(days: int = 30, db: Session = Depends(get_db)):
    """일일 포트폴리오 스냅샷 (차트용)."""
    portfolio = get_or_create_portfolio(db)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    snapshots = (
        db.query(PortfolioSnapshot)
        .filter(
            PortfolioSnapshot.portfolio_id == portfolio.id,
            PortfolioSnapshot.snapshot_date >= cutoff,
        )
        .order_by(PortfolioSnapshot.snapshot_date.asc())
        .all()
    )
    return [
        {
            "date": s.snapshot_date.isoformat(),
            "total_value": s.total_value,
            "cash": s.cash,
            "positions_value": s.positions_value,
            "daily_return_pct": s.daily_return_pct,
            "cumulative_return_pct": s.cumulative_return_pct,
            "open_positions": s.open_positions,
        }
        for s in snapshots
    ]


@router.post("/reset")
def reset_portfolio(db: Session = Depends(get_db)):
    """포트폴리오 초기화 (모든 매매 기록 삭제, 자본금 리셋)."""
    portfolio = db.query(VirtualPortfolio).filter(VirtualPortfolio.is_active.is_(True)).first()
    if portfolio:
        db.query(PortfolioSnapshot).filter(PortfolioSnapshot.portfolio_id == portfolio.id).delete()
        db.query(VirtualTrade).filter(VirtualTrade.portfolio_id == portfolio.id).delete()
        portfolio.current_cash = portfolio.initial_capital
        db.commit()
        return {"message": "포트폴리오 초기화 완료", "capital": portfolio.initial_capital}
    return {"message": "활성 포트폴리오 없음"}
