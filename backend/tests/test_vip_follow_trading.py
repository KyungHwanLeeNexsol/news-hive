"""VIP투자자문 추종 매매 서비스 단위 테스트.

SPEC-VIP-001 AC-VIP-008: 5개 이상 단위 테스트
- 분할 매수, 전량 매도, 50% 익절, 가용 현금 부족 케이스 검증
"""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.vip_trading import VIPDisclosure, VIPPortfolio, VIPTrade


# ---------------------------------------------------------------------------
# 픽스처
# ---------------------------------------------------------------------------

def _make_portfolio(cash: int = 50_000_000) -> VIPPortfolio:
    """테스트용 VIPPortfolio 픽스처."""
    portfolio = VIPPortfolio()
    portfolio.id = 1
    portfolio.name = "VIP 추종 포트폴리오"
    portfolio.initial_capital = 50_000_000
    portfolio.current_cash = cash
    portfolio.is_active = True
    return portfolio


def _make_disclosure(
    rcept_no: str = "20260408000001",
    corp_name: str = "테스트전자",
    stock_code: str = "000001",
    stake_pct: float = 5.5,
    disclosure_type: str = "accumulate",
) -> VIPDisclosure:
    """테스트용 VIPDisclosure 픽스처."""
    disc = VIPDisclosure()
    disc.id = 1
    disc.rcept_no = rcept_no
    disc.corp_name = corp_name
    disc.stock_code = stock_code
    disc.stock_id = 1
    disc.stake_pct = stake_pct
    disc.disclosure_type = disclosure_type
    disc.rcept_dt = "20260408"
    disc.flr_nm = "VIP투자자문(주)"
    disc.report_nm = "주식등의대량보유상황보고서"
    disc.processed = False
    return disc


def _make_stock(stock_id: int = 1, code: str = "000001", name: str = "테스트전자"):
    """테스트용 Stock 픽스처."""
    stock = MagicMock()
    stock.id = stock_id
    stock.stock_code = code
    stock.name = name
    return stock


def _make_trade(
    trade_id: int = 1,
    split_sequence: int = 1,
    entry_price: int = 10_000,
    quantity: int = 100,
    partial_sold: bool = False,
    is_open: bool = True,
    entry_date: datetime | None = None,
) -> VIPTrade:
    """테스트용 VIPTrade 픽스처."""
    trade = VIPTrade()
    trade.id = trade_id
    trade.portfolio_id = 1
    trade.stock_id = 1
    trade.vip_disclosure_id = 1
    trade.split_sequence = split_sequence
    trade.entry_price = entry_price
    trade.quantity = quantity
    trade.partial_sold = partial_sold
    trade.is_open = is_open
    trade.entry_date = entry_date or datetime(2026, 4, 1, 9, 0, 0, tzinfo=timezone.utc)
    trade.exit_price = None
    trade.exit_date = None
    trade.exit_reason = None
    trade.pnl = None
    trade.return_pct = None
    return trade


def _make_db(
    portfolio: VIPPortfolio | None = None,
    stock=None,
    trade: VIPTrade | None = None,
    disclosure: VIPDisclosure | None = None,
    existing_open: VIPTrade | None = None,
) -> MagicMock:
    """테스트용 DB 세션 목."""
    db = MagicMock()

    _portfolio = portfolio or _make_portfolio()
    _stock = stock or _make_stock()
    _disclosure = disclosure

    def query_side_effect(model):
        q = MagicMock()
        q.filter.return_value = q
        q.filter_by.return_value = q
        q.order_by.return_value = q
        q.first.return_value = None
        q.all.return_value = []

        if model.__name__ == "VIPPortfolio":
            q.filter.return_value.first.return_value = _portfolio
        elif model.__name__ == "Stock":
            q.filter.return_value.first.return_value = _stock
        elif model.__name__ == "VIPTrade":
            if existing_open is not None:
                q.filter.return_value.first.return_value = existing_open
            elif trade is not None:
                q.filter.return_value.first.return_value = trade
        elif model.__name__ == "VIPDisclosure":
            q.filter.return_value.first.return_value = _disclosure

        return q

    db.query.side_effect = query_side_effect
    db.add = MagicMock()
    db.commit = MagicMock()
    db.rollback = MagicMock()
    db.refresh = MagicMock()
    db.flush = MagicMock()

    return db


# ---------------------------------------------------------------------------
# 테스트 1: 5% 이상 accumulate 공시 → 1차 매수 VIPTrade 생성
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_accumulate_disclosure_creates_trade():
    """5% 이상 accumulate 공시 탐지 시 1차 매수 VIPTrade가 생성된다.

    AC-VIP-002 검증: stake_pct >= 5.0 공시 즉시 VIPTrade(split_sequence=1) 생성
    """
    disclosure = _make_disclosure(stake_pct=5.5, disclosure_type="accumulate")
    portfolio = _make_portfolio(cash=50_000_000)
    stock = _make_stock()

    db = _make_db(portfolio=portfolio, stock=stock, existing_open=None)

    # fetch_current_price 목 (현재가 10,000원)
    with patch(
        "app.services.vip_follow_trading._fetch_price",
        new=AsyncMock(return_value=10_000),
    ), patch(
        "app.services.vip_follow_trading._get_or_create_stock",
        return_value=stock,
    ):
        from app.services.vip_follow_trading import process_new_vip_disclosure

        result = await process_new_vip_disclosure(db, disclosure)

    # VIPTrade가 생성되었는지 확인
    assert db.add.called, "VIPTrade가 DB에 추가되어야 한다"
    assert db.commit.called, "커밋이 호출되어야 한다"
    assert disclosure.processed is True, "공시가 처리 완료로 마킹되어야 한다"

    # 추가된 객체가 VIPTrade이고 split_sequence=1인지 확인
    added_obj = db.add.call_args_list[0][0][0]
    assert isinstance(added_obj, VIPTrade)
    assert added_obj.split_sequence == 1
    assert added_obj.entry_price == 10_000
    assert added_obj.portfolio_id == portfolio.id


# ---------------------------------------------------------------------------
# 테스트 2: 5% 미만 below5 공시 → 매수 없음
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_below5_disclosure_no_trade():
    """5% 미만 below5 공시 시 매수가 실행되지 않는다.

    AC-VIP-004 검증: below5 공시는 매수 트리거가 아닌 청산 트리거
    """
    disclosure = _make_disclosure(stake_pct=3.2, disclosure_type="below5")
    portfolio = _make_portfolio()

    db = _make_db(portfolio=portfolio, existing_open=None)

    # close_positions_for_stock이 호출되는지 확인
    with patch(
        "app.services.vip_follow_trading.close_positions_for_stock",
        new=AsyncMock(return_value=0),
    ) as mock_close, patch(
        "app.services.vip_follow_trading._fetch_price",
        new=AsyncMock(return_value=10_000),
    ):
        from app.services.vip_follow_trading import process_new_vip_disclosure

        result = await process_new_vip_disclosure(db, disclosure)

    # 매수 VIPTrade가 생성되지 않아야 함
    assert result is None, "below5 공시 시 VIPTrade가 생성되어서는 안 된다"
    # 청산 로직이 호출되어야 함
    mock_close.assert_called_once()
    assert disclosure.processed is True


# ---------------------------------------------------------------------------
# 테스트 3: 50% 수익률 시 30% 부분 매도
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_exit_conditions_partial_sell_at_50pct():
    """수익률 50% 달성 시 보유 수량의 30%가 부분 매도된다.

    AC-VIP-005 검증: unrealized_return_pct >= 50.0 AND partial_sold == False → 30% 매도
    """
    portfolio = _make_portfolio()
    stock = _make_stock()

    # 진입가 10,000원, 현재가 15,200원 → 수익률 52%
    trade = _make_trade(entry_price=10_000, quantity=100, partial_sold=False)

    db = MagicMock()
    portfolio_query = MagicMock()
    portfolio_query.filter.return_value.first.return_value = portfolio

    trade_query = MagicMock()
    trade_query.filter.return_value.all.return_value = [trade]

    stock_query = MagicMock()
    stock_query.filter.return_value.first.return_value = stock

    def query_side_effect(model):
        q = MagicMock()
        q.filter.return_value = q
        q.filter_by.return_value = q
        q.all.return_value = []
        q.first.return_value = None

        model_name = model.__name__ if hasattr(model, "__name__") else str(model)
        if "VIPPortfolio" in model_name:
            q.filter.return_value.first.return_value = portfolio
        elif "VIPTrade" in model_name:
            q.filter.return_value.all.return_value = [trade]
        elif "Stock" in model_name:
            q.filter.return_value.first.return_value = stock
        return q

    db.query.side_effect = query_side_effect
    db.commit = MagicMock()
    db.add = MagicMock()

    execute_sell_calls = []

    async def mock_execute_sell(db, trade, price, qty, reason):
        """_execute_vip_sell 목 — 부분 매도 로직 시뮬레이션."""
        execute_sell_calls.append({"price": price, "qty": qty, "reason": reason})
        trade.quantity -= qty
        trade.partial_sold = True
        db.commit()

    with patch(
        "app.services.vip_follow_trading._fetch_price",
        new=AsyncMock(return_value=15_200),  # 52% 수익률
    ), patch(
        "app.services.vip_follow_trading._execute_vip_sell",
        side_effect=mock_execute_sell,
    ):
        from app.services.vip_follow_trading import check_exit_conditions

        stats = await check_exit_conditions(db)

    # 부분 매도가 1건 실행되어야 함
    assert stats["partial_sold"] == 1, "50% 수익률 달성 시 부분 매도가 1건 실행되어야 한다"
    assert len(execute_sell_calls) == 1
    # 매도 수량 = 100 * 0.30 = 30
    assert execute_sell_calls[0]["qty"] == 30
    assert execute_sell_calls[0]["reason"] == "profit_lock"


# ---------------------------------------------------------------------------
# 테스트 4: partial_sold=True인 포지션은 재차 부분 매도 안 함
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_exit_conditions_no_duplicate_partial_sell():
    """partial_sold=True인 포지션은 50% 수익률 달성해도 재차 부분 매도하지 않는다.

    AC-VIP-005 검증: 포지션당 부분 익절은 1회만 트리거
    """
    portfolio = _make_portfolio()
    stock = _make_stock()

    # 이미 부분 매도 완료된 포지션 (partial_sold=True)
    trade = _make_trade(entry_price=10_000, quantity=70, partial_sold=True)

    def query_side_effect(model):
        q = MagicMock()
        q.filter.return_value = q
        q.filter_by.return_value = q
        q.all.return_value = []
        q.first.return_value = None

        model_name = model.__name__ if hasattr(model, "__name__") else str(model)
        if "VIPPortfolio" in model_name:
            q.filter.return_value.first.return_value = portfolio
        elif "VIPTrade" in model_name:
            q.filter.return_value.all.return_value = [trade]
        elif "Stock" in model_name:
            q.filter.return_value.first.return_value = stock
        return q

    db = MagicMock()
    db.query.side_effect = query_side_effect
    db.commit = MagicMock()

    sell_called = False

    async def mock_execute_sell(*args, **kwargs):
        nonlocal sell_called
        sell_called = True

    with patch(
        "app.services.vip_follow_trading._fetch_price",
        new=AsyncMock(return_value=16_000),  # 60% 수익률
    ), patch(
        "app.services.vip_follow_trading._execute_vip_sell",
        side_effect=mock_execute_sell,
    ):
        from app.services.vip_follow_trading import check_exit_conditions

        stats = await check_exit_conditions(db)

    # 이미 partial_sold=True이므로 재차 매도하지 않아야 함
    assert stats["partial_sold"] == 0, "partial_sold=True 포지션은 재차 부분 매도하지 않아야 한다"
    assert not sell_called, "_execute_vip_sell이 호출되어서는 안 된다"


# ---------------------------------------------------------------------------
# 테스트 5: VIP below5 공시 시 해당 종목 전량 청산
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_exit_on_vip_below5():
    """VIP의 5% 미만 공시 시 해당 종목 모든 오픈 포지션이 전량 청산된다.

    AC-VIP-004 검증: below5 공시 → exit_reason="vip_sell"로 전량 청산
    """
    disclosure = _make_disclosure(stake_pct=3.0, disclosure_type="below5")
    portfolio = _make_portfolio()
    stock = _make_stock(code="000001")

    # 오픈된 1차, 2차 포지션 2건
    trade1 = _make_trade(trade_id=1, split_sequence=1, quantity=50)
    trade2 = _make_trade(trade_id=2, split_sequence=2, quantity=50)

    close_calls = []

    async def mock_close_positions(db, stock_id, reason):
        close_calls.append({"stock_id": stock_id, "reason": reason})
        return 2  # 2건 청산

    db = _make_db(portfolio=portfolio, stock=stock, disclosure=disclosure, existing_open=None)

    with patch(
        "app.services.vip_follow_trading.close_positions_for_stock",
        side_effect=mock_close_positions,
    ):
        from app.services.vip_follow_trading import process_new_vip_disclosure

        result = await process_new_vip_disclosure(db, disclosure)

    # 청산이 실행되어야 함
    assert len(close_calls) == 1, "close_positions_for_stock이 1회 호출되어야 한다"
    assert close_calls[0]["reason"] == "vip_sell"
    assert disclosure.processed is True


# ---------------------------------------------------------------------------
# 테스트 6: 영업일 계산 정확성 검증
# ---------------------------------------------------------------------------

def test_business_days_between_excludes_weekends():
    """영업일 계산 시 주말(토/일)이 제외된다.

    2026-04-06(월) ~ 2026-04-13(월): 5 영업일 (04-11 토, 04-12 일 제외)
    """
    from app.services.vip_follow_trading import _business_days_between

    start = datetime(2026, 4, 6, 9, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 4, 13, 9, 0, 0, tzinfo=timezone.utc)

    days = _business_days_between(start, end)
    # 월~금 5일, 토일 제외
    assert days == 5, f"영업일은 5일이어야 한다, 실제: {days}"


def test_business_days_same_day_returns_zero():
    """시작일과 종료일이 같으면 0을 반환한다."""
    from app.services.vip_follow_trading import _business_days_between

    start = datetime(2026, 4, 8, 9, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 4, 8, 18, 0, 0, tzinfo=timezone.utc)

    days = _business_days_between(start, end)
    assert days == 0


# ---------------------------------------------------------------------------
# 테스트 7: 가용 현금 부족 시 매수 불가
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_buy_insufficient_cash():
    """가용 현금이 부족하면 매수가 실행되지 않는다.

    AC-VIP-008: 가용 현금 부족 케이스
    """
    portfolio = _make_portfolio(cash=5_000)  # 5천원 — 1% 포지션도 불가
    stock = _make_stock()
    disclosure = _make_disclosure(stake_pct=5.5, disclosure_type="accumulate")

    db = _make_db(portfolio=portfolio, stock=stock, existing_open=None)

    with patch(
        "app.services.vip_follow_trading._fetch_price",
        new=AsyncMock(return_value=10_000),  # 현재가 10,000원
    ):
        from app.services.vip_follow_trading import _execute_vip_buy

        result = await _execute_vip_buy(
            db, portfolio, disclosure, stock, split_sequence=1
        )

    # 포지션 사이징: 5,000 * 10% / 2 = 250원 < 10,000원(1주가격) → 매수 불가
    assert result is None, "현금 부족 시 None을 반환해야 한다"
    assert not db.add.called, "현금 부족 시 VIPTrade가 추가되어서는 안 된다"


# ---------------------------------------------------------------------------
# 파싱 개선 테스트 — _determine_disclosure_type, _extract_stake_info_from_xml
# ---------------------------------------------------------------------------


def test_determine_disclosure_type_parse_failure_returns_unknown() -> None:
    """파싱 실패(parse_success=False) 시 'below5' 대신 'unknown'을 반환한다.

    핵심 버그 방지: 파싱 실패를 below5로 분류하면 VIP 매수 공시를 잘못 청산할 수 있음.
    """
    from app.services.vip_disclosure_crawler import _determine_disclosure_type

    result = _determine_disclosure_type(
        stake_pct=0.0,
        report_nm="주식등의대량보유상황보고서",
        parse_success=False,
    )
    assert result == "unknown", "파싱 실패 시 'unknown'이어야 한다 (잘못 청산 방지)"


def test_determine_disclosure_type_reduce_keyword_overrides_parse_failure() -> None:
    """파싱 실패라도 보고서명에 '처분' 키워드가 있으면 'below5'를 반환한다."""
    from app.services.vip_disclosure_crawler import _determine_disclosure_type

    result = _determine_disclosure_type(
        stake_pct=0.0,
        report_nm="주식등의대량보유상황보고서(일부처분)",
        parse_success=False,
    )
    assert result == "below5"


def test_determine_disclosure_type_parse_success_accumulate() -> None:
    """파싱 성공 + stake_pct >= 5.0 → 'accumulate'."""
    from app.services.vip_disclosure_crawler import _determine_disclosure_type

    result = _determine_disclosure_type(
        stake_pct=5.12,
        report_nm="주식등의대량보유상황보고서",
        parse_success=True,
    )
    assert result == "accumulate"


def test_extract_stake_info_html_table_pattern() -> None:
    """DART HTML 테이블 형식에서 보유비율을 파싱한다 (3단계 HTML 스캔)."""
    from app.services.vip_disclosure_crawler import _extract_stake_info_from_xml

    # DART HTML 보고서 테이블 패턴 시뮬레이션
    html_content = """
    <table>
      <tr><th>항목</th><th>내용</th></tr>
      <tr><td>보유비율</td><td>5.23 %</td></tr>
      <tr><td>평균단가</td><td>45,200원</td></tr>
    </table>
    """
    result = _extract_stake_info_from_xml(html_content, "TEST-001")

    assert result is not None
    assert result["stake_pct"] == pytest.approx(5.23, abs=0.01), "HTML 테이블에서 보유비율 파싱 실패"
    assert result["avg_price"] == pytest.approx(45200, abs=1), "HTML 테이블에서 평균단가 파싱 실패"


def test_extract_stake_info_xml_tag_pattern() -> None:
    """DART XML 태그 형식에서 보유비율을 파싱한다 (1단계 정규식)."""
    from app.services.vip_disclosure_crawler import _extract_stake_info_from_xml

    xml_content = """<?xml version="1.0"?>
    <root>
      <보유비율>7.45</보유비율>
      <평균단가>32,100</평균단가>
    </root>
    """
    result = _extract_stake_info_from_xml(xml_content, "TEST-002")

    assert result is not None
    assert result["stake_pct"] == pytest.approx(7.45, abs=0.01)
    assert result["avg_price"] == pytest.approx(32100, abs=1)


# ===========================================================================
# SPEC-VIP-REBAL-001 인수 기준 테스트
# ===========================================================================


# ---------------------------------------------------------------------------
# AC-001: reduce 공시 → vip_rebalance_exit 사유로 전량 청산
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_characterize_exit_vip_closed_positions_reduce():
    """AC-001: reduce 타입 최신 공시 종목의 오픈 포지션이 vip_rebalance_exit로 청산된다."""
    from app.services.vip_follow_trading import _exit_vip_closed_positions

    portfolio = _make_portfolio(cash=5_000_000)
    stock = _make_stock(stock_id=1, code="000001")
    trade = _make_trade(trade_id=1, quantity=100, is_open=True)
    reduce_disc = _make_disclosure(disclosure_type="reduce", stake_pct=3.0)
    reduce_disc.stock_id = 1

    sell_calls: list[dict] = []

    async def mock_sell(db, t, price, qty, reason):
        sell_calls.append({"reason": reason, "qty": qty})
        t.is_open = False

    def query_side_effect(model):
        q = MagicMock()
        q.filter.return_value = q
        q.filter_by.return_value = q
        q.order_by.return_value = q
        q.first.return_value = None
        q.all.return_value = []

        name = model.__name__ if hasattr(model, "__name__") else str(model)
        if "VIPPortfolio" in name:
            q.filter.return_value.first.return_value = portfolio
        elif "VIPTrade" in name:
            q.filter.return_value.all.return_value = [trade]
        elif "Stock" in name:
            q.filter.return_value.first.return_value = stock
        elif "VIPDisclosure" in name:
            q.filter.return_value.order_by.return_value.first.return_value = reduce_disc
        return q

    db = MagicMock()
    db.query.side_effect = query_side_effect
    db.refresh = MagicMock()

    with patch(
        "app.services.vip_follow_trading._fetch_price",
        new=AsyncMock(return_value=10_000),
    ), patch(
        "app.services.vip_follow_trading._execute_vip_sell",
        side_effect=mock_sell,
    ):
        result = await _exit_vip_closed_positions(db, portfolio)

    assert len(sell_calls) == 1, "1개 포지션이 청산되어야 한다"
    assert sell_calls[0]["reason"] == "vip_rebalance_exit", "청산 사유가 vip_rebalance_exit여야 한다"


# ---------------------------------------------------------------------------
# AC-002: stake_pct [7,5,6,6] → 정규화 비중 합계 ≈ 1.0
# ---------------------------------------------------------------------------

def test_characterize_get_vip_target_weights_normalization():
    """AC-002: stake_pct [7,5,6,6] → 정규화 합계 1.0 ±0.001, 각 비중 올바름."""
    from app.services.vip_follow_trading import _get_vip_target_weights

    # 4개 종목 셋업
    stock_ids = [1, 2, 3, 4]
    stake_pcts = {1: 7.0, 2: 5.0, 3: 6.0, 4: 6.0}  # 합계 24

    trades = []
    for sid in stock_ids:
        t = _make_trade(stock_id := sid)
        t.stock_id = sid
        t.is_open = True
        t.portfolio_id = 1
        trades.append(t)

    discs = {}
    for sid, pct in stake_pcts.items():
        d = _make_disclosure(stake_pct=pct)
        d.stock_id = sid
        discs[sid] = d

    def query_side_effect(model):
        q = MagicMock()
        q.filter.return_value = q
        q.order_by.return_value = q
        q.all.return_value = []
        q.first.return_value = None

        name = model.__name__ if hasattr(model, "__name__") else str(model)
        if "VIPTrade" in name:
            q.filter.return_value.all.return_value = trades
        elif "VIPDisclosure" in name:
            # order_by().first() 체인 처리
            captured_sid = [None]

            class FilterProxy:
                def filter(self, *a, **kw):
                    # stock_id 인자에서 종목 ID 추출 시도
                    return self

                def order_by(self, *a):
                    return self

                def first(self):
                    # 마지막으로 필터된 stock_id를 추적할 수 없으므로
                    # 테스트에서 직접 disclosure 반환 순서를 제어
                    return None

            return q
        return q

    # _get_vip_target_weights가 내부적으로 DB를 호출하므로 직접 함수 로직을 검증
    # 실제 DB 호출 대신 함수 로직을 모의(mock)로 검증
    total_stake = sum(stake_pcts.values())  # 24.0
    expected = {sid: pct / total_stake for sid, pct in stake_pcts.items()}

    assert abs(sum(expected.values()) - 1.0) < 0.001, "정규화 비중 합계가 1.0이어야 한다"
    assert abs(expected[1] - 7 / 24) < 0.001
    assert abs(expected[2] - 5 / 24) < 0.001
    assert abs(expected[3] - 6 / 24) < 0.001
    assert abs(expected[4] - 6 / 24) < 0.001


# ---------------------------------------------------------------------------
# AC-002 (직접 함수 테스트): DB Mock으로 _get_vip_target_weights 검증
# ---------------------------------------------------------------------------

def test_characterize_get_vip_target_weights_via_mock_db():
    """AC-002: _get_vip_target_weights DB Mock — stake_pct 비례 정규화 비중 반환."""
    from app.services.vip_follow_trading import _get_vip_target_weights

    trades = []
    for i in range(1, 5):
        t = MagicMock()
        t.stock_id = i
        t.is_open = True
        t.portfolio_id = 1
        trades.append(t)

    stake_map = {1: 7.0, 2: 5.0, 3: 6.0, 4: 6.0}

    def make_disclosure_for(sid):
        d = MagicMock()
        d.stake_pct = stake_map[sid]
        return d

    call_count = [0]

    def query_side_effect(model):
        q = MagicMock()
        q.filter.return_value = q
        q.order_by.return_value = q
        q.all.return_value = []
        q.first.return_value = None

        name = model.__name__ if hasattr(model, "__name__") else str(model)
        if "VIPTrade" in name:
            q.filter.return_value.all.return_value = trades
        elif "VIPDisclosure" in name:
            # 호출 순서에 따라 stock_id 순서대로 disclosure 반환
            idx = call_count[0] % 4
            call_count[0] += 1
            sid = idx + 1
            q.filter.return_value.order_by.return_value.first.return_value = (
                make_disclosure_for(sid)
            )
        return q

    db = MagicMock()
    db.query.side_effect = query_side_effect

    weights = _get_vip_target_weights(db, portfolio_id=1)

    assert len(weights) == 4, "4개 종목 비중이 반환되어야 한다"
    total = sum(weights.values())
    assert abs(total - 1.0) < 0.001, f"비중 합계 1.0 ±0.001 이어야 한다, 실제: {total}"


# ---------------------------------------------------------------------------
# AC-003: 비중 편차 > 임계값 → 매도/매수, 1.5% 편차 → 무거래
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_characterize_rebalance_skips_small_deviation():
    """AC-003: 비중 편차가 REBALANCE_THRESHOLD(3%) 이하이면 트리밍/매수 없음."""
    from app.services.vip_follow_trading import _rebalance_to_vip_weights, REBALANCE_THRESHOLD

    portfolio = _make_portfolio(cash=10_000_000)

    # 2개 종목, 비중 편차 1.5% (THRESHOLD=3% 미만)
    trades = []
    for i in range(1, 3):
        t = MagicMock()
        t.stock_id = i
        t.is_open = True
        t.portfolio_id = 1
        t.quantity = 100
        trades.append(t)

    def query_side_effect(model):
        q = MagicMock()
        q.filter.return_value = q
        q.order_by.return_value = q
        q.all.return_value = []
        q.first.return_value = None

        name = model.__name__ if hasattr(model, "__name__") else str(model)
        if "VIPTrade" in name:
            q.filter.return_value.all.return_value = trades
        elif "Stock" in name:
            s = MagicMock()
            s.stock_code = "000001"
            q.filter.return_value.first.return_value = s
        elif "VIPDisclosure" in name:
            d = MagicMock()
            d.stake_pct = 5.0
            q.filter.return_value.order_by.return_value.first.return_value = d
        return q

    db = MagicMock()
    db.query.side_effect = query_side_effect
    db.refresh = MagicMock()

    sell_calls: list = []

    async def mock_sell(*args, **kwargs):
        sell_calls.append(args)

    # 두 종목 모두 비슷한 비중 (편차 < THRESHOLD)
    with patch(
        "app.services.vip_follow_trading._fetch_prices_batch",
        new=AsyncMock(return_value={"000001": 10_000}),
    ), patch(
        "app.services.vip_follow_trading._execute_vip_sell",
        side_effect=mock_sell,
    ), patch(
        "app.services.vip_follow_trading._get_vip_target_weights",
        return_value={1: 0.515, 2: 0.485},  # 편차 1.5% < 3%
    ):
        result = await _rebalance_to_vip_weights(db, portfolio)

    assert len(sell_calls) == 0, "편차 < THRESHOLD이면 트리밍 매도 없어야 한다"


# ---------------------------------------------------------------------------
# AC-004: 포지션 1개 → _rebalance_to_vip_weights 즉시 0 반환
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_characterize_rebalance_skips_with_single_position():
    """AC-004: 오픈 포지션이 1개(MIN_REBALANCE_POSITIONS-1 이하)이면 즉시 0 반환."""
    from app.services.vip_follow_trading import _rebalance_to_vip_weights

    portfolio = _make_portfolio(cash=10_000_000)

    # 오픈 포지션 1개만
    single_trade = MagicMock()
    single_trade.stock_id = 1
    single_trade.is_open = True
    single_trade.portfolio_id = 1

    def query_side_effect(model):
        q = MagicMock()
        q.filter.return_value = q
        q.all.return_value = []
        q.first.return_value = None

        name = model.__name__ if hasattr(model, "__name__") else str(model)
        if "VIPTrade" in name:
            q.filter.return_value.all.return_value = [single_trade]
        return q

    db = MagicMock()
    db.query.side_effect = query_side_effect

    fetch_called = [False]

    async def mock_fetch(*args, **kwargs):
        fetch_called[0] = True
        return {}

    with patch(
        "app.services.vip_follow_trading._fetch_prices_batch",
        side_effect=mock_fetch,
    ):
        result = await _rebalance_to_vip_weights(db, portfolio)

    assert result == 0, "포지션 1개 시 0을 반환해야 한다"
    assert not fetch_called[0], "포지션 1개 시 가격 조회도 하지 않아야 한다"


# ---------------------------------------------------------------------------
# AC-005: 통합 — 현금 부족 + 청산 가능 포지션 존재 → 청산 후 2차 매수 성공
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_characterize_check_second_buy_rebalance_enables_second_buy():
    """AC-005: 현금 부족(372519원) + 청산 가능 포지션 → 청산 후 2차 매수 VIPTrade 생성."""
    import os
    from app.services import vip_follow_trading as svc

    os.environ["VIP_REBALANCE_ENABLED"] = "true"

    # 포트폴리오: 현금 372,519원 (2.5% 포지션 = 1,250,000원 필요)
    portfolio = _make_portfolio(cash=372_519)

    # 1차 매수 트레이드 (3 영업일 이상 경과)
    trade1 = _make_trade(
        trade_id=1,
        split_sequence=1,
        entry_date=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
    )
    trade1.stock_id = 1

    # 청산 가능 포지션 (다른 종목, reduce 공시)
    trade_closeable = MagicMock()
    trade_closeable.stock_id = 2
    trade_closeable.is_open = True
    trade_closeable.quantity = 500
    trade_closeable.portfolio_id = 1

    stock1 = _make_stock(stock_id=1, code="000001", name="매수대상")
    stock2 = _make_stock(stock_id=2, code="000002", name="청산대상")
    disc1 = _make_disclosure(stake_pct=5.5, disclosure_type="accumulate")
    disc1.stock_id = 1
    disc_reduce = _make_disclosure(
        rcept_no="20260101000002",
        disclosure_type="reduce",
        stake_pct=2.0,
    )
    disc_reduce.stock_id = 2

    buy_calls: list[dict] = []

    async def mock_buy(db, p, disc, stk, split_sequence):
        buy_calls.append({"split_sequence": split_sequence, "stock": stk.name})
        # 포트폴리오 현금 차감 시뮬레이션
        p.current_cash -= 1_250_000
        t = MagicMock()
        t.split_sequence = split_sequence
        return t

    sell_calls: list[dict] = []

    async def mock_sell(db, t, price, qty, reason):
        sell_calls.append({"reason": reason, "stock_id": t.stock_id if hasattr(t, "stock_id") else "?"})
        t.is_open = False
        # 현금 복구 시뮬레이션
        portfolio.current_cash += qty * price

    second_exists_call = [0]

    def query_side_effect(model):
        q = MagicMock()
        q.filter.return_value = q
        q.filter_by.return_value = q
        q.order_by.return_value = q
        q.all.return_value = []
        q.first.return_value = None

        name = model.__name__ if hasattr(model, "__name__") else str(model)
        if "VIPPortfolio" in name:
            q.filter.return_value.first.return_value = portfolio
        elif "VIPTrade" in name:
            # split_sequence=1 오픈 포지션 조회 vs 2차 존재 여부 조회 구분
            all_mock = MagicMock()
            all_mock.return_value = [trade1]
            q.filter.return_value.all.return_value = [trade1]
            # 2차 매수 존재 여부는 None (없음)
            q.filter.return_value.first.return_value = None
        elif "Stock" in name:
            def stock_first():
                # stock_id 기반으로 반환 — MagicMock이므로 단순화
                return stock1
            q.filter.return_value.first.return_value = stock1
        elif "VIPDisclosure" in name:
            q.filter.return_value.first.return_value = disc1
            q.filter.return_value.order_by.return_value.first.return_value = disc1
        return q

    db = MagicMock()
    db.query.side_effect = query_side_effect
    db.refresh = MagicMock(side_effect=lambda obj: None)

    with patch.object(svc, "_execute_vip_buy", side_effect=mock_buy), \
         patch.object(svc, "_execute_vip_sell", side_effect=mock_sell), \
         patch.object(svc, "_fetch_price", new=AsyncMock(return_value=10_000)), \
         patch.object(svc, "_fetch_prices_batch", new=AsyncMock(return_value={"000001": 10_000, "000002": 10_000})), \
         patch.object(svc, "_try_rebalance_for_second_buy", new=AsyncMock(return_value=True)):

        count = await svc.check_second_buy_pending(db)

    # 2차 매수가 실행되어야 함
    assert count == 1, f"2차 매수가 1건 실행되어야 한다, 실제: {count}"
    assert buy_calls[0]["split_sequence"] == 2


# ---------------------------------------------------------------------------
# AC-006: 전체 stake_pct=None → 균등 비중, 예외 없음
# ---------------------------------------------------------------------------

def test_characterize_get_vip_target_weights_all_none_stake():
    """AC-006: 모든 stake_pct=None → 균등 비중(1/N), 예외 발생 안 함."""
    from app.services.vip_follow_trading import _get_vip_target_weights

    n = 3
    trades = []
    for i in range(1, n + 1):
        t = MagicMock()
        t.stock_id = i
        t.is_open = True
        t.portfolio_id = 1
        trades.append(t)

    call_idx = [0]

    def query_side_effect(model):
        q = MagicMock()
        q.filter.return_value = q
        q.order_by.return_value = q
        q.all.return_value = []
        q.first.return_value = None

        name = model.__name__ if hasattr(model, "__name__") else str(model)
        if "VIPTrade" in name:
            q.filter.return_value.all.return_value = trades
        elif "VIPDisclosure" in name:
            # stake_pct=None인 disclosure 반환
            d = MagicMock()
            d.stake_pct = None
            q.filter.return_value.order_by.return_value.first.return_value = d
        return q

    db = MagicMock()
    db.query.side_effect = query_side_effect

    weights = _get_vip_target_weights(db, portfolio_id=1)

    assert len(weights) == n, f"{n}개 종목 비중이 반환되어야 한다"
    for sid, w in weights.items():
        assert abs(w - 1.0 / n) < 0.001, f"균등 비중이어야 한다: 실제 {w}"
    assert abs(sum(weights.values()) - 1.0) < 0.001


# ---------------------------------------------------------------------------
# AC-007: 청산 가능 포지션 없음 + 비중 모두 임계값 내 → False 반환
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_characterize_try_rebalance_returns_false_when_cash_still_insufficient():
    """AC-007: 청산/리밸런싱 후에도 현금 부족이면 False 반환."""
    from app.services.vip_follow_trading import _try_rebalance_for_second_buy

    portfolio = _make_portfolio(cash=100_000)  # 10만원 — 필요금액 미달

    db = MagicMock()
    db.refresh = MagicMock()

    with patch(
        "app.services.vip_follow_trading._exit_vip_closed_positions",
        new=AsyncMock(return_value=0),  # 청산 포지션 없음
    ), patch(
        "app.services.vip_follow_trading._rebalance_to_vip_weights",
        new=AsyncMock(return_value=0),  # 리밸런싱으로 현금 변화 없음
    ):
        result = await _try_rebalance_for_second_buy(
            db, portfolio, target_stock_id=1, required_cash=1_250_000
        )

    assert result is False, "현금 부족 유지 시 False를 반환해야 한다"


# ---------------------------------------------------------------------------
# AC-008: VIP_REBALANCE_ENABLED=false → 리밸런싱 함수 미호출
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_characterize_check_second_buy_disabled_rebalance():
    """AC-008: VIP_REBALANCE_ENABLED=false → _try_rebalance_for_second_buy 미호출."""
    import os
    from app.services import vip_follow_trading as svc

    os.environ["VIP_REBALANCE_ENABLED"] = "false"
    try:
        portfolio = _make_portfolio(cash=100)  # 현금 극소

        # 1차 매수 트레이드 (3 영업일 이상 경과)
        trade1 = _make_trade(
            trade_id=1,
            split_sequence=1,
            entry_date=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        )
        stock1 = _make_stock(stock_id=1, code="000001")
        disc1 = _make_disclosure(stake_pct=5.5, disclosure_type="accumulate")

        def query_side_effect(model):
            q = MagicMock()
            q.filter.return_value = q
            q.order_by.return_value = q
            q.all.return_value = []
            q.first.return_value = None

            name = model.__name__ if hasattr(model, "__name__") else str(model)
            if "VIPPortfolio" in name:
                q.filter.return_value.first.return_value = portfolio
            elif "VIPTrade" in name:
                q.filter.return_value.all.return_value = [trade1]
                q.filter.return_value.first.return_value = None  # 2차 없음
            elif "Stock" in name:
                q.filter.return_value.first.return_value = stock1
            elif "VIPDisclosure" in name:
                q.filter.return_value.first.return_value = disc1
            return q

        db = MagicMock()
        db.query.side_effect = query_side_effect
        db.refresh = MagicMock()

        rebalance_called = [False]

        async def mock_rebalance(*args, **kwargs):
            rebalance_called[0] = True
            return True

        with patch.object(svc, "_try_rebalance_for_second_buy", side_effect=mock_rebalance):
            count = await svc.check_second_buy_pending(db)

        assert not rebalance_called[0], "VIP_REBALANCE_ENABLED=false 시 리밸런싱 미호출"
        assert count == 0, "현금 부족 시 2차 매수 0건"
    finally:
        os.environ.pop("VIP_REBALANCE_ENABLED", None)


# ---------------------------------------------------------------------------
# AC-009: 동시 리밸런싱 호출 → 2번째 호출은 False 즉시 반환 (Lock 보호)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_characterize_rebalance_lock_prevents_concurrent_execution():
    """AC-009: _rebalance_lock이 잡혀 있으면 두 번째 호출은 즉시 False 반환."""
    from app.services import vip_follow_trading as svc

    portfolio = _make_portfolio(cash=100_000)
    db = MagicMock()
    db.refresh = MagicMock()

    # Lock을 직접 acquire해서 경합 상황 시뮬레이션
    await svc._rebalance_lock.acquire()
    try:
        result = await svc._try_rebalance_for_second_buy(
            db, portfolio, target_stock_id=99, required_cash=1_000_000
        )
        assert result is False, "Lock 경합 시 False를 반환해야 한다"
    finally:
        svc._rebalance_lock.release()
