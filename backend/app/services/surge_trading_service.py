"""SPEC-AI-013: 급등예측 모의투자 포트폴리오 서비스.

FundSignal(signal_type="surge_candidate") 시그널 기반 자동 매매 로직.
정규장(KST 평일 09:00~15:30) 시간대에만 매수/매도 실행.
"""
import asyncio
import json
import logging
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from math import floor
from typing import Optional

from sqlalchemy.orm import Session
from zoneinfo import ZoneInfo

from app.models.fund_signal import FundSignal
from app.models.stock import Stock
from app.models.surge_portfolio import SurgePortfolio, SurgeTrade
from app.services.naver_finance import fetch_current_price as _fetch_current_price_async

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
MARKET_OPEN = time(9, 0)
MARKET_CLOSE = time(15, 30)


def _get_current_price_sync(stock_code: str) -> Optional[int]:
    """async fetch_current_price를 sync 컨텍스트에서 실행하는 wrapper.

    # @MX:NOTE: [AUTO] asyncio.run()으로 async 가격 조회를 sync 서비스에서 사용하기 위한 어댑터
    # @MX:SPEC: SPEC-AI-013
    테스트에서는 이 함수를 직접 패치하여 async 복잡성 없이 모킹 가능.
    """
    try:
        return asyncio.run(_fetch_current_price_async(stock_code))
    except RuntimeError:
        # 이미 이벤트 루프가 실행 중인 경우 (비정상 컨텍스트)
        return None


def is_market_hours(now: Optional[datetime] = None) -> bool:
    # @MX:ANCHOR: [AUTO] 정규장 시간 가드 — 모든 매수/매도 실행의 전제 조건
    # @MX:REASON: [AUTO] execute_buy_orders, check_exit_conditions, 스케줄러 잡 등 3개 이상 컴포넌트에서 참조
    """KST 평일 09:00~15:30 여부 확인.

    매수/매도 주문은 정규장 시간 외에는 실행하지 않음 (큐잉 X, 단순 스킵).
    """
    now = now or datetime.now(KST)
    # 토요일(5), 일요일(6)은 휴장
    if now.weekday() >= 5:
        return False
    current_time = now.time()
    return MARKET_OPEN <= current_time <= MARKET_CLOSE


def get_or_create_portfolio(db: Session) -> SurgePortfolio:
    """단일 SurgePortfolio 인스턴스 조회 또는 생성 (id=1)."""
    portfolio = db.query(SurgePortfolio).filter(SurgePortfolio.id == 1).first()
    if portfolio is None:
        portfolio = SurgePortfolio(
            initial_capital=Decimal("5000000"),
            current_cash=Decimal("5000000"),
        )
        db.add(portfolio)
        db.commit()
        db.refresh(portfolio)
        logger.info("SurgePortfolio 인스턴스 생성 완료 (id=1)")
    return portfolio


def get_today_signals(
    db: Session,
    min_probability: Decimal = Decimal("0.20"),
) -> list:
    """오늘(KST) 생성된 surge_candidate 시그널 중 확률 임계값 이상 반환.

    FundSignal에는 stock_code 컬럼이 없으므로 Stock 테이블과 조인.
    surge_metadata JSON에서 surge_probability_score를 파싱하여 필터링.
    """
    now_kst = datetime.now(KST)
    today_kst = now_kst.date()

    # surge_candidate 시그널 전체 조회 후 Python 레벨에서 날짜/확률 필터링
    # (created_at timezone 변환을 DB 레벨에서 하지 않아 안정성 확보)
    signals_with_stocks = (
        db.query(FundSignal, Stock)
        .join(Stock, FundSignal.stock_id == Stock.id)
        .filter(FundSignal.signal_type == "surge_candidate")
        .all()
    )

    # Python 레벨에서 날짜 필터 및 확률 필터 적용
    result = []
    for signal, stock in signals_with_stocks:
        # created_at 날짜(KST 변환) 체크
        if signal.created_at is not None:
            signal_date = signal.created_at
            # timezone-aware 처리
            if hasattr(signal_date, 'tzinfo') and signal_date.tzinfo is not None:
                signal_date_kst = signal_date.astimezone(KST)
            else:
                # naive datetime — UTC로 가정
                from datetime import timezone
                signal_date_kst = signal_date.replace(tzinfo=timezone.utc).astimezone(KST)
            if signal_date_kst.date() != today_kst:
                continue
        else:
            continue

        # surge_metadata에서 surge_probability_score 파싱
        probability = _parse_surge_probability(signal.surge_metadata)
        if probability is None or probability < float(min_probability):
            continue

        result.append((signal, stock, probability))

    return result


def _parse_surge_probability(surge_metadata: Optional[str]) -> Optional[float]:
    """surge_metadata JSON 문자열에서 surge_probability_score 파싱."""
    if not surge_metadata:
        return None
    try:
        data = json.loads(surge_metadata)
        score = data.get("surge_probability_score")
        if score is not None:
            return float(score)
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    return None


def get_open_position(db: Session, stock_code: str) -> Optional[SurgeTrade]:
    """해당 종목의 오픈 포지션 조회 (중복 진입 차단용).

    Option B: SurgeTrade.is_open + stock_code 조합으로 중복 판단.
    FundSignal.paper_executed 미사용.
    """
    return (
        db.query(SurgeTrade)
        .filter(
            SurgeTrade.stock_code == stock_code,
            SurgeTrade.is_open.is_(True),
        )
        .first()
    )


def count_today_entries(db: Session) -> int:
    """오늘(KST 기준) 진입한 포지션 수 (열린 포지션 + 당일 청산 포지션 모두 포함)."""
    today_kst = datetime.now(KST).date()
    return (
        db.query(SurgeTrade)
        .filter(SurgeTrade.entry_date == today_kst)
        .count()
    )


def execute_buy_orders(
    db: Session,
    max_daily_entries: int = 5,
    position_pct: Decimal = Decimal("0.20"),
    min_probability: Decimal = Decimal("0.20"),
) -> dict:
    # @MX:ANCHOR: [AUTO] 매수 실행 메인 함수 — 시그널 필터링부터 트랜잭션까지 전체 흐름 담당
    # @MX:REASON: [AUTO] 라우터(POST /surge/execute), 스케줄러(surge_execute_buys) 등 3개 이상 컴포넌트에서 참조
    """매수 실행 메인 함수.

    1. 정규장 시간 체크 (아닐 시 즉시 반환)
    2. 오늘 시그널 조회
    3. 임계값/중복/한도 필터링
    4. 각 시그널에 대해 매수 시도 (가격 조회 → 수량 계산 → 트랜잭션)
    5. 결과 요약 반환

    Returns: {"executed": int, "skipped": int, "failed": int, "details": list}
    """
    if not is_market_hours():
        logger.debug("surge_execute_buys: 정규장 시간 외 — 스킵")
        return {"executed": 0, "skipped": 0, "failed": 0, "details": [], "reason": "market_closed"}

    portfolio = get_or_create_portfolio(db)
    today_signals = get_today_signals(db, min_probability=min_probability)

    today_count = count_today_entries(db)
    executed = 0
    skipped = 0
    failed = 0
    details = []

    for signal, stock, probability in today_signals:
        stock_code = stock.stock_code
        stock_name = stock.name

        # 일일 최대 진입 한도 체크
        if today_count + executed >= max_daily_entries:
            logger.info(
                "surge_execute_buys: 일일 최대 진입 한도(%d) 도달 — %s 스킵",
                max_daily_entries,
                stock_code,
            )
            skipped += 1
            details.append({"stock_code": stock_code, "action": "skipped", "reason": "daily_limit"})
            continue

        # 동일 종목 오픈 포지션 중복 체크
        if get_open_position(db, stock_code):
            logger.debug("surge_execute_buys: %s 이미 오픈 포지션 존재 — 스킵", stock_code)
            skipped += 1
            details.append({"stock_code": stock_code, "action": "skipped", "reason": "duplicate_position"})
            continue

        # 투자금액 계산
        investment_amount = portfolio.initial_capital * position_pct

        # 현금 부족 체크
        if portfolio.current_cash < investment_amount:
            logger.warning(
                "surge_execute_buys: %s 현금 부족 (보유 %s, 필요 %s) — 스킵",
                stock_code,
                portfolio.current_cash,
                investment_amount,
            )
            skipped += 1
            details.append({"stock_code": stock_code, "action": "skipped", "reason": "insufficient_cash"})
            continue

        # 현재가 조회
        current_price = _get_current_price_sync(stock_code)
        if current_price is None:
            logger.warning(
                "surge_execute_buys: %s 현재가 조회 실패 — 스킵",
                stock_code,
            )
            failed += 1
            details.append({"stock_code": stock_code, "action": "failed", "reason": "price_fetch_failed"})
            continue

        # 수량 계산 (floor 처리)
        quantity = floor(float(investment_amount) / float(current_price))
        if quantity <= 0:
            logger.warning(
                "surge_execute_buys: %s 수량 0 (투자금 %s, 현재가 %s) — 스킵",
                stock_code,
                investment_amount,
                current_price,
            )
            skipped += 1
            details.append({"stock_code": stock_code, "action": "skipped", "reason": "quantity_zero"})
            continue

        actual_amount = Decimal(str(current_price)) * quantity

        # 원자적 트랜잭션: current_cash 차감 + SurgeTrade 생성
        try:
            portfolio.current_cash = portfolio.current_cash - actual_amount
            trade = SurgeTrade(
                portfolio_id=portfolio.id,
                stock_code=stock_code,
                stock_name=stock_name,
                signal_id=signal.id,
                entry_price=Decimal(str(current_price)),
                quantity=quantity,
                entry_date=datetime.now(KST).date(),
                is_open=True,
                surge_probability_score=Decimal(str(probability)),
            )
            db.add(trade)
            db.commit()
            db.refresh(portfolio)
            executed += 1
            logger.info(
                "surge_execute_buys: %s(%s) 매수 완료 — 수량=%d, 단가=%s, 금액=%s, 확률=%.2f",
                stock_name,
                stock_code,
                quantity,
                current_price,
                actual_amount,
                probability,
            )
            details.append({
                "stock_code": stock_code,
                "stock_name": stock_name,
                "action": "executed",
                "quantity": quantity,
                "entry_price": float(current_price),
                "amount": float(actual_amount),
                "probability": probability,
            })
        except Exception as e:
            db.rollback()
            logger.error("surge_execute_buys: %s 매수 트랜잭션 실패 — %s", stock_code, e)
            failed += 1
            details.append({"stock_code": stock_code, "action": "failed", "reason": str(e)})

    return {
        "executed": executed,
        "skipped": skipped,
        "failed": failed,
        "details": details,
    }


def calculate_trading_days_elapsed(
    entry_date: date,
    today: Optional[date] = None,
) -> int:
    """평일 카운팅 (단순화: 주말 제외, 공휴일 무시).

    entry_date 이후 today까지의 거래일(평일) 수를 반환.
    today <= entry_date 이면 0 반환.
    """
    today = today or date.today()
    if today <= entry_date:
        return 0
    days = 0
    current = entry_date
    while current < today:
        current += timedelta(days=1)
        if current.weekday() < 5:  # 0=월, 4=금
            days += 1
    return days


def execute_sell(
    db: Session,
    trade: SurgeTrade,
    exit_price: Decimal,
    exit_reason: str,
) -> SurgeTrade:
    """매도 실행 (원자적 트랜잭션: is_open=False + current_cash 가산).

    Args:
        db: DB 세션
        trade: 매도할 SurgeTrade 인스턴스
        exit_price: 매도가
        exit_reason: 종료 사유 ("stop_loss"|"take_profit"|"max_holding_period"|"manual")

    Returns:
        업데이트된 SurgeTrade 인스턴스
    """
    portfolio = db.query(SurgePortfolio).filter(SurgePortfolio.id == trade.portfolio_id).first()
    if portfolio is None:
        raise ValueError(f"SurgePortfolio(id={trade.portfolio_id}) not found")

    proceeds = exit_price * trade.quantity
    portfolio.current_cash = portfolio.current_cash + proceeds

    trade.is_open = False
    trade.exit_date = datetime.now(KST).date()
    trade.exit_price = exit_price
    trade.exit_reason = exit_reason

    db.commit()
    db.refresh(trade)

    pnl_pct = (float(exit_price) - float(trade.entry_price)) / float(trade.entry_price) * 100
    logger.info(
        "surge 매도 완료: %s(%s) exit_reason=%s, 단가=%s, 수익률=%.2f%%",
        trade.stock_name,
        trade.stock_code,
        exit_reason,
        exit_price,
        pnl_pct,
    )
    return trade


def check_exit_conditions(
    db: Session,
    stop_loss_pct: Decimal = Decimal("-0.08"),
    take_profit_pct: Decimal = Decimal("0.15"),
    max_holding_days: int = 5,
) -> dict:
    # @MX:ANCHOR: [AUTO] 종료 조건 체크 메인 함수 — 손절/익절/만기 모든 종료 로직 담당
    # @MX:REASON: [AUTO] 라우터, 스케줄러(surge_check_exits) 등 3개 이상 컴포넌트에서 참조
    """종료 조건 체크 메인 함수.

    1. 정규장 시간 체크 (아닐 시 즉시 반환)
    2. 모든 is_open=True 포지션 순회
    3. 현재가 조회 → PnL 계산
    4. 손절/익절/만기 조건 체크 → 매도 실행
    5. 결과 요약 반환

    Returns: {"closed": int, "still_open": int, "errors": int, "details": list}
    """
    if not is_market_hours():
        logger.debug("surge_check_exits: 정규장 시간 외 — 스킵")
        return {"closed": 0, "still_open": 0, "errors": 0, "details": [], "reason": "market_closed"}

    open_trades = (
        db.query(SurgeTrade)
        .filter(SurgeTrade.is_open.is_(True))
        .all()
    )

    closed = 0
    errors = 0
    still_open = 0
    details = []
    today = datetime.now(KST).date()

    for trade in open_trades:
        # 현재가 조회
        current_price = _get_current_price_sync(trade.stock_code)
        if current_price is None:
            logger.warning(
                "surge_check_exits: %s 현재가 조회 실패 — 다음 사이클로 연기",
                trade.stock_code,
            )
            errors += 1
            details.append({
                "stock_code": trade.stock_code,
                "action": "deferred",
                "reason": "price_fetch_failed",
            })
            continue

        entry_price = float(trade.entry_price)
        curr_price = float(current_price)
        pnl_pct = (curr_price - entry_price) / entry_price

        exit_reason = None

        # 손절 조건
        if Decimal(str(pnl_pct)) <= stop_loss_pct:
            exit_reason = "stop_loss"
        # 익절 조건
        elif Decimal(str(pnl_pct)) >= take_profit_pct:
            exit_reason = "take_profit"
        # 최대 보유 기간 초과
        elif calculate_trading_days_elapsed(trade.entry_date, today) >= max_holding_days:
            exit_reason = "max_holding_period"

        if exit_reason:
            try:
                execute_sell(db, trade, Decimal(str(current_price)), exit_reason)
                closed += 1
                details.append({
                    "stock_code": trade.stock_code,
                    "action": "closed",
                    "exit_reason": exit_reason,
                    "pnl_pct": round(pnl_pct * 100, 2),
                    "exit_price": curr_price,
                })
            except Exception as e:
                db.rollback()
                logger.error(
                    "surge_check_exits: %s 매도 실패 — %s", trade.stock_code, e
                )
                errors += 1
                details.append({
                    "stock_code": trade.stock_code,
                    "action": "error",
                    "reason": str(e),
                })
        else:
            still_open += 1

    return {
        "closed": closed,
        "still_open": still_open,
        "errors": errors,
        "details": details,
    }


def get_portfolio_stats(db: Session) -> dict:
    """포트폴리오 통계 계산.

    현재가 조회를 통해 오픈 포지션 평가액을 계산한다.
    현재가 조회 실패 시 진입가 기준으로 fallback.
    """
    portfolio = get_or_create_portfolio(db)

    open_trades = (
        db.query(SurgeTrade)
        .filter(SurgeTrade.portfolio_id == portfolio.id, SurgeTrade.is_open.is_(True))
        .all()
    )
    closed_count = (
        db.query(SurgeTrade)
        .filter(SurgeTrade.portfolio_id == portfolio.id, SurgeTrade.is_open.is_(False))
        .count()
    )

    open_positions_value = Decimal("0")
    for trade in open_trades:
        current_price = _get_current_price_sync(trade.stock_code)
        if current_price is not None:
            open_positions_value += Decimal(str(current_price)) * trade.quantity
        else:
            # 현재가 조회 실패 시 진입가 기준
            open_positions_value += trade.entry_price * trade.quantity

    current_value = portfolio.current_cash + open_positions_value
    return_pct = (
        float(current_value - portfolio.initial_capital)
        / float(portfolio.initial_capital)
        * 100
        if float(portfolio.initial_capital) > 0
        else 0.0
    )

    return {
        "initial_capital": portfolio.initial_capital,
        "current_cash": portfolio.current_cash,
        "open_positions_value": open_positions_value,
        "current_value": current_value,
        "return_pct": round(return_pct, 4),
        "total_trades_count": len(open_trades) + closed_count,
        "open_positions_count": len(open_trades),
        "closed_trades_count": closed_count,
    }


def get_open_positions_detail(db: Session) -> list:
    """보유 포지션 상세 (현재가, PnL% 포함).

    현재가 조회 실패 시 current_price=None으로 반환.
    """
    open_trades = (
        db.query(SurgeTrade)
        .filter(SurgeTrade.is_open.is_(True))
        .order_by(SurgeTrade.entry_date.desc())
        .all()
    )

    result = []
    today = datetime.now(KST).date()
    for trade in open_trades:
        current_price = _get_current_price_sync(trade.stock_code)
        pnl_pct = None
        if current_price is not None:
            pnl_pct = (
                (float(current_price) - float(trade.entry_price))
                / float(trade.entry_price)
                * 100
            )
        days_held = calculate_trading_days_elapsed(trade.entry_date, today)
        result.append({
            "id": trade.id,
            "stock_code": trade.stock_code,
            "stock_name": trade.stock_name,
            "entry_price": trade.entry_price,
            "current_price": Decimal(str(current_price)) if current_price else None,
            "quantity": trade.quantity,
            "pnl_pct": round(pnl_pct, 4) if pnl_pct is not None else None,
            "entry_date": trade.entry_date,
            "days_held": days_held,
            "surge_probability_score": trade.surge_probability_score,
        })
    return result


def get_closed_trades(db: Session, limit: int = 20, offset: int = 0) -> dict:
    """종료 거래 이력 (페이징)."""
    total = (
        db.query(SurgeTrade)
        .filter(SurgeTrade.is_open.is_(False))
        .count()
    )
    trades = (
        db.query(SurgeTrade)
        .filter(SurgeTrade.is_open.is_(False))
        .order_by(SurgeTrade.exit_date.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )

    items = []
    for trade in trades:
        pnl_pct = None
        holding_days = None
        if trade.exit_price is not None:
            pnl_pct = round(
                (float(trade.exit_price) - float(trade.entry_price))
                / float(trade.entry_price)
                * 100,
                4,
            )
        if trade.exit_date is not None:
            holding_days = calculate_trading_days_elapsed(trade.entry_date, trade.exit_date)

        items.append({
            "id": trade.id,
            "stock_code": trade.stock_code,
            "stock_name": trade.stock_name,
            "entry_price": trade.entry_price,
            "exit_price": trade.exit_price,
            "quantity": trade.quantity,
            "entry_date": trade.entry_date,
            "exit_date": trade.exit_date,
            "exit_reason": trade.exit_reason,
            "pnl_pct": pnl_pct,
            "holding_days": holding_days,
            "surge_probability_score": trade.surge_probability_score,
        })

    return {"items": items, "total": total, "limit": limit, "offset": offset}


def get_performance_timeseries(db: Session, days: int = 30) -> list:
    """누적 수익률 시계열 (days일 단위).

    각 날짜의 누적 수익률(%)을 계산하여 반환한다.
    종료 거래의 entry/exit를 기준으로 일별 손익을 계산한다.
    """
    portfolio = get_or_create_portfolio(db)
    today = datetime.now(KST).date()
    start_date = today - timedelta(days=days)

    # 시작일 이후 종료된 거래만 조회
    closed_trades = (
        db.query(SurgeTrade)
        .filter(
            SurgeTrade.portfolio_id == portfolio.id,
            SurgeTrade.is_open.is_(False),
            SurgeTrade.exit_date >= start_date,
        )
        .order_by(SurgeTrade.exit_date)
        .all()
    )

    # 날짜별 손익 집계
    daily_pnl: dict[date, float] = {}
    for trade in closed_trades:
        if trade.exit_date and trade.exit_price:
            pnl = (float(trade.exit_price) - float(trade.entry_price)) * trade.quantity
            daily_pnl[trade.exit_date] = daily_pnl.get(trade.exit_date, 0.0) + pnl

    # 시계열 생성
    result = []
    cumulative_pnl = 0.0
    initial_capital = float(portfolio.initial_capital)

    current = start_date
    while current <= today:
        pnl = daily_pnl.get(current, 0.0)
        cumulative_pnl += pnl
        cumulative_return_pct = (
            cumulative_pnl / initial_capital * 100 if initial_capital > 0 else 0.0
        )
        result.append({
            "date": current.isoformat(),
            "daily_pnl": round(pnl, 2),
            "cumulative_pnl": round(cumulative_pnl, 2),
            "cumulative_return_pct": round(cumulative_return_pct, 4),
        })
        current += timedelta(days=1)

    return result
