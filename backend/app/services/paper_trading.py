"""페이퍼 트레이딩 서비스.

AI 시그널 기반 가상 매매를 자동 실행하고 포트폴리오 성과를 추적한다.
"""
import logging
import math
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.fund_signal import FundSignal
from app.models.stock import Stock
from app.models.virtual_portfolio import PortfolioSnapshot, VirtualPortfolio, VirtualTrade

logger = logging.getLogger(__name__)

# 포지션 사이징: 총 자본의 최대 10%를 한 종목에 투자
MAX_POSITION_PCT = 0.10
# 타임아웃: 포지션 최대 보유 기간 (영업일 기준)
MAX_HOLD_DAYS = 10


def get_or_create_portfolio(db: Session) -> VirtualPortfolio:
    """활성 가상 포트폴리오를 가져오거나 생성한다."""
    portfolio = db.query(VirtualPortfolio).filter(VirtualPortfolio.is_active.is_(True)).first()
    if not portfolio:
        portfolio = VirtualPortfolio(
            name="AI 펀드 시뮬레이션",
            initial_capital=100_000_000,
            current_cash=100_000_000,
        )
        db.add(portfolio)
        db.commit()
        db.refresh(portfolio)
        logger.info("가상 포트폴리오 생성: %s (자본금: %d원)", portfolio.name, portfolio.initial_capital)
    return portfolio


async def execute_signal_trade(db: Session, signal: FundSignal) -> VirtualTrade | None:
    """시그널 기반 가상 매매를 실행한다.

    - buy 시그널 + confidence >= 0.6 → long 포지션 진입
    - sell 시그널은 기존 long 포지션 청산 (신규 short은 미지원)
    - hold 시그널은 무시
    """
    if signal.signal == "hold":
        return None
    if signal.signal == "buy" and signal.confidence < 0.6:
        return None

    portfolio = get_or_create_portfolio(db)
    stock = db.query(Stock).filter(Stock.id == signal.stock_id).first()
    if not stock:
        return None

    # sell 시그널: 기존 포지션 청산
    if signal.signal == "sell":
        return await _close_position_by_signal(db, portfolio, signal)

    # buy 시그널: 이미 같은 종목 포지션이 있으면 무시
    existing = (
        db.query(VirtualTrade)
        .filter(
            VirtualTrade.portfolio_id == portfolio.id,
            VirtualTrade.stock_id == signal.stock_id,
            VirtualTrade.is_open.is_(True),
        )
        .first()
    )
    if existing:
        logger.info("이미 오픈 포지션 존재: %s, skip", stock.name)
        return None

    # 포지션 사이징
    entry_price = signal.price_at_signal
    if not entry_price or entry_price <= 0:
        return None

    max_invest = int(portfolio.current_cash * MAX_POSITION_PCT)
    if max_invest < entry_price:
        logger.info("자금 부족: cash=%d, 필요=%d", portfolio.current_cash, entry_price)
        return None

    quantity = max_invest // entry_price
    if quantity <= 0:
        return None

    invest_amount = entry_price * quantity

    # 매매 실행
    trade = VirtualTrade(
        portfolio_id=portfolio.id,
        stock_id=signal.stock_id,
        signal_id=signal.id,
        entry_price=entry_price,
        quantity=quantity,
        direction="long",
        target_price=signal.target_price,
        stop_loss=signal.stop_loss,
    )
    portfolio.current_cash -= invest_amount

    db.add(trade)
    db.commit()
    db.refresh(trade)
    logger.info(
        "가상 매수: %s %d주 @ %d원 (투자금: %d원)",
        stock.name, quantity, entry_price, invest_amount,
    )
    return trade


async def _close_position_by_signal(
    db: Session, portfolio: VirtualPortfolio, signal: FundSignal,
) -> VirtualTrade | None:
    """sell 시그널에 의해 기존 포지션을 청산한다."""
    trade = (
        db.query(VirtualTrade)
        .filter(
            VirtualTrade.portfolio_id == portfolio.id,
            VirtualTrade.stock_id == signal.stock_id,
            VirtualTrade.is_open.is_(True),
        )
        .first()
    )
    if not trade:
        return None

    exit_price = signal.price_at_signal or trade.entry_price
    _close_trade(portfolio, trade, exit_price, "signal_sell")
    db.commit()
    return trade


async def check_exit_conditions(db: Session) -> dict:
    """오픈 포지션의 청산 조건을 확인한다.

    - target_price 도달 → 익절
    - stop_loss 이탈 → 손절
    - MAX_HOLD_DAYS 초과 → 타임아웃 청산

    Returns:
        {"checked": N, "closed": N, "reasons": {"target_hit": N, ...}}
    """
    from app.services.signal_verifier import _get_current_price

    portfolio = db.query(VirtualPortfolio).filter(VirtualPortfolio.is_active.is_(True)).first()
    if not portfolio:
        return {"checked": 0, "closed": 0, "reasons": {}}

    open_trades = (
        db.query(VirtualTrade)
        .filter(
            VirtualTrade.portfolio_id == portfolio.id,
            VirtualTrade.is_open.is_(True),
        )
        .all()
    )

    stats: dict = {"checked": 0, "closed": 0, "reasons": {}}
    now = datetime.now(timezone.utc)

    for trade in open_trades:
        stock = db.query(Stock).filter(Stock.id == trade.stock_id).first()
        if not stock:
            continue

        current_price = await _get_current_price(stock.stock_code)
        if not current_price:
            continue

        stats["checked"] += 1
        exit_reason = None

        # 목표가 도달
        if trade.target_price and current_price >= trade.target_price:
            exit_reason = "target_hit"
        # 손절가 이탈
        elif trade.stop_loss and current_price <= trade.stop_loss:
            exit_reason = "stop_loss"
        # 타임아웃
        elif (now - trade.entry_date).days >= MAX_HOLD_DAYS:
            exit_reason = "timeout"

        if exit_reason:
            _close_trade(portfolio, trade, current_price, exit_reason)
            stats["closed"] += 1
            stats["reasons"][exit_reason] = stats["reasons"].get(exit_reason, 0) + 1
            logger.info(
                "가상 청산: %s @ %d원 (%s), 수익률: %.2f%%",
                stock.name, current_price, exit_reason, trade.return_pct or 0,
            )

    if stats["closed"]:
        db.commit()

    return stats


def _close_trade(
    portfolio: VirtualPortfolio,
    trade: VirtualTrade,
    exit_price: int,
    reason: str,
) -> None:
    """포지션을 청산하고 포트폴리오에 반영한다."""
    trade.exit_price = exit_price
    trade.exit_date = datetime.now(timezone.utc)
    trade.exit_reason = reason
    trade.is_open = False
    trade.pnl = (exit_price - trade.entry_price) * trade.quantity
    trade.return_pct = round((exit_price - trade.entry_price) / trade.entry_price * 100, 2)

    # 현금 반환
    portfolio.current_cash += exit_price * trade.quantity


async def take_daily_snapshot(db: Session) -> PortfolioSnapshot | None:
    """일일 포트폴리오 스냅샷을 기록한다."""
    from app.services.signal_verifier import _get_current_price

    portfolio = db.query(VirtualPortfolio).filter(VirtualPortfolio.is_active.is_(True)).first()
    if not portfolio:
        return None

    # 오픈 포지션 평가
    open_trades = (
        db.query(VirtualTrade)
        .filter(
            VirtualTrade.portfolio_id == portfolio.id,
            VirtualTrade.is_open.is_(True),
        )
        .all()
    )

    positions_value = 0
    for trade in open_trades:
        stock = db.query(Stock).filter(Stock.id == trade.stock_id).first()
        if stock:
            price = await _get_current_price(stock.stock_code)
            if price:
                positions_value += price * trade.quantity
            else:
                # 폴백: 진입가 기준
                positions_value += trade.entry_price * trade.quantity

    total_value = portfolio.current_cash + positions_value
    cumulative_return = round(
        (total_value - portfolio.initial_capital) / portfolio.initial_capital * 100, 2,
    )

    # 전일 스냅샷으로 일일 수익률 계산
    prev_snapshot = (
        db.query(PortfolioSnapshot)
        .filter(PortfolioSnapshot.portfolio_id == portfolio.id)
        .order_by(PortfolioSnapshot.snapshot_date.desc())
        .first()
    )
    daily_return = 0.0
    if prev_snapshot and prev_snapshot.total_value > 0:
        daily_return = round(
            (total_value - prev_snapshot.total_value) / prev_snapshot.total_value * 100, 2,
        )

    snapshot = PortfolioSnapshot(
        portfolio_id=portfolio.id,
        total_value=total_value,
        cash=portfolio.current_cash,
        positions_value=positions_value,
        open_positions=len(open_trades),
        daily_return_pct=daily_return,
        cumulative_return_pct=cumulative_return,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    logger.info("포트폴리오 스냅샷: 총자산=%d, 수익률=%.2f%%", total_value, cumulative_return)
    return snapshot


def get_portfolio_stats(db: Session) -> dict:
    """포트폴리오 종합 성과 통계."""
    portfolio = db.query(VirtualPortfolio).filter(VirtualPortfolio.is_active.is_(True)).first()
    if not portfolio:
        return {"error": "활성 포트폴리오 없음"}

    # 전체 매매 기록
    all_trades = db.query(VirtualTrade).filter(VirtualTrade.portfolio_id == portfolio.id).all()
    closed_trades = [t for t in all_trades if not t.is_open]
    open_trades = [t for t in all_trades if t.is_open]

    # 승률
    wins = sum(1 for t in closed_trades if t.pnl and t.pnl > 0)
    win_rate = round(wins / len(closed_trades) * 100, 1) if closed_trades else 0

    # 평균 수익률
    returns = [t.return_pct for t in closed_trades if t.return_pct is not None]
    avg_return = round(sum(returns) / len(returns), 2) if returns else 0

    # 총 손익
    total_pnl = sum(t.pnl for t in closed_trades if t.pnl is not None)

    # 스냅샷 기반 성과
    snapshots = (
        db.query(PortfolioSnapshot)
        .filter(PortfolioSnapshot.portfolio_id == portfolio.id)
        .order_by(PortfolioSnapshot.snapshot_date.asc())
        .all()
    )

    # Sharpe ratio (일일 수익률 기반, 연환산)
    daily_returns = [s.daily_return_pct for s in snapshots if s.daily_return_pct is not None]
    sharpe_ratio = 0.0
    if len(daily_returns) >= 5:
        mean_r = sum(daily_returns) / len(daily_returns)
        std_r = math.sqrt(sum((r - mean_r) ** 2 for r in daily_returns) / len(daily_returns))
        if std_r > 0:
            sharpe_ratio = round((mean_r / std_r) * math.sqrt(252), 2)

    # MDD (Maximum Drawdown)
    mdd = 0.0
    if snapshots:
        peak = snapshots[0].total_value
        for s in snapshots:
            if s.total_value > peak:
                peak = s.total_value
            drawdown = (peak - s.total_value) / peak * 100
            if drawdown > mdd:
                mdd = drawdown
    mdd = round(mdd, 2)

    # 누적 수익률
    cumulative_return = snapshots[-1].cumulative_return_pct if snapshots else 0

    return {
        "portfolio_id": portfolio.id,
        "portfolio_name": portfolio.name,
        "initial_capital": portfolio.initial_capital,
        "current_cash": portfolio.current_cash,
        "total_trades": len(all_trades),
        "closed_trades": len(closed_trades),
        "open_positions": len(open_trades),
        "win_rate": win_rate,
        "avg_return": avg_return,
        "total_pnl": total_pnl,
        "cumulative_return": cumulative_return,
        "sharpe_ratio": sharpe_ratio,
        "mdd": mdd,
        "sharpe_warning": sharpe_ratio < 1.0 and len(daily_returns) >= 20,
    }
