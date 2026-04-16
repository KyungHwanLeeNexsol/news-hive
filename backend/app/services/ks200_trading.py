"""KOSPI 200 스토캐스틱+이격도 매매 실행 서비스.

SPEC-KS200-001
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.ks200_trading import KS200Portfolio, KS200Signal, KS200Trade
from app.models.stock import Stock

logger = logging.getLogger(__name__)

INITIAL_CAPITAL = 100_000_000
MAX_POSITION_PCT = 0.10  # 종목당 최대 투자 비율 10%
POSITION_SIZE = int(INITIAL_CAPITAL * MAX_POSITION_PCT)  # 10,000,000원
MAX_OPEN_POSITIONS = 10

# 삼성증권 온라인(MTS) 기준 수수료/거래세
# @MX:NOTE: 매수/매도 각각 0.014% 수수료, 매도 시 거래세 0.18% (KOSPI 증권거래세 0.03% + 농특세 0.15%)
COMMISSION_RATE = 0.00014       # 수수료: 0.014%
TRANSACTION_TAX_RATE = 0.0018   # 거래세: 0.18% (매도 시에만)


def get_or_create_ks200_portfolio(db: Session) -> KS200Portfolio:
    """KS200 포트폴리오를 조회하거나 없으면 생성한다.

    항상 단일 인스턴스만 운영한다.
    """
    # @MX:ANCHOR: KS200 포트폴리오 단일 인스턴스 획득 지점
    # @MX:REASON: router, execute_pending_signals, get_ks200_portfolio_stats 등 3개 이상 호출
    # @MX:SPEC: SPEC-KS200-001
    portfolio = (
        db.query(KS200Portfolio)
        .filter(KS200Portfolio.is_active.is_(True))
        .first()
    )
    if portfolio is None:
        portfolio = KS200Portfolio(
            name="KOSPI200 스토캐스틱+이격도",
            initial_capital=INITIAL_CAPITAL,
            current_cash=INITIAL_CAPITAL,
            is_active=True,
        )
        db.add(portfolio)
        db.commit()
        db.refresh(portfolio)
        logger.info("KS200 포트폴리오 신규 생성: 초기자본 %d원", INITIAL_CAPITAL)
    return portfolio


async def execute_pending_signals(db: Session) -> dict:
    """미실행 신호(executed=False)를 조회하여 매매를 실행한다.

    매수 신호: 포지션 한도 / 잔고 충분 / 미보유 종목 조건 확인 후 실행
    매도 신호: 해당 종목 오픈 포지션 전량 청산
    실행(또는 스킵) 후 executed=True로 업데이트

    Returns: {"buy_executed": int, "sell_executed": int, "skipped": int}
    """
    portfolio = get_or_create_ks200_portfolio(db)

    # 미실행 신호 조회 (최근 24시간 이내)
    # 15:30 KST 스캔 → 익일 09:05 KST 실행 간격 약 17.5시간을 커버
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    pending_signals = (
        db.query(KS200Signal)
        .filter(
            KS200Signal.executed.is_(False),
            KS200Signal.signal_date >= cutoff,
        )
        .all()
    )

    buy_executed = sell_executed = skipped = 0

    for signal in pending_signals:
        try:
            if signal.signal_type == "buy":
                result = await _execute_buy(db, portfolio, signal)
                if result is not None:
                    buy_executed += 1
                else:
                    skipped += 1
            elif signal.signal_type == "sell":
                closed = await _execute_sell(db, portfolio, signal)
                if closed:
                    sell_executed += 1
                else:
                    skipped += 1

            # 신호를 실행 완료로 마킹
            signal.executed = True

        except Exception as e:
            logger.error(
                "신호 실행 실패 (id=%d, code=%s, type=%s): %s",
                signal.id,
                signal.stock_code,
                signal.signal_type,
                e,
            )
            signal.executed = True  # 오류가 있어도 재시도 방지

    db.commit()
    logger.info(
        "신호 실행 완료: 매수=%d, 매도=%d, 스킵=%d",
        buy_executed,
        sell_executed,
        skipped,
    )
    return {
        "buy_executed": buy_executed,
        "sell_executed": sell_executed,
        "skipped": skipped,
    }


async def execute_backfill_signals(db: Session) -> dict:
    """백필된 미실행 신호를 날짜 순서대로 실행한다 (시뮬레이션).

    현재가를 조회하지 않고 price_at_signal을 체결가로 사용한다.
    신호 발생 순서(signal_date ASC)대로 처리하여 포트폴리오 상태를 일관되게 유지한다.

    Returns: {"buy_executed": int, "sell_executed": int, "skipped": int}
    """
    # @MX:NOTE: 백필 전용 실행 함수 — execute_pending_signals과 구분 (현재가 조회 없음)
    # @MX:REASON: 백필 시뮬레이션은 과거 체결가(price_at_signal) 기반이어야 역사적 정합성 유지
    # @MX:SPEC: SPEC-KS200-001
    portfolio = get_or_create_ks200_portfolio(db)

    # 미실행 신호 전체를 날짜 오름차순으로 조회 (시간 순서대로 시뮬레이션)
    pending_signals = (
        db.query(KS200Signal)
        .filter(KS200Signal.executed.is_(False))
        .order_by(KS200Signal.signal_date.asc())
        .all()
    )

    buy_executed = sell_executed = skipped = 0

    for signal in pending_signals:
        try:
            if signal.signal_type == "buy":
                result = _execute_backfill_buy(db, portfolio, signal)
                if result is not None:
                    buy_executed += 1
                else:
                    skipped += 1
            elif signal.signal_type == "sell":
                closed = _execute_backfill_sell(db, portfolio, signal)
                if closed:
                    sell_executed += 1
                else:
                    skipped += 1

            signal.executed = True
            # 신호마다 커밋하여 포트폴리오 상태(잔고, 포지션)를 순서대로 반영
            db.commit()

        except Exception as e:
            logger.error(
                "백필 신호 실행 실패 (id=%d, code=%s, type=%s): %s",
                signal.id,
                signal.stock_code,
                signal.signal_type,
                e,
            )
            signal.executed = True
            db.commit()

    logger.info(
        "백필 실행 완료: 매수=%d, 매도=%d, 스킵=%d",
        buy_executed,
        sell_executed,
        skipped,
    )
    return {
        "buy_executed": buy_executed,
        "sell_executed": sell_executed,
        "skipped": skipped,
    }


def _execute_backfill_buy(
    db: Session,
    portfolio: KS200Portfolio,
    signal: KS200Signal,
) -> KS200Trade | None:
    """백필 매수 신호를 실행한다 (price_at_signal 기반).

    현재가 조회 없이 신호 발생 시점의 가격을 체결가로 사용한다.
    조건 불충족 시 None 반환.
    """
    # 현재 오픈 포지션 수 확인
    open_count = (
        db.query(KS200Trade)
        .filter(
            KS200Trade.portfolio_id == portfolio.id,
            KS200Trade.is_open.is_(True),
        )
        .count()
    )
    if open_count >= MAX_OPEN_POSITIONS:
        logger.debug("백필 매수 스킵 (%s): 최대 포지션 수 초과", signal.stock_code)
        return None

    # 잔고 확인
    if portfolio.current_cash < signal.price_at_signal:
        logger.debug(
            "백필 매수 스킵 (%s): 잔고 부족 (잔고=%d, 주가=%d)",
            signal.stock_code,
            portfolio.current_cash,
            signal.price_at_signal,
        )
        return None

    # 동일 종목 기존 포지션 확인
    existing_position = (
        db.query(KS200Trade)
        .filter(
            KS200Trade.portfolio_id == portfolio.id,
            KS200Trade.stock_code == signal.stock_code,
            KS200Trade.is_open.is_(True),
        )
        .first()
    )
    if existing_position is not None:
        logger.debug("백필 매수 스킵 (%s): 이미 보유 중", signal.stock_code)
        return None

    # 체결가는 신호 발생 시점의 가격 (현재가 조회 없음)
    exec_price = signal.price_at_signal

    # stock_id 조회
    stock = (
        db.query(Stock)
        .filter(Stock.stock_code == signal.stock_code)
        .first()
    )
    if stock is None:
        logger.warning("백필 매수 스킵 (%s): stocks 테이블에 없는 종목", signal.stock_code)
        return None

    invest_amount = min(POSITION_SIZE, portfolio.current_cash)
    quantity = invest_amount // exec_price
    if quantity <= 0:
        logger.debug("백필 매수 스킵 (%s): 매수 가능 수량 0", signal.stock_code)
        return None

    total_cost = exec_price * quantity
    buy_commission = round(total_cost * COMMISSION_RATE)
    portfolio.current_cash -= (total_cost + buy_commission)

    trade = KS200Trade(
        portfolio_id=portfolio.id,
        stock_id=stock.id,
        stock_code=signal.stock_code,
        entry_price=exec_price,
        quantity=quantity,
        entry_date=signal.signal_date,
        is_open=True,
    )
    db.add(trade)
    logger.info(
        "백필 매수 체결: %s %d주 @ %d원 (투자금=%d원, 수수료=%d원, 잔고=%d원, 기준일=%s)",
        signal.stock_code,
        quantity,
        exec_price,
        total_cost,
        buy_commission,
        portfolio.current_cash,
        signal.signal_date.date() if signal.signal_date else "unknown",
    )
    return trade


def _execute_backfill_sell(
    db: Session,
    portfolio: KS200Portfolio,
    signal: KS200Signal,
) -> bool:
    """백필 매도 신호를 실행한다 (price_at_signal 기반).

    보유 포지션이 없으면 False 반환.
    """
    open_trades = (
        db.query(KS200Trade)
        .filter(
            KS200Trade.portfolio_id == portfolio.id,
            KS200Trade.stock_code == signal.stock_code,
            KS200Trade.is_open.is_(True),
        )
        .all()
    )
    if not open_trades:
        logger.debug("백필 매도 스킵 (%s): 보유 포지션 없음", signal.stock_code)
        return False

    exec_price = signal.price_at_signal
    for trade in open_trades:
        _close_position(db, portfolio, trade, exec_price, reason="backfill_sell")

    return True


async def _execute_buy(
    db: Session,
    portfolio: KS200Portfolio,
    signal: KS200Signal,
) -> KS200Trade | None:
    """매수 신호를 실행한다.

    조건 불충족 시 None 반환:
    - 최대 포지션 수 초과 (MAX_OPEN_POSITIONS=10)
    - 현금 부족 (POSITION_SIZE=10,000,000원 미만)
    - 동일 종목 이미 보유 중
    """
    from app.services.naver_finance import fetch_current_price

    # 현재 오픈 포지션 수 확인
    open_count = (
        db.query(KS200Trade)
        .filter(
            KS200Trade.portfolio_id == portfolio.id,
            KS200Trade.is_open.is_(True),
        )
        .count()
    )
    if open_count >= MAX_OPEN_POSITIONS:
        logger.debug(
            "매수 스킵 (%s): 최대 포지션 수 초과 (%d/%d)",
            signal.stock_code,
            open_count,
            MAX_OPEN_POSITIONS,
        )
        return None

    # 잔고 충분 여부 확인 (최소 1주 매수 가능해야 함)
    if portfolio.current_cash < signal.price_at_signal:
        logger.debug(
            "매수 스킵 (%s): 잔고 부족 (잔고=%d, 주가=%d)",
            signal.stock_code,
            portfolio.current_cash,
            signal.price_at_signal,
        )
        return None

    # 동일 종목 기존 포지션 확인
    existing_position = (
        db.query(KS200Trade)
        .filter(
            KS200Trade.portfolio_id == portfolio.id,
            KS200Trade.stock_code == signal.stock_code,
            KS200Trade.is_open.is_(True),
        )
        .first()
    )
    if existing_position is not None:
        logger.debug("매수 스킵 (%s): 이미 보유 중", signal.stock_code)
        return None

    # 현재가 조회 (실제 체결가)
    try:
        current_price = await fetch_current_price(signal.stock_code)
        if current_price is None or current_price <= 0:
            current_price = signal.price_at_signal
    except Exception as e:
        logger.warning("현재가 조회 실패 (%s), 신호가 사용: %s", signal.stock_code, e)
        current_price = signal.price_at_signal

    # 매수 수량 산정: POSITION_SIZE와 잔고 중 작은 금액으로 최대 수량
    invest_amount = min(POSITION_SIZE, portfolio.current_cash)
    quantity = invest_amount // current_price
    if quantity <= 0:
        logger.debug("매수 스킵 (%s): 매수 가능 수량 0", signal.stock_code)
        return None

    # stock_id 조회
    stock = (
        db.query(Stock)
        .filter(Stock.stock_code == signal.stock_code)
        .first()
    )
    if stock is None:
        logger.warning("매수 스킵 (%s): stocks 테이블에 없는 종목", signal.stock_code)
        return None

    total_cost = current_price * quantity
    buy_commission = round(total_cost * COMMISSION_RATE)
    portfolio.current_cash -= (total_cost + buy_commission)

    trade = KS200Trade(
        portfolio_id=portfolio.id,
        stock_id=stock.id,
        stock_code=signal.stock_code,
        entry_price=current_price,
        quantity=quantity,
        entry_date=datetime.now(timezone.utc),
        is_open=True,
    )
    db.add(trade)
    logger.info(
        "KS200 매수 체결: %s %d주 @ %d원 (투자금=%d원, 수수료=%d원, 잔고=%d원)",
        signal.stock_code,
        quantity,
        current_price,
        total_cost,
        buy_commission,
        portfolio.current_cash,
    )
    return trade


async def _execute_sell(
    db: Session,
    portfolio: KS200Portfolio,
    signal: KS200Signal,
) -> bool:
    """매도 신호를 실행한다 — 해당 종목 오픈 포지션 전량 청산.

    보유 포지션이 없으면 False 반환.
    """
    from app.services.naver_finance import fetch_current_price

    open_trades = (
        db.query(KS200Trade)
        .filter(
            KS200Trade.portfolio_id == portfolio.id,
            KS200Trade.stock_code == signal.stock_code,
            KS200Trade.is_open.is_(True),
        )
        .all()
    )
    if not open_trades:
        logger.debug("매도 스킵 (%s): 보유 포지션 없음", signal.stock_code)
        return False

    # 현재가 조회
    try:
        current_price = await fetch_current_price(signal.stock_code)
        if current_price is None or current_price <= 0:
            current_price = signal.price_at_signal
    except Exception as e:
        logger.warning("현재가 조회 실패 (%s), 신호가 사용: %s", signal.stock_code, e)
        current_price = signal.price_at_signal

    for trade in open_trades:
        _close_position(db, portfolio, trade, current_price, reason="signal_sell")

    return True


def _close_position(
    db: Session,
    portfolio: KS200Portfolio,
    trade: KS200Trade,
    exit_price: int,
    reason: str = "signal_sell",
) -> None:
    """포지션을 청산하고 손익을 계산한다."""
    # 매도 수수료 + 거래세 차감 (삼성증권 MTS 기준)
    sell_proceeds = exit_price * trade.quantity
    sell_commission = round(sell_proceeds * COMMISSION_RATE)
    transaction_tax = round(sell_proceeds * TRANSACTION_TAX_RATE)
    net_proceeds = sell_proceeds - sell_commission - transaction_tax
    portfolio.current_cash += net_proceeds

    # PnL = 순매도금액 - (매수금액 + 매수수수료 추정치)
    cost_basis = trade.entry_price * trade.quantity
    buy_commission_est = round(cost_basis * COMMISSION_RATE)
    total_cost = cost_basis + buy_commission_est

    pnl = net_proceeds - total_cost
    return_pct = pnl / total_cost * 100.0 if total_cost > 0 else 0.0

    trade.exit_price = exit_price
    trade.exit_date = datetime.now(timezone.utc)
    trade.exit_reason = reason
    trade.pnl = round(pnl)
    trade.return_pct = round(return_pct, 4)
    trade.is_open = False

    logger.info(
        "KS200 매도 체결: %s %d주 @ %d원 (PnL=%+d원, %.1f%%, 잔고=%d원)",
        trade.stock_code,
        trade.quantity,
        exit_price,
        pnl,
        return_pct,
        portfolio.current_cash,
    )


async def get_ks200_portfolio_stats(db: Session) -> dict:
    """KS200 포트폴리오 현황 통계를 반환한다."""
    from app.services.vip_follow_trading import _fetch_prices_batch

    portfolio = get_or_create_ks200_portfolio(db)
    open_trades = (
        db.query(KS200Trade)
        .filter(
            KS200Trade.portfolio_id == portfolio.id,
            KS200Trade.is_open.is_(True),
        )
        .all()
    )

    # 오픈 포지션 평가금액 계산 — 배치 API 1회 호출 (순차 개별 조회 → 성능 개선)
    open_stock_codes = [t.stock_code for t in open_trades if t.stock_code]
    prices = await _fetch_prices_batch(open_stock_codes)
    position_value = sum(
        prices.get(t.stock_code, t.entry_price) * t.quantity
        for t in open_trades
    )

    total_value = portfolio.current_cash + position_value
    total_pnl = total_value - portfolio.initial_capital
    total_return_pct = total_pnl / portfolio.initial_capital * 100.0

    # 실현 손익 합계
    closed_trades = (
        db.query(KS200Trade)
        .filter(
            KS200Trade.portfolio_id == portfolio.id,
            KS200Trade.is_open.is_(False),
            KS200Trade.pnl.isnot(None),
        )
        .all()
    )
    realized_pnl = sum(t.pnl for t in closed_trades if t.pnl is not None)

    return {
        "portfolio_id": portfolio.id,
        "name": portfolio.name,
        "initial_capital": portfolio.initial_capital,
        "current_cash": portfolio.current_cash,
        "position_value": position_value,
        "total_value": total_value,
        "total_pnl": total_pnl,
        "total_return_pct": round(total_return_pct, 2),
        "realized_pnl": realized_pnl,
        "open_positions": len(open_trades),
        "max_positions": MAX_OPEN_POSITIONS,
    }
