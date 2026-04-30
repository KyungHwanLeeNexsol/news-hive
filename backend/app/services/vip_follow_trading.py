"""VIP투자자문 지분 추종 자동매매 서비스.

SPEC-VIP-001의 매매 로직 구현:
- REQ-VIP-002: 5% 이상 공시 시 분할 매수 (1차 즉시, 2차 3영업일 후)
- REQ-VIP-003: 5% 미만 공시 시 전량 매도
- REQ-VIP-004: 수익률 50% 이상 시 30% 부분 익절

SPEC-VIP-REBAL-001 리밸런싱 확장:
- REQ-VIP-REBAL-001~005: 2차 매수 현금 부족 시 VIP 청산 포지션 정리 후 비중 리밸런싱 재시도

기존 paper_trading.py, fund_manager.py와 완전히 분리된 독립 서비스.
"""
import asyncio
import json
import logging
import math
import os
import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.stock import Stock
from app.models.vip_trading import VIPDisclosure, VIPPortfolio, VIPTrade

logger = logging.getLogger(__name__)

# 포지션 사이징: 초기 자본의 5%를 한 공시 종목에 투자 (분할 매수 2회 → 1회당 2.5%)
VIP_POSITION_PCT = 0.05

# 분할 매수 횟수: 1차 + 2차
SPLIT_COUNT = 2

# 2차 매수 대기 거래일 수 (주말 제외)
SECOND_BUY_DAYS = 3

# 부분 익절 임계 수익률 (%)
PROFIT_LOCK_THRESHOLD = 50.0

# 부분 익절 비율 (현재 보유 수량의 30%)
PARTIAL_SELL_PCT = 0.30

# 삼성증권 온라인(MTS) 기준 수수료/거래세
# @MX:NOTE: 매수/매도 각각 0.014% 수수료, 매도 시 거래세 0.18% (KOSPI 증권거래세 0.03% + 농특세 0.15%)
COMMISSION_RATE = 0.00014       # 수수료: 0.014%
TRANSACTION_TAX_RATE = 0.0018   # 거래세: 0.18% (매도 시에만)

# SPEC-VIP-REBAL-001: 리밸런싱 관련 상수
# 비중 편차가 이 임계값을 초과할 때만 리밸런싱 실행 (기본 3%)
REBALANCE_THRESHOLD: float = float(os.getenv("VIP_REBALANCE_THRESHOLD", "0.03"))
# 리밸런싱을 실행할 최소 포지션 수 (2개 미만이면 리밸런싱 의미 없음)
MIN_REBALANCE_POSITIONS: int = 2
# 리밸런싱 관련 로그 접두어 — 로그 검색/필터링 용도
REBALANCE_LOG_PREFIX: str = "[vip_rebal]"
# @MX:WARN: [AUTO] 리밸런싱 동시 실행 방지 Lock — 동일 포트폴리오에 복수 리밸런싱이 중첩되면 현금 잔고 이중 차감 위험
# @MX:REASON: 스케줄러가 복수 태스크를 병렬 실행할 때 _rebalance_lock 미적용 시 race condition 발생
_rebalance_lock: asyncio.Lock = asyncio.Lock()


def get_or_create_vip_portfolio(db: Session) -> VIPPortfolio:
    """활성 VIP 포트폴리오를 가져오거나 생성한다.

    단일 인스턴스 운영 — is_active=True인 포트폴리오가 없으면 신규 생성.

    Args:
        db: DB 세션

    Returns:
        활성 VIPPortfolio 인스턴스
    """
    # @MX:ANCHOR: VIP 포트폴리오 단일 진입점 — 모든 매매 함수가 이 함수를 통해 포트폴리오 획득
    # @MX:REASON: 중복 포트폴리오 생성 방지 및 현금 잔고 일관성 보장
    portfolio = (
        db.query(VIPPortfolio).filter(VIPPortfolio.is_active.is_(True)).first()
    )
    if not portfolio:
        portfolio = VIPPortfolio(
            name="VIP 추종 포트폴리오",
            initial_capital=50_000_000,
            current_cash=50_000_000,
        )
        db.add(portfolio)
        db.commit()
        db.refresh(portfolio)
        logger.info(
            "VIP 포트폴리오 신규 생성: %s (초기자본: %d원)",
            portfolio.name,
            portfolio.initial_capital,
        )
    return portfolio


async def process_new_vip_disclosure(
    db: Session, disclosure: VIPDisclosure
) -> VIPTrade | None:
    """신규 VIP 공시를 처리한다.

    - accumulate + stake_pct >= 5.0: 1차 매수 실행
    - below5 / reduce: 해당 종목 전량 청산

    Args:
        db: DB 세션
        disclosure: 처리할 VIPDisclosure 인스턴스

    Returns:
        생성된 VIPTrade 또는 None
    """
    if disclosure.processed:
        logger.debug("이미 처리된 VIP 공시 스킵: %s", disclosure.rcept_no)
        return None

    try:
        if (
            disclosure.disclosure_type == "accumulate"
            and disclosure.stake_pct is not None
            and disclosure.stake_pct >= 5.0
        ):
            trade = await _handle_accumulate_disclosure(db, disclosure)
        elif disclosure.disclosure_type in ("below5", "reduce"):
            await _handle_exit_disclosure(db, disclosure)
            trade = None
        else:
            # unknown 또는 기준 미달 — processed 처리 후 스킵
            logger.info(
                "VIP 공시 매매 조건 미충족 — 스킵: type=%s, stake=%.2f, rcept_no=%s",
                disclosure.disclosure_type,
                disclosure.stake_pct or 0.0,
                disclosure.rcept_no,
            )
            trade = None

        # 처리 완료 마킹
        disclosure.processed = True
        db.commit()
        return trade

    except Exception as e:
        db.rollback()
        logger.error("VIP 공시 처리 오류 (rcept_no=%s): %s", disclosure.rcept_no, e)
        raise


async def _handle_accumulate_disclosure(
    db: Session, disclosure: VIPDisclosure
) -> VIPTrade | None:
    """5% 이상 매집 공시 처리: 1차 매수 실행.

    Args:
        db: DB 세션
        disclosure: accumulate 유형 공시

    Returns:
        생성된 1차 VIPTrade 또는 None
    """
    if not disclosure.stock_code:
        logger.warning(
            "VIP 공시 종목코드 없음 — 매수 불가: corp=%s, rcept_no=%s",
            disclosure.corp_name,
            disclosure.rcept_no,
        )
        return None

    # 종목 조회 또는 자동 등록
    stock = _get_or_create_stock(db, disclosure)
    if not stock:
        return None

    portfolio = get_or_create_vip_portfolio(db)

    # 이미 같은 종목의 오픈 포지션이 있으면 중복 매수 방지
    existing = (
        db.query(VIPTrade)
        .filter(
            VIPTrade.portfolio_id == portfolio.id,
            VIPTrade.stock_id == stock.id,
            VIPTrade.is_open.is_(True),
        )
        .first()
    )
    if existing:
        logger.info(
            "VIP 이미 오픈 포지션 존재: %s (id=%d), 중복 매수 스킵",
            stock.name,
            existing.id,
        )
        return None

    return await _execute_vip_buy(db, portfolio, disclosure, stock, split_sequence=1)


async def _handle_exit_disclosure(db: Session, disclosure: VIPDisclosure) -> int:
    """5% 미만 또는 처분 공시 처리: 해당 종목 전량 청산.

    Args:
        db: DB 세션
        disclosure: below5 또는 reduce 유형 공시

    Returns:
        청산된 포지션 수
    """
    if not disclosure.stock_code:
        return 0

    stock = db.query(Stock).filter(Stock.stock_code == disclosure.stock_code).first()
    if not stock:
        logger.debug("VIP 매도 대상 종목 미등록: %s", disclosure.stock_code)
        return 0

    return await close_positions_for_stock(db, stock.id, "vip_sell")


# ---------------------------------------------------------------------------
# SPEC-VIP-REBAL-001: 리밸런싱 보조 함수
# ---------------------------------------------------------------------------


def _get_vip_target_weights(db: Session, portfolio_id: int) -> dict[int, float]:
    """VIP 공시 기반 목표 비중을 계산한다.

    각 오픈 포지션 종목의 최신 VIPDisclosure.stake_pct 비율에 따라
    정규화된 목표 비중 딕셔너리를 반환한다.

    Args:
        db: DB 세션
        portfolio_id: VIPPortfolio.id

    Returns:
        {stock_id: target_weight} — 합계 ≈ 1.0 (빈 포지션이면 빈 딕셔너리)
    """
    # 오픈 포지션의 고유 종목 ID 목록
    open_trades: list[VIPTrade] = (
        db.query(VIPTrade)
        .filter(
            VIPTrade.portfolio_id == portfolio_id,
            VIPTrade.is_open.is_(True),
        )
        .all()
    )

    stock_ids = list({t.stock_id for t in open_trades})
    if not stock_ids:
        return {}

    # 종목별 최신 공시 stake_pct 수집
    stake_map: dict[int, float | None] = {}
    for sid in stock_ids:
        latest = (
            db.query(VIPDisclosure)
            .filter(VIPDisclosure.stock_id == sid)
            .order_by(VIPDisclosure.id.desc())
            .first()
        )
        stake_map[sid] = latest.stake_pct if latest else None

    # None 처리: 유효한 값들의 평균으로 대체, 전부 None이면 균등 비중
    valid_stakes = [v for v in stake_map.values() if v is not None]
    if not valid_stakes:
        equal_weight = 1.0 / len(stock_ids)
        return {sid: equal_weight for sid in stock_ids}

    avg_stake = sum(valid_stakes) / len(valid_stakes)
    filled: dict[int, float] = {
        sid: (stake if stake is not None else avg_stake)
        for sid, stake in stake_map.items()
    }

    total = sum(filled.values())
    if total <= 0:
        equal_weight = 1.0 / len(stock_ids)
        return {sid: equal_weight for sid in stock_ids}

    return {sid: w / total for sid, w in filled.items()}


async def _exit_vip_closed_positions(db: Session, portfolio: VIPPortfolio) -> int:
    """VIP가 이미 청산한 종목(reduce/below5)의 오픈 포지션을 모두 매도한다.

    REQ-VIP-REBAL-001: 리밸런싱 1단계 — VIP 철수 종목 정리.
    종목별 최신 공시 타입이 'reduce' 또는 'below5'이면 해당 포지션 전량 매도.

    Args:
        db: DB 세션
        portfolio: 대상 VIPPortfolio

    Returns:
        회수된 현금 총액 (원, 정수) — 포지션 없으면 0
    """
    # 오픈 포지션 종목 목록 조회
    open_trades: list[VIPTrade] = (
        db.query(VIPTrade)
        .filter(
            VIPTrade.portfolio_id == portfolio.id,
            VIPTrade.is_open.is_(True),
        )
        .all()
    )

    stock_ids = sorted({t.stock_id for t in open_trades})
    if not stock_ids:
        return 0

    cash_before = portfolio.current_cash
    exited_stock_ids: list[int] = []

    for sid in stock_ids:
        # 최신 공시 타입 확인
        latest_disc = (
            db.query(VIPDisclosure)
            .filter(VIPDisclosure.stock_id == sid)
            .order_by(VIPDisclosure.id.desc())
            .first()
        )
        if not latest_disc or latest_disc.disclosure_type not in ("reduce", "below5"):
            continue

        # 해당 종목의 오픈 포지션 전량 매도
        trades_to_exit = [t for t in open_trades if t.stock_id == sid]
        stock = db.query(Stock).filter(Stock.id == sid).first()
        if not stock or not stock.stock_code:
            logger.warning(
                "%s 종목 코드 없음(stock_id=%d), 청산 스킵",
                REBALANCE_LOG_PREFIX,
                sid,
            )
            continue

        current_price = await _fetch_price(stock.stock_code)
        if not current_price:
            logger.warning(
                "%s 현재가 조회 실패(stock_id=%d, code=%s), 청산 스킵",
                REBALANCE_LOG_PREFIX,
                sid,
                stock.stock_code,
            )
            continue

        for trade in trades_to_exit:
            await _execute_vip_sell(
                db, trade, current_price, trade.quantity, "vip_rebalance_exit"
            )
            logger.info(
                "%s VIP 철수 포지션 청산: %s %d주 @ %d원 (reason=vip_rebalance_exit)",
                REBALANCE_LOG_PREFIX,
                stock.name,
                trade.quantity,
                current_price,
            )
        exited_stock_ids.append(sid)

    if not exited_stock_ids:
        return 0

    # 실제 회수된 현금 = 커밋 후 포트폴리오 잔고 변화
    db.refresh(portfolio)
    cash_recovered = portfolio.current_cash - cash_before
    logger.info(
        "%s 철수 포지션 청산 완료: %d 종목, 회수 현금 %d원",
        REBALANCE_LOG_PREFIX,
        len(exited_stock_ids),
        cash_recovered,
    )
    return max(0, cash_recovered)


async def _rebalance_to_vip_weights(db: Session, portfolio: VIPPortfolio) -> int:
    """VIP 목표 비중에 맞게 포지션을 조정한다.

    REQ-VIP-REBAL-002~004: 현재 비중이 목표 비중과 REBALANCE_THRESHOLD 이상 차이날 때
    - 초과 비중: 트리밍 매도
    - 부족 비중: 추가 매수 (현금 여력 시)

    포지션이 MIN_REBALANCE_POSITIONS 미만이면 즉시 반환(리밸런싱 불필요).

    Args:
        db: DB 세션
        portfolio: 대상 VIPPortfolio

    Returns:
        순 현금 변화 (원, 정수) — 매도 수익 - 매수 비용
    """
    open_trades: list[VIPTrade] = (
        db.query(VIPTrade)
        .filter(
            VIPTrade.portfolio_id == portfolio.id,
            VIPTrade.is_open.is_(True),
        )
        .all()
    )

    distinct_stocks = list({t.stock_id for t in open_trades})

    # REQ-VIP-REBAL-004: 포지션 수가 최소 기준 미달이면 리밸런싱 불필요
    if len(distinct_stocks) <= MIN_REBALANCE_POSITIONS - 1:
        logger.info(
            "%s 오픈 포지션 수(%d) 최소 기준(%d) 미달 — 리밸런싱 스킵",
            REBALANCE_LOG_PREFIX,
            len(distinct_stocks),
            MIN_REBALANCE_POSITIONS,
        )
        return 0

    target_weights = _get_vip_target_weights(db, portfolio.id)
    if not target_weights:
        return 0

    # 배치 현재가 조회
    stocks_by_id: dict[int, Stock] = {}
    for sid in distinct_stocks:
        s = db.query(Stock).filter(Stock.id == sid).first()
        if s:
            stocks_by_id[sid] = s

    stock_codes = [s.stock_code for s in stocks_by_id.values() if s.stock_code]
    prices = await _fetch_prices_batch(stock_codes)

    # 현재가 조회 실패 종목 제거
    price_by_id: dict[int, int] = {}
    for sid, stock in stocks_by_id.items():
        if stock.stock_code and stock.stock_code in prices:
            price_by_id[sid] = prices[stock.stock_code]

    if not price_by_id:
        return 0

    # 포트폴리오 총 평가액 계산
    holdings: dict[int, int] = {}  # stock_id → 보유 수량 합계
    for trade in open_trades:
        if trade.stock_id in price_by_id:
            holdings[trade.stock_id] = holdings.get(trade.stock_id, 0) + trade.quantity

    position_value = sum(price_by_id[sid] * qty for sid, qty in holdings.items())
    total_portfolio_value = portfolio.current_cash + position_value
    if total_portfolio_value <= 0:
        return 0

    # 현재 비중 계산
    current_weights: dict[int, float] = {
        sid: (price_by_id[sid] * holdings.get(sid, 0)) / total_portfolio_value
        for sid in distinct_stocks
        if sid in price_by_id
    }

    # 편차 기준 정렬 (절댓값 내림차순, 동일 시 stock_id 오름차순)
    sorted_stocks = sorted(
        [sid for sid in distinct_stocks if sid in price_by_id],
        key=lambda sid: (
            -abs(current_weights.get(sid, 0.0) - target_weights.get(sid, 0.0)),
            sid,
        ),
    )

    cash_delta = 0

    # 1단계: 초과 비중 종목 트리밍 매도
    for sid in sorted_stocks:
        cw = current_weights.get(sid, 0.0)
        tw = target_weights.get(sid, 0.0)
        diff = cw - tw
        if diff <= REBALANCE_THRESHOLD:
            continue

        trim_value = diff * total_portfolio_value
        price = price_by_id[sid]
        trim_qty = math.floor(trim_value / price)
        if trim_qty <= 0:
            continue

        # 해당 종목의 첫 번째 오픈 트레이드에서 트리밍
        trade_to_trim = next(
            (t for t in open_trades if t.stock_id == sid and t.is_open), None
        )
        if not trade_to_trim:
            continue

        actual_qty = min(trim_qty, trade_to_trim.quantity)
        await _execute_vip_sell(
            db, trade_to_trim, price, actual_qty, "vip_rebalance_trim"
        )
        trim_proceeds = actual_qty * price  # 근사치 (수수료/세금 전)
        cash_delta += trim_proceeds
        logger.info(
            "%s 비중 트리밍 매도: stock_id=%d %d주 @ %d원 (현재비중=%.1f%%, 목표=%.1f%%)",
            REBALANCE_LOG_PREFIX,
            sid,
            actual_qty,
            price,
            cw * 100,
            tw * 100,
        )

    # 포트폴리오 현금 잔고 갱신
    db.refresh(portfolio)

    # 2단계: 부족 비중 종목 추가 매수
    split_invest = _calculate_position_size(portfolio.initial_capital) // SPLIT_COUNT

    for sid in sorted_stocks:
        cw = current_weights.get(sid, 0.0)
        tw = target_weights.get(sid, 0.0)
        diff = tw - cw
        if diff <= REBALANCE_THRESHOLD:
            continue

        if portfolio.current_cash < split_invest:
            break

        stock = stocks_by_id.get(sid)
        if not stock:
            continue

        latest_disc = (
            db.query(VIPDisclosure)
            .filter(VIPDisclosure.stock_id == sid)
            .order_by(VIPDisclosure.id.desc())
            .first()
        )
        if not latest_disc:
            continue

        # split_sequence=3으로 추가 매수 (리밸런싱 전용 시퀀스)
        new_trade = await _execute_vip_buy(
            db, portfolio, latest_disc, stock, split_sequence=3
        )
        if new_trade:
            cash_delta -= split_invest
            logger.info(
                "%s 비중 추가 매수: stock_id=%d (현재비중=%.1f%%, 목표=%.1f%%)",
                REBALANCE_LOG_PREFIX,
                sid,
                cw * 100,
                tw * 100,
            )

    return cash_delta


async def _try_rebalance_for_second_buy(
    db: Session,
    portfolio: VIPPortfolio,
    target_stock_id: int,
    required_cash: int,
) -> bool:
    """2차 매수를 위해 리밸런싱을 시도하고 필요 현금을 확보한다.

    REQ-VIP-REBAL-005/010:
    - 동시 호출 방지용 Lock 적용 (이미 실행 중이면 즉시 False 반환)
    - Step 1: VIP 철수 포지션 청산
    - Step 2: 비중 리밸런싱
    - 각 단계 후 현금 잔고 재확인

    Args:
        db: DB 세션
        portfolio: 대상 VIPPortfolio
        target_stock_id: 2차 매수 대상 종목 ID (로그용)
        required_cash: 2차 매수에 필요한 현금 (원)

    Returns:
        True: 리밸런싱 후 충분한 현금 확보됨 / False: 현금 부족 또는 Lock 경합
    """
    # 동시 실행 방지 — 이미 Lock이 잡혀 있으면 즉시 포기
    if _rebalance_lock.locked():
        logger.warning(
            "%s 리밸런싱 Lock 경합 — 이미 실행 중이므로 스킵 (stock_id=%d)",
            REBALANCE_LOG_PREFIX,
            target_stock_id,
        )
        return False

    async with _rebalance_lock:
        logger.info(
            "%s 리밸런싱 시작: stock_id=%d, 필요현금=%d원, 현재현금=%d원",
            REBALANCE_LOG_PREFIX,
            target_stock_id,
            required_cash,
            portfolio.current_cash,
        )

        # Step 1: VIP 철수 포지션 청산
        try:
            await _exit_vip_closed_positions(db, portfolio)
        except Exception as e:
            logger.error(
                "%s Step1 철수 포지션 청산 실패: %s", REBALANCE_LOG_PREFIX, e
            )

        db.refresh(portfolio)
        if portfolio.current_cash >= required_cash:
            logger.info(
                "%s Step1 후 현금 충분: %d원 >= %d원",
                REBALANCE_LOG_PREFIX,
                portfolio.current_cash,
                required_cash,
            )
            return True

        # Step 2: 비중 리밸런싱
        try:
            await _rebalance_to_vip_weights(db, portfolio)
        except Exception as e:
            logger.error(
                "%s Step2 비중 리밸런싱 실패: %s", REBALANCE_LOG_PREFIX, e
            )

        db.refresh(portfolio)
        if portfolio.current_cash >= required_cash:
            logger.info(
                "%s Step2 후 현금 충분: %d원 >= %d원",
                REBALANCE_LOG_PREFIX,
                portfolio.current_cash,
                required_cash,
            )
            return True

        logger.warning(
            "%s VIP 잔여 현금 부족 (리밸런싱 후에도 부족): 현재=%d원, 필요=%d원",
            REBALANCE_LOG_PREFIX,
            portfolio.current_cash,
            required_cash,
        )
        return False


async def check_second_buy_pending(db: Session) -> int:
    """3거래일 경과한 1차 매수 포지션에 2차 매수를 실행한다.

    Args:
        db: DB 세션

    Returns:
        실행된 2차 매수 건수
    """
    portfolio = get_or_create_vip_portfolio(db)

    # 1차 매수 포지션 중 오픈 상태인 것 조회
    first_buy_trades = (
        db.query(VIPTrade)
        .filter(
            VIPTrade.portfolio_id == portfolio.id,
            VIPTrade.split_sequence == 1,
            VIPTrade.is_open.is_(True),
        )
        .all()
    )

    executed = 0
    for trade in first_buy_trades:
        # 영업일 경과 체크
        elapsed = _business_days_between(trade.entry_date, datetime.now(timezone.utc))
        if elapsed < SECOND_BUY_DAYS:
            continue

        # 이미 2차 매수가 존재하는지 확인
        second_exists = (
            db.query(VIPTrade)
            .filter(
                VIPTrade.portfolio_id == portfolio.id,
                VIPTrade.stock_id == trade.stock_id,
                VIPTrade.vip_disclosure_id == trade.vip_disclosure_id,
                VIPTrade.split_sequence == 2,
            )
            .first()
        )
        if second_exists:
            continue

        stock = db.query(Stock).filter(Stock.id == trade.stock_id).first()
        if not stock:
            continue

        disclosure = db.query(VIPDisclosure).filter(
            VIPDisclosure.id == trade.vip_disclosure_id
        ).first()
        if not disclosure:
            continue

        logger.info(
            "VIP 2차 매수 실행 조건 충족: %s (1차 entry=%s, 경과=%d 영업일)",
            stock.name,
            trade.entry_date.date(),
            elapsed,
        )

        # 현금 부족 여부 사전 체크 + 리밸런싱 시도 (REQ-VIP-REBAL-005)
        # @MX:NOTE: [AUTO] VIP_REBALANCE_ENABLED=false이면 기존 동작(현금 부족 시 스킵) 유지
        vip_rebalance_enabled = (
            os.getenv("VIP_REBALANCE_ENABLED", "true").lower() != "false"
        )
        split_invest = _calculate_position_size(portfolio.initial_capital) // SPLIT_COUNT

        if portfolio.current_cash < split_invest:
            if vip_rebalance_enabled:
                success = await _try_rebalance_for_second_buy(
                    db, portfolio, stock.id, split_invest
                )
                if not success:
                    logger.warning(
                        "VIP 잔여 현금 부족: cash=%d, 필요=%d (%s 2차 매수)",
                        portfolio.current_cash,
                        split_invest,
                        stock.name,
                    )
                    continue
                # 리밸런싱 성공 후 portfolio 잔고 반영
                db.refresh(portfolio)
            else:
                logger.warning(
                    "VIP 잔여 현금 부족: cash=%d, 필요=%d (%s 2차 매수)",
                    portfolio.current_cash,
                    split_invest,
                    stock.name,
                )
                continue

        result = await _execute_vip_buy(db, portfolio, disclosure, stock, split_sequence=2)
        if result:
            executed += 1

    return executed


async def check_exit_conditions(db: Session) -> dict:
    """모든 오픈 VIP 포지션의 청산 조건을 점검한다.

    조건 1: 수익률 >= 50% AND partial_sold == False → 30% 부분 매도
    조건 2: 미처리 below5/reduce 공시 존재 → 전량 청산 (process_new_vip_disclosure에서 처리)

    Args:
        db: DB 세션

    Returns:
        {"partial_sold": int, "full_exit": int}
    """
    stats: dict[str, int] = {"partial_sold": 0, "full_exit": 0}

    portfolio = get_or_create_vip_portfolio(db)
    open_trades = (
        db.query(VIPTrade)
        .filter(
            VIPTrade.portfolio_id == portfolio.id,
            VIPTrade.is_open.is_(True),
        )
        .all()
    )

    for trade in open_trades:
        stock = db.query(Stock).filter(Stock.id == trade.stock_id).first()
        if not stock or not stock.stock_code:
            continue

        current_price = await _fetch_price(stock.stock_code)
        if not current_price:
            continue

        # 미실현 수익률 계산
        unrealized_pct = (
            (current_price - trade.entry_price) / trade.entry_price * 100
        )

        # 50% 수익률 달성 시 부분 익절 (포지션당 1회)
        if unrealized_pct >= PROFIT_LOCK_THRESHOLD and not trade.partial_sold:
            sell_qty = max(1, int(trade.quantity * PARTIAL_SELL_PCT))
            logger.info(
                "VIP 부분 익절 트리거: %s, 수익률=%.1f%%, 매도수량=%d/%d",
                stock.name,
                unrealized_pct,
                sell_qty,
                trade.quantity,
            )
            await _execute_vip_sell(db, trade, current_price, sell_qty, "profit_lock")
            stats["partial_sold"] += 1

    return stats


async def close_positions_for_stock(
    db: Session, stock_id: int, reason: str
) -> int:
    """특정 종목의 모든 오픈 포지션을 전량 청산한다.

    Args:
        db: DB 세션
        stock_id: 종목 ID
        reason: 청산 사유 ("vip_sell" | "manual" 등)

    Returns:
        청산된 포지션 수
    """
    portfolio = get_or_create_vip_portfolio(db)

    open_trades = (
        db.query(VIPTrade)
        .filter(
            VIPTrade.portfolio_id == portfolio.id,
            VIPTrade.stock_id == stock_id,
            VIPTrade.is_open.is_(True),
        )
        .all()
    )

    if not open_trades:
        return 0

    stock = db.query(Stock).filter(Stock.id == stock_id).first()
    stock_code = stock.stock_code if stock else None

    current_price: int | None = None
    if stock_code:
        current_price = await _fetch_price(stock_code)

    closed = 0
    for trade in open_trades:
        price = current_price or trade.entry_price
        await _execute_vip_sell(db, trade, price, trade.quantity, reason)
        closed += 1

    if closed:
        logger.info(
            "VIP 전량 청산 완료: stock_id=%d, reason=%s, 청산 포지션=%d건",
            stock_id,
            reason,
            closed,
        )

    return closed


async def _execute_vip_buy(
    db: Session,
    portfolio: VIPPortfolio,
    disclosure: VIPDisclosure,
    stock: Stock,
    split_sequence: int,
) -> VIPTrade | None:
    """VIP 추종 매수를 실행한다.

    포지션 크기 = 총 현금 × 10% / SPLIT_COUNT
    가용 현금 부족 시 가능한 만큼만 매수.

    Args:
        db: DB 세션
        portfolio: VIP 포트폴리오
        disclosure: 트리거 공시
        stock: 매수 대상 종목
        split_sequence: 1 또는 2

    Returns:
        생성된 VIPTrade 또는 None
    """
    if not stock.stock_code:
        logger.warning("종목 코드 없음: stock_id=%d", stock.id)
        return None

    current_price = await _fetch_price(stock.stock_code)
    if not current_price or current_price <= 0:
        logger.warning("현재가 조회 실패: %s", stock.stock_code)
        return None

    # 포지션 사이징: 초기 자본 × 5% / 2 (분할 매수 — 종목별 균등 비중)
    max_invest = _calculate_position_size(portfolio.initial_capital)
    split_invest = max_invest // SPLIT_COUNT

    if split_invest < current_price:
        logger.warning(
            "VIP 주가 대비 투자금 부족: cash=%d, split_invest=%d, price=%d (%s %d차 매수)",
            portfolio.current_cash,
            split_invest,
            current_price,
            stock.name,
            split_sequence,
        )
        return None

    if portfolio.current_cash < split_invest:
        logger.warning(
            "VIP 잔여 현금 부족: cash=%d, 필요=%d (%s %d차 매수)",
            portfolio.current_cash,
            split_invest,
            stock.name,
            split_sequence,
        )
        return None

    quantity = split_invest // current_price
    if quantity <= 0:
        return None

    invest_amount = current_price * quantity
    buy_commission = round(invest_amount * COMMISSION_RATE)
    total_buy_cost = invest_amount + buy_commission

    trade = VIPTrade(
        portfolio_id=portfolio.id,
        stock_id=stock.id,
        vip_disclosure_id=disclosure.id,
        split_sequence=split_sequence,
        entry_price=current_price,
        quantity=quantity,
    )
    portfolio.current_cash -= total_buy_cost

    db.add(trade)
    db.commit()
    db.refresh(trade)

    logger.info(
        "VIP %d차 매수: %s %d주 @ %d원 (투자금: %d원, 수수료: %d원, 잔여현금: %d원)",
        split_sequence,
        stock.name,
        quantity,
        current_price,
        invest_amount,
        buy_commission,
        portfolio.current_cash,
    )
    return trade


async def _execute_vip_sell(
    db: Session,
    trade: VIPTrade,
    current_price: int,
    quantity: int,
    reason: str,
) -> None:
    """VIP 추종 매도를 실행한다 (부분 또는 전량).

    전량 매도: is_open=False, exit_price/date/reason/pnl/return_pct 기록
    부분 매도: quantity 차감, partial_sold=True

    Args:
        db: DB 세션
        trade: 청산 대상 VIPTrade
        current_price: 현재가 (시장가)
        quantity: 매도 수량
        reason: 청산 사유
    """
    portfolio = db.query(VIPPortfolio).filter(
        VIPPortfolio.id == trade.portfolio_id
    ).first()

    # 매도 수수료 + 거래세 차감 (삼성증권 MTS 기준)
    gross_proceeds = current_price * quantity
    sell_commission = round(gross_proceeds * COMMISSION_RATE)
    transaction_tax = round(gross_proceeds * TRANSACTION_TAX_RATE)
    net_proceeds = gross_proceeds - sell_commission - transaction_tax

    is_full_exit = quantity >= trade.quantity

    if is_full_exit:
        # 전량 청산 — PnL = 순매도금액 - (매수금액 + 매수수수료 추정치)
        cost_basis = trade.entry_price * trade.quantity
        buy_commission_est = round(cost_basis * COMMISSION_RATE)
        total_cost = cost_basis + buy_commission_est

        pnl = net_proceeds - total_cost
        return_pct = pnl / total_cost * 100 if total_cost > 0 else 0.0

        trade.exit_price = current_price
        trade.exit_date = datetime.now(timezone.utc)
        trade.exit_reason = reason
        trade.pnl = round(pnl)
        trade.return_pct = round(return_pct, 2)
        trade.quantity = 0
        trade.is_open = False
    else:
        # 부분 매도 — 수량만 차감, 포지션 유지
        trade.quantity -= quantity
        trade.partial_sold = True

    if portfolio:
        portfolio.current_cash += net_proceeds

    db.commit()

    stock = db.query(Stock).filter(Stock.id == trade.stock_id).first()
    stock_name = stock.name if stock else f"stock_id={trade.stock_id}"

    logger.info(
        "VIP 매도: %s %d주 @ %d원 (reason=%s, %s, 순회수금: %d원)",
        stock_name,
        quantity,
        current_price,
        reason,
        "전량" if is_full_exit else "부분",
        net_proceeds,
    )


def _calculate_position_size(initial_capital: int) -> int:
    """초기 자본 기준 종목당 투자 금액을 계산한다.

    Args:
        initial_capital: 포트폴리오 초기 자본

    Returns:
        종목당 최대 투자 금액 (초기자본 × 5%)
    """
    return int(initial_capital * VIP_POSITION_PCT)


def _business_days_between(start: datetime, end: datetime) -> int:
    """두 날짜 사이의 영업일 수(주말 제외)를 계산한다.

    공휴일 캘린더 미사용 — 단순 주말(토/일) 제외 카운트.
    SPEC-VIP-001 Assumption 4 참조.

    Args:
        start: 시작 일시
        end: 종료 일시

    Returns:
        영업일 수 (0 이상 정수)
    """
    # timezone-aware 비교를 위해 정규화
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    if end <= start:
        return 0

    business_days = 0
    current = start.date()
    end_date = end.date()

    while current < end_date:
        # 0=월요일, 6=일요일
        if current.weekday() < 5:
            business_days += 1
        from datetime import timedelta
        current += timedelta(days=1)

    return business_days


# 동시 Naver 현재가 요청 제한 — 병렬 조회 시 타임아웃 방지
# asyncio.gather로 18개 종목 동시 요청 시 Naver 서버가 429/timeout을 반환하던 문제 수정
_PRICE_FETCH_SEMAPHORE = asyncio.Semaphore(5)

# 현재가 인메모리 캐시: {stock_code: (price, cached_at)}
# 포트폴리오 재조회 시 Naver API 호출 생략 → 응답 속도 개선
_price_cache: dict[str, tuple[int, float]] = {}
_PRICE_CACHE_TTL = 30  # 30초 TTL — 장중 실시간성과 응답 속도 균형


async def _fetch_price(stock_code: str) -> int | None:
    """종목 현재가를 조회한다.

    # @MX:NOTE: Naver 실시간 polling API 사용 — integration endpoint는 dealTrendInfos[0]가 전일종가를 반환해 오류 발생
    # @MX:REASON: m.stock.naver.com/api/stock/{code}/integration의 dealTrendInfos는 과거 일별 데이터로 실시간 현재가 아님
    # @MX:NOTE: _PRICE_FETCH_SEMAPHORE(5)로 동시 요청 제한 — 병렬 gather 시 Naver 타임아웃 방지
    # @MX:NOTE: _price_cache로 30초 캐시 — 포트폴리오 재조회 시 Naver API 호출 생략
    Args:
        stock_code: 종목 코드

    Returns:
        현재가 (원) 또는 None
    """
    # 캐시 확인
    now = time.monotonic()
    cached = _price_cache.get(stock_code)
    if cached is not None:
        cached_price, cached_at = cached
        if now - cached_at < _PRICE_CACHE_TTL:
            return cached_price

    import httpx
    from app.services.naver_finance import HEADERS
    try:
        url = f"https://polling.finance.naver.com/api/realtime/domestic/stock/{stock_code}"
        async with _PRICE_FETCH_SEMAPHORE:
            async with httpx.AsyncClient(timeout=3, follow_redirects=True) as client:
                resp = await client.get(url, headers=HEADERS)
                resp.raise_for_status()
            data = resp.json()
        datas = data.get("datas") or []
        price_str = datas[0].get("closePrice", "") if datas else ""
        if price_str:
            price = int(str(price_str).replace(",", ""))
            _price_cache[stock_code] = (price, now)
            return price
    except Exception as e:
        logger.warning("현재가 조회 실패 (%s): %s(%s)", stock_code, type(e).__name__, e)
    return None


async def _fetch_prices_batch(stock_codes: list[str]) -> dict[str, int]:
    """여러 종목의 현재가를 Naver 배치 API 한 번으로 조회한다.

    # @MX:NOTE: Naver 배치 API — 최대 50개 종목을 1번 요청으로 조회 (N개별 요청 대비 대폭 빠름)
    # @MX:ANCHOR: 포트폴리오 조회 성능 핵심 경로 — vip/paper trading /positions 및 get_vip_portfolio_stats에서 사용
    # @MX:REASON: 개별 _fetch_price N회 호출 시 semaphore(5) 제약으로 ceil(N/5) 순차 배치 필요 → 배치 API로 1회 요청

    Args:
        stock_codes: 조회할 종목 코드 목록

    Returns:
        {stock_code: current_price} 딕셔너리 (조회 실패 종목은 포함되지 않음)
    """
    if not stock_codes:
        return {}

    now = time.monotonic()
    result: dict[str, int] = {}
    to_fetch: list[str] = []

    # 캐시 히트 먼저 분리
    for code in stock_codes:
        cached = _price_cache.get(code)
        if cached is not None:
            cached_price, cached_at = cached
            if now - cached_at < _PRICE_CACHE_TTL:
                result[code] = cached_price
                continue
        to_fetch.append(code)

    if not to_fetch:
        return result

    import httpx
    from app.services.naver_finance import HEADERS

    # 배치 API: SERVICE_ITEM:{code} 형식으로 최대 50개 한 번에 조회
    _BATCH_SIZE = 50
    for i in range(0, len(to_fetch), _BATCH_SIZE):
        batch = to_fetch[i:i + _BATCH_SIZE]
        # @MX:NOTE: Naver 배치 포맷은 "SERVICE_ITEM:code1,code2,..." — "SERVICE_ITEM:" 반복 시 첫 종목만 반환됨
        query = "SERVICE_ITEM:" + ",".join(batch)
        url = f"https://polling.finance.naver.com/api/realtime?query={query}"
        try:
            async with httpx.AsyncClient(timeout=5, follow_redirects=True) as client:
                resp = await client.get(url, headers=HEADERS)
                resp.raise_for_status()
            text = resp.content.decode("euc-kr", errors="replace")
            data = json.loads(text)
            for area in data.get("result", {}).get("areas", []):
                for item in area.get("datas", []):
                    code = item.get("cd", "")
                    if not code:
                        continue
                    try:
                        price = int(float(item.get("nv", 0) or 0))
                    except (ValueError, TypeError):
                        continue
                    if price > 0:
                        result[code] = price
                        _price_cache[code] = (price, now)
        except Exception as e:
            logger.warning("배치 현재가 조회 실패 — 개별 조회로 폴백: %s", e)
            # 배치 실패 시 기존 개별 조회 폴백
            fallback = await asyncio.gather(*[_fetch_price(c) for c in batch])
            for code, price in zip(batch, fallback):
                if price:
                    result[code] = price

    return result


def _get_or_create_stock(db: Session, disclosure: VIPDisclosure) -> Stock | None:
    """공시 정보로 종목을 조회하거나 자동 등록한다.

    종목 마스터에 없는 경우 최소 정보로 자동 생성.
    SPEC-VIP-001 Assumption 5 참조.

    Args:
        db: DB 세션
        disclosure: VIPDisclosure 인스턴스

    Returns:
        Stock 인스턴스 또는 None
    """
    if not disclosure.stock_code:
        return None

    stock = db.query(Stock).filter(
        Stock.stock_code == disclosure.stock_code
    ).first()

    if not stock:
        # 미등록 종목 자동 생성
        logger.info(
            "VIP 공시 종목 자동 등록: %s (%s)",
            disclosure.corp_name,
            disclosure.stock_code,
        )
        stock = Stock(
            name=disclosure.corp_name,
            stock_code=disclosure.stock_code,
        )
        db.add(stock)
        db.flush()  # id 획득을 위해 flush (아직 commit은 하지 않음)

        # disclosure에 stock_id 연결
        disclosure.stock_id = stock.id

    return stock


async def get_vip_portfolio_stats(db: Session) -> dict:
    """VIP 포트폴리오 통계를 반환한다.

    Args:
        db: DB 세션

    Returns:
        포트폴리오 현황 딕셔너리
    """
    portfolio = get_or_create_vip_portfolio(db)

    open_trades = (
        db.query(VIPTrade)
        .filter(
            VIPTrade.portfolio_id == portfolio.id,
            VIPTrade.is_open.is_(True),
        )
        .all()
    )

    closed_trades = (
        db.query(VIPTrade)
        .filter(
            VIPTrade.portfolio_id == portfolio.id,
            VIPTrade.is_open.is_(False),
        )
        .all()
    )

    # 포지션 평가액 계산 — 배치 API로 현재가 일괄 조회 (N개별 요청 → 1회 요청)
    # N+1 쿼리 방지: open_trades의 stock_id를 한 번에 IN 쿼리로 조회
    open_stock_ids = [t.stock_id for t in open_trades]
    stocks_list = db.query(Stock).filter(Stock.id.in_(open_stock_ids)).all() if open_stock_ids else []
    stocks = {s.id: s for s in stocks_list}

    # 현재가 일괄 조회 (배치 API 1회 호출)
    stock_codes = [s.stock_code for s in stocks_list if s.stock_code]
    prices = await _fetch_prices_batch(stock_codes)

    positions_value = sum(
        (prices.get(stocks[t.stock_id].stock_code, t.entry_price) if t.stock_id in stocks else t.entry_price) * t.quantity
        for t in open_trades
    )

    total_value = portfolio.current_cash + positions_value
    total_pnl = sum((t.pnl or 0) for t in closed_trades)
    total_return_pct = (
        (total_value - portfolio.initial_capital) / portfolio.initial_capital * 100
        if portfolio.initial_capital > 0
        else 0.0
    )

    return {
        "portfolio_id": portfolio.id,
        "name": portfolio.name,
        "initial_capital": portfolio.initial_capital,
        "current_cash": portfolio.current_cash,
        "positions_value": positions_value,
        "total_value": total_value,
        "total_return_pct": round(total_return_pct, 2),
        "realized_pnl": total_pnl,
        "open_positions": len(open_trades),
        "closed_trades": len(closed_trades),
    }
