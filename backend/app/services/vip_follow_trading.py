"""VIP투자자문 지분 추종 자동매매 서비스.

SPEC-VIP-001의 매매 로직 구현:
- REQ-VIP-002: 5% 이상 공시 시 분할 매수 (1차 즉시, 2차 3영업일 후)
- REQ-VIP-003: 5% 미만 공시 시 전량 매도
- REQ-VIP-004: 수익률 50% 이상 시 30% 부분 익절

기존 paper_trading.py, fund_manager.py와 완전히 분리된 독립 서비스.
"""
import asyncio
import logging
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

    trade = VIPTrade(
        portfolio_id=portfolio.id,
        stock_id=stock.id,
        vip_disclosure_id=disclosure.id,
        split_sequence=split_sequence,
        entry_price=current_price,
        quantity=quantity,
    )
    portfolio.current_cash -= invest_amount

    db.add(trade)
    db.commit()
    db.refresh(trade)

    logger.info(
        "VIP %d차 매수: %s %d주 @ %d원 (투자금: %d원, 잔여현금: %d원)",
        split_sequence,
        stock.name,
        quantity,
        current_price,
        invest_amount,
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

    sell_amount = current_price * quantity
    is_full_exit = quantity >= trade.quantity

    if is_full_exit:
        # 전량 청산
        pnl = (current_price - trade.entry_price) * trade.quantity
        return_pct = (current_price - trade.entry_price) / trade.entry_price * 100

        trade.exit_price = current_price
        trade.exit_date = datetime.now(timezone.utc)
        trade.exit_reason = reason
        trade.pnl = pnl
        trade.return_pct = round(return_pct, 2)
        trade.quantity = 0
        trade.is_open = False
    else:
        # 부분 매도 — 수량만 차감, 포지션 유지
        trade.quantity -= quantity
        trade.partial_sold = True

    if portfolio:
        portfolio.current_cash += sell_amount

    db.commit()

    stock = db.query(Stock).filter(Stock.id == trade.stock_id).first()
    stock_name = stock.name if stock else f"stock_id={trade.stock_id}"

    logger.info(
        "VIP 매도: %s %d주 @ %d원 (reason=%s, %s, 회수금: %d원)",
        stock_name,
        quantity,
        current_price,
        reason,
        "전량" if is_full_exit else "부분",
        sell_amount,
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


async def _fetch_price(stock_code: str) -> int | None:
    """종목 현재가를 조회한다.

    # @MX:NOTE: [AUTO] 모바일 API 직접 호출 — KOSPI/KOSDAQ 목록 탐색(2회 HTTP) 생략으로 응답속도 개선
    # @MX:REASON: fetch_current_price는 목록 탐색 2회 후 모바일 fallback으로 종목당 3회 HTTP 요청 발생
    # @MX:NOTE: _PRICE_FETCH_SEMAPHORE(5)로 동시 요청 제한 — 병렬 gather 시 Naver 타임아웃 방지
    Args:
        stock_code: 종목 코드

    Returns:
        현재가 (원) 또는 None
    """
    import httpx
    from app.services.naver_finance import HEADERS
    try:
        url = f"https://m.stock.naver.com/api/stock/{stock_code}/integration"
        async with _PRICE_FETCH_SEMAPHORE:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                resp = await client.get(url, headers=HEADERS)
                resp.raise_for_status()
            data = resp.json()
        deal_infos = data.get("dealTrendInfos") or []
        price_str = (
            (deal_infos[0].get("closePrice", "") if deal_infos else "")
            or data.get("stockInfo", {}).get("closePrice", "")
        )
        if price_str:
            return int(str(price_str).replace(",", ""))
    except Exception as e:
        logger.warning("현재가 조회 실패 (%s): %s(%s)", stock_code, type(e).__name__, e)
    return None


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

    # 포지션 평가액 계산 — 현재가를 병렬 조회하여 응답 지연 최소화
    stocks = {
        trade.stock_id: db.query(Stock).filter(Stock.id == trade.stock_id).first()
        for trade in open_trades
    }

    async def _fetch_trade_value(trade: VIPTrade) -> int:
        stock = stocks.get(trade.stock_id)
        if stock and stock.stock_code:
            price = await _fetch_price(stock.stock_code)
            return (price if price else trade.entry_price) * trade.quantity
        return trade.entry_price * trade.quantity

    trade_values = await asyncio.gather(*[_fetch_trade_value(t) for t in open_trades])
    positions_value = sum(trade_values)

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
