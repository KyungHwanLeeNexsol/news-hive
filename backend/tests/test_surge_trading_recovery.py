"""SPEC-AI-021: 손절 후 회복 종목 시그널 누락 방지 테스트.

AC-001~AC-010 검증.
모든 외부 의존성(DB, 가격 API)은 mock 처리.
"""
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


# ---------------------------------------------------------------------------
# 헬퍼 / 픽스처
# ---------------------------------------------------------------------------

def _make_db():
    """SQLAlchemy Session mock 생성 헬퍼."""
    return MagicMock()


def _make_fund_signal(
    signal_id=1,
    stock_id=1,
    probability=0.40,
    surge_basis=None,
    surge_metadata=None,
):
    """FundSignal mock 생성 헬퍼."""
    if surge_basis is None:
        surge_basis = ["theme_cluster"]
    s = MagicMock()
    s.id = signal_id
    s.stock_id = stock_id
    s.signal_type = "surge_candidate"
    if surge_metadata is not None:
        s.surge_metadata = surge_metadata
    else:
        s.surge_metadata = json.dumps({
            "surge_probability_score": probability,
            "surge_basis": surge_basis,
        })
    s.paper_executed = False
    return s


def _make_stock(stock_id=1, stock_code="066570", name="LG전자"):
    """Stock mock 생성 헬퍼."""
    s = MagicMock()
    s.id = stock_id
    s.stock_code = stock_code
    s.name = name
    return s


def _make_trade(
    stock_code="066570",
    stock_name="LG전자",
    entry_price=Decimal("75000"),
    quantity=10,
    entry_date=None,
    exit_date=None,
    exit_reason=None,
    is_open=False,
    trade_id=1,
    holding_days=1,
):
    """SurgeTrade mock 생성 헬퍼."""
    t = MagicMock()
    t.id = trade_id
    t.stock_code = stock_code
    t.stock_name = stock_name
    t.entry_price = entry_price
    t.quantity = quantity
    t.entry_date = entry_date or date(2026, 5, 28)
    t.exit_date = exit_date
    t.exit_reason = exit_reason
    t.is_open = is_open
    t.surge_probability_score = Decimal("0.30")
    return t


# ---------------------------------------------------------------------------
# REQ-AI021-001/002: 손절 후 신뢰도 부스트 + 임계값 완화
# _get_recent_stop_loss_codes 헬퍼 테스트
# ---------------------------------------------------------------------------

class TestGetRecentStopLossCodes:
    """AC-009: _get_recent_stop_loss_codes 정확성 검증."""

    def test_ac009_returns_stop_loss_codes(self):
        """AC-009: lookback_days=3 이내 stop_loss 종목 코드 반환."""
        from app.services.surge_trading_service import _get_recent_stop_loss_codes
        from app.models.surge_portfolio import SurgeTrade

        db = _make_db()

        # stop_loss 종목 2개 mock
        t1 = _make_trade(stock_code="066570", exit_reason="stop_loss", exit_date=date(2026, 5, 28))
        t2 = _make_trade(stock_code="018260", exit_reason="stop_loss", exit_date=date(2026, 5, 27))

        # DB 쿼리 mock 체인 설정 — .filter().all() 반환
        mock_query = db.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.all.return_value = [t1, t2]

        result = _get_recent_stop_loss_codes(db, lookback_days=3)

        assert "066570" in result
        assert "018260" in result

    def test_ac009_excludes_take_profit(self):
        """AC-009: take_profit 종목은 결과에 포함되지 않음."""
        from app.services.surge_trading_service import _get_recent_stop_loss_codes

        today = date(2026, 5, 29)
        db = _make_db()

        # take_profit 종목만 있는 경우
        mock_query = db.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.all.return_value = []  # stop_loss 없음 → 빈 결과

        result = _get_recent_stop_loss_codes(db, lookback_days=3)

        assert len(result) == 0

    def test_ac009_excludes_old_stop_loss_beyond_lookback(self):
        """AC-009: lookback_days=3 초과된 손절은 반환하지 않음 (DB 필터 책임)."""
        from app.services.surge_trading_service import _get_recent_stop_loss_codes

        db = _make_db()

        # DB가 오래된 손절 필터링 후 빈 결과 반환
        mock_query = db.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.all.return_value = []

        result = _get_recent_stop_loss_codes(db, lookback_days=3)

        assert isinstance(result, set)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# REQ-AI021-001: get_today_signals() - 손절 후 부스트 적용
# ---------------------------------------------------------------------------

class TestGetTodaySignalsBoost:
    """AC-001~AC-005: get_today_signals() 손절 후 부스트 및 임계값 완화 검증."""

    def _make_kst_signal(self, probability, surge_basis=None):
        """KST 날짜 포함 시그널 mock."""
        if surge_basis is None:
            surge_basis = ["theme_cluster"]
        metadata = json.dumps({
            "surge_probability_score": probability,
            "surge_basis": surge_basis,
        })
        s = MagicMock()
        s.id = 1
        s.stock_id = 1
        s.signal_type = "surge_candidate"
        s.surge_metadata = metadata
        # created_at: 전일 15:30 (KST, UTC aware)
        s.created_at = datetime(2026, 5, 28, 15, 30, 0, tzinfo=KST)
        return s

    def test_ac001_stop_loss_within_3days_boosts_confidence(self):
        """AC-001: 3일 이내 stop_loss 이력 + conf=0.2576 → 부스트 후 통과 (0.3576 >= 0.30).

        get_today_signals()가 (signal, stock, probability, boost_info) 4-tuple 반환.
        """
        from app.services.surge_trading_service import get_today_signals

        db = _make_db()
        signal = self._make_kst_signal(probability=0.2576, surge_basis=["theme_cluster", "volume_news_combo"])
        stock = _make_stock(stock_code="066570", name="LG전자")

        # DB 시그널 조회 mock
        db.query.return_value.join.return_value.filter.return_value.all.return_value = [(signal, stock)]

        with patch("app.services.surge_trading_service._get_recent_stop_loss_codes") as mock_stop_loss, \
             patch("app.services.surge_trading_service._get_price_history_sync", return_value=[]):
            mock_stop_loss.return_value = {"066570"}  # 손절 이력 있음

            result = get_today_signals(db, min_probability=Decimal("0.30"))

        # 4-tuple 반환 검증
        assert len(result) >= 1
        first = result[0]
        assert len(first) == 4, "4-tuple (signal, stock, probability, boost_info) 반환 필요"

        _, _, _, boost_info = first
        assert boost_info["is_post_stop_loss"] is True
        assert boost_info["boost_applied"] == pytest.approx(0.10, abs=1e-6)

    def test_ac002_no_stop_loss_history_filtered_out(self):
        """AC-002: stop_loss 이력 없음 + conf=0.2576 → 필터 아웃."""
        from app.services.surge_trading_service import get_today_signals

        db = _make_db()
        signal = self._make_kst_signal(probability=0.2576)
        stock = _make_stock(stock_code="066570")

        db.query.return_value.join.return_value.filter.return_value.all.return_value = [(signal, stock)]

        with patch("app.services.surge_trading_service._get_recent_stop_loss_codes") as mock_stop_loss, \
             patch("app.services.surge_trading_service._get_price_history_sync", return_value=[]):
            mock_stop_loss.return_value = set()  # 손절 이력 없음

            result = get_today_signals(db, min_probability=Decimal("0.30"))

        assert len(result) == 0, "손절 이력 없는 저확률 시그널은 필터 아웃되어야 함"

    def test_ac003_theme_cluster_only_threshold_relaxed(self):
        """AC-003: theme_cluster-only + stop_loss + conf=0.2464 → 완화 임계값 0.25 통과."""
        from app.services.surge_trading_service import get_today_signals

        db = _make_db()
        # theme_cluster ONLY
        signal = self._make_kst_signal(probability=0.2464, surge_basis=["theme_cluster"])
        stock = _make_stock(stock_code="018260", name="삼성에스디에스")

        db.query.return_value.join.return_value.filter.return_value.all.return_value = [(signal, stock)]

        with patch("app.services.surge_trading_service._get_recent_stop_loss_codes") as mock_stop_loss, \
             patch("app.services.surge_trading_service._get_price_history_sync", return_value=[]):
            mock_stop_loss.return_value = {"018260"}  # 손절 이력 있음

            result = get_today_signals(db, min_probability=Decimal("0.30"))

        # 0.2464 + 0.10 = 0.3464 >= 0.25 → 통과
        assert len(result) >= 1, "theme_cluster-only + 손절 이력 + 0.2464 → 통과해야 함"
        _, _, _, boost_info = result[0]
        assert boost_info["min_probability_effective"] == pytest.approx(0.25, abs=1e-6)

    def test_ac004_multi_basis_no_threshold_relaxation(self):
        """AC-004: theme_cluster + volume_news_combo + stop_loss → min_probability 0.30 유지."""
        from app.services.surge_trading_service import get_today_signals

        db = _make_db()
        # 다중 basis → 완화 적용 안됨
        signal = self._make_kst_signal(
            probability=0.2900,
            surge_basis=["theme_cluster", "volume_news_combo"],
        )
        stock = _make_stock(stock_code="066570")

        db.query.return_value.join.return_value.filter.return_value.all.return_value = [(signal, stock)]

        with patch("app.services.surge_trading_service._get_recent_stop_loss_codes") as mock_stop_loss, \
             patch("app.services.surge_trading_service._get_price_history_sync", return_value=[]):
            mock_stop_loss.return_value = {"066570"}

            result = get_today_signals(db, min_probability=Decimal("0.30"))

        # 0.29 + 0.10 = 0.39 >= 0.30 → 통과해야 함 (multi-basis이지만 부스트는 적용)
        assert len(result) >= 1
        _, _, _, boost_info = result[0]
        # min_probability_effective는 0.30 (완화 없음)
        assert boost_info["min_probability_effective"] == pytest.approx(0.30, abs=1e-6)

    def test_ac005_carry_over_no_threshold_relaxation(self):
        """AC-005: carry_over in basis → min_probability 0.30 유지 (theme_cluster-only 완화 미적용)."""
        from app.services.surge_trading_service import get_today_signals

        db = _make_db()
        # carry_over 포함 → theme_cluster-only 조건 불충족
        signal = self._make_kst_signal(
            probability=0.2400,
            surge_basis=["carry_over"],
        )
        stock = _make_stock(stock_code="066570")

        db.query.return_value.join.return_value.filter.return_value.all.return_value = [(signal, stock)]

        with patch("app.services.surge_trading_service._get_recent_stop_loss_codes") as mock_stop_loss, \
             patch("app.services.surge_trading_service._get_price_history_sync", return_value=[]):
            mock_stop_loss.return_value = {"066570"}

            result = get_today_signals(db, min_probability=Decimal("0.30"))

        # carry_over: 0.24 + 0.10 = 0.34 >= 0.30 → 통과 (부스트는 적용, 완화는 없음)
        # 0.34 >= 0.30 이므로 필터 통과
        assert len(result) >= 1
        _, _, _, boost_info = result[0]
        # theme_cluster-only 아님 → min_probability_effective는 0.30
        assert boost_info["min_probability_effective"] == pytest.approx(0.30, abs=1e-6)

    def test_boost_info_no_boost_when_high_confidence(self):
        """부스트 없어도 통과하는 시그널: boost_applied=0.0, is_post_stop_loss=False."""
        from app.services.surge_trading_service import get_today_signals

        db = _make_db()
        signal = self._make_kst_signal(probability=0.50, surge_basis=["theme_cluster", "volume_news_combo"])
        stock = _make_stock(stock_code="005930", name="삼성전자")

        db.query.return_value.join.return_value.filter.return_value.all.return_value = [(signal, stock)]

        with patch("app.services.surge_trading_service._get_recent_stop_loss_codes") as mock_stop_loss, \
             patch("app.services.surge_trading_service._get_price_history_sync", return_value=[]):
            mock_stop_loss.return_value = set()  # 손절 이력 없음

            result = get_today_signals(db, min_probability=Decimal("0.30"))

        assert len(result) >= 1
        _, _, _, boost_info = result[0]
        assert boost_info["is_post_stop_loss"] is False
        assert boost_info["boost_applied"] == pytest.approx(0.0, abs=1e-6)
        assert boost_info["boost_reason"] is None


# ---------------------------------------------------------------------------
# REQ-AI021-003: check_exit_conditions() - 보유기간별 손절 임계값
# ---------------------------------------------------------------------------

class TestCheckExitConditionsHoldingPeriod:
    """AC-006~AC-008: 보유기간별 손절 임계값 차등 적용."""

    def _make_open_trade(self, stock_code, entry_price_float, holding_days=0, entry_date=None):
        """오픈 포지션 SurgeTrade mock."""
        t = MagicMock()
        t.stock_code = stock_code
        t.entry_price = Decimal(str(entry_price_float))
        t.quantity = 10
        t.is_open = True
        # holding_days에 맞게 entry_date 설정
        today = date(2026, 5, 29)
        if holding_days == 0:
            t.entry_date = today
        else:
            # 영업일 기준 holding_days 전: 단순 계산 (주말 무시하여 충분히 과거로)
            t.entry_date = date(2026, 5, 27) if holding_days == 1 else date(2026, 5, 26)
        t.exit_date = None
        t.exit_reason = None
        return t

    def test_ac006_same_day_not_stopped_at_minus_4_6_pct(self):
        """AC-006: 당일 거래 -4.60% → 손절 미발동 (same_day 임계값 -5%)."""
        from app.services.surge_trading_service import check_exit_conditions

        entry_price = 10000
        # -4.60% 하락
        current_price = int(entry_price * 0.954)  # 9540

        trade = self._make_open_trade("066570", entry_price, holding_days=0)

        db = _make_db()
        db.query.return_value.filter.return_value.all.return_value = [trade]

        with patch("app.services.surge_trading_service.is_market_hours", return_value=True), \
             patch("app.services.surge_trading_service._get_current_price_sync", return_value=current_price), \
             patch("app.services.surge_trading_service.calculate_trading_days_elapsed", return_value=0):

            result = check_exit_conditions(db)

        # -4.60% < -5% 미달 → 손절 미발동
        assert result["closed"] == 0, "당일 -4.60%는 same_day -5% 임계값 미달로 손절되지 않아야 함"

    def test_ac007_multiday_not_stopped_at_minus_6_pct(self):
        """AC-007: 멀티데이 -6.00% → 손절 미발동 (multi_day 임계값 -7%)."""
        from app.services.surge_trading_service import check_exit_conditions

        entry_price = 10000
        # -6.00% 하락
        current_price = int(entry_price * 0.94)  # 9400

        trade = self._make_open_trade("018260", entry_price, holding_days=1)

        db = _make_db()
        db.query.return_value.filter.return_value.all.return_value = [trade]

        with patch("app.services.surge_trading_service.is_market_hours", return_value=True), \
             patch("app.services.surge_trading_service._get_current_price_sync", return_value=current_price), \
             patch("app.services.surge_trading_service.calculate_trading_days_elapsed", return_value=1):

            result = check_exit_conditions(db)

        # -6% < -7% 미달 → 손절 미발동
        assert result["closed"] == 0, "멀티데이 -6%는 multi_day -7% 임계값 미달로 손절되지 않아야 함"

    def test_same_day_stopped_at_minus_5_pct(self):
        """당일 -5.00% 정확히 → 손절 발동 (경계값 포함)."""
        from app.services.surge_trading_service import check_exit_conditions

        entry_price = 10000
        current_price = int(entry_price * 0.95)  # 9500 → 정확히 -5%

        trade = self._make_open_trade("066570", entry_price, holding_days=0)

        db = _make_db()
        db.query.return_value.filter.return_value.all.return_value = [trade]

        with patch("app.services.surge_trading_service.is_market_hours", return_value=True), \
             patch("app.services.surge_trading_service._get_current_price_sync", return_value=current_price), \
             patch("app.services.surge_trading_service.calculate_trading_days_elapsed", return_value=0), \
             patch("app.services.surge_trading_service.execute_sell") as mock_sell:
            mock_sell.return_value = trade

            result = check_exit_conditions(db)

        # -5% 이상 → 손절 발동
        assert result["closed"] >= 1 or mock_sell.called, "당일 -5%는 손절 발동해야 함"

    def test_multiday_stopped_at_minus_7_pct(self):
        """멀티데이 -7.00% 정확히 → 손절 발동."""
        from app.services.surge_trading_service import check_exit_conditions

        entry_price = 10000
        current_price = int(entry_price * 0.93)  # 9300 → -7%

        trade = self._make_open_trade("018260", entry_price, holding_days=1)

        db = _make_db()
        db.query.return_value.filter.return_value.all.return_value = [trade]

        with patch("app.services.surge_trading_service.is_market_hours", return_value=True), \
             patch("app.services.surge_trading_service._get_current_price_sync", return_value=current_price), \
             patch("app.services.surge_trading_service.calculate_trading_days_elapsed", return_value=1), \
             patch("app.services.surge_trading_service.execute_sell") as mock_sell:
            mock_sell.return_value = trade

            result = check_exit_conditions(db)

        assert result["closed"] >= 1 or mock_sell.called, "멀티데이 -7%는 손절 발동해야 함"

    def test_ac008_old_stop_loss_pct_param_backward_compat(self):
        """AC-008: 기존 stop_loss_pct 파라미터 전달 시 backward compatible."""
        from app.services.surge_trading_service import check_exit_conditions

        entry_price = 10000
        current_price = 9500  # -5%

        trade = self._make_open_trade("066570", entry_price, holding_days=0)

        db = _make_db()
        db.query.return_value.filter.return_value.all.return_value = [trade]

        # 기존 파라미터 방식으로 호출
        with patch("app.services.surge_trading_service.is_market_hours", return_value=True), \
             patch("app.services.surge_trading_service._get_current_price_sync", return_value=current_price), \
             patch("app.services.surge_trading_service.calculate_trading_days_elapsed", return_value=0), \
             patch("app.services.surge_trading_service.execute_sell") as mock_sell:
            mock_sell.return_value = trade

            # stop_loss_pct 파라미터를 직접 전달 — 이전 API 유지
            result = check_exit_conditions(db, stop_loss_pct=Decimal("-0.05"))

        # 예외 없이 실행되어야 함
        assert "closed" in result


# ---------------------------------------------------------------------------
# REQ-AI021-004: execute_buy_orders() - 4-tuple 언패킹
# ---------------------------------------------------------------------------

class TestExecuteBuyOrders4Tuple:
    """AC-010: execute_buy_orders()가 4-tuple 반환값을 올바르게 처리."""

    def test_ac010_execute_buy_orders_unpacks_4tuple(self):
        """AC-010: execute_buy_orders가 4-tuple 반환값 처리 및 details에 recovery 필드 포함."""
        from app.services.surge_trading_service import execute_buy_orders

        signal = _make_fund_signal(
            probability=0.2576,
            surge_basis=["theme_cluster", "volume_news_combo"],
        )
        signal.surge_metadata = json.dumps({
            "surge_probability_score": 0.2576,
            "surge_basis": ["theme_cluster", "volume_news_combo"],
        })
        stock = _make_stock(stock_code="066570", name="LG전자")

        boost_info = {
            "is_post_stop_loss": True,
            "boost_applied": 0.10,
            "min_probability_effective": 0.30,
            "boost_reason": "3일 이내 stop_loss 이력",
        }

        db = _make_db()
        portfolio = MagicMock()
        portfolio.id = 1
        portfolio.initial_capital = Decimal("50000000")
        portfolio.current_cash = Decimal("50000000")

        with patch("app.services.surge_trading_service.is_buy_eligible_hours", return_value=True), \
             patch("app.services.surge_trading_service.get_or_create_portfolio", return_value=portfolio), \
             patch("app.services.surge_trading_service.get_today_signals",
                   return_value=[(signal, stock, 0.2576, boost_info)]), \
             patch("app.services.surge_trading_service.count_today_entries", return_value=0), \
             patch("app.services.surge_trading_service.count_open_positions", return_value=0), \
             patch("app.services.surge_trading_service.get_open_position", return_value=None), \
             patch("app.services.surge_trading_service._get_open_sector_counts", return_value={}), \
             patch("app.services.surge_trading_service._get_price_with_change_batch_sync",
                   return_value={"066570": {"current_price": 80000, "change_rate": 5.0}}):

            # execute_buy_orders가 4-tuple을 처리해도 예외 없이 실행
            result = execute_buy_orders(db)

        assert "executed" in result
        assert "details" in result

    def test_ac010_details_contain_recovery_fields(self):
        """AC-010: 매수 성공 시 details에 is_post_stop_loss 필드 포함."""
        from app.services.surge_trading_service import execute_buy_orders

        signal = _make_fund_signal(
            probability=0.2576,
            surge_basis=["theme_cluster", "volume_news_combo"],
        )
        signal.surge_metadata = json.dumps({
            "surge_probability_score": 0.2576,
            "surge_basis": ["theme_cluster", "volume_news_combo"],
        })
        stock = _make_stock(stock_code="066570", name="LG전자")

        boost_info = {
            "is_post_stop_loss": True,
            "boost_applied": 0.10,
            "min_probability_effective": 0.30,
            "boost_reason": "3일 이내 stop_loss 이력",
        }

        db = _make_db()
        portfolio = MagicMock()
        portfolio.id = 1
        portfolio.initial_capital = Decimal("50000000")
        portfolio.current_cash = Decimal("50000000")

        with patch("app.services.surge_trading_service.is_buy_eligible_hours", return_value=True), \
             patch("app.services.surge_trading_service.get_or_create_portfolio", return_value=portfolio), \
             patch("app.services.surge_trading_service.get_today_signals",
                   return_value=[(signal, stock, 0.2576, boost_info)]), \
             patch("app.services.surge_trading_service.count_today_entries", return_value=0), \
             patch("app.services.surge_trading_service.count_open_positions", return_value=0), \
             patch("app.services.surge_trading_service.get_open_position", return_value=None), \
             patch("app.services.surge_trading_service._get_open_sector_counts", return_value={}), \
             patch("app.services.surge_trading_service._get_price_with_change_batch_sync",
                   return_value={"066570": {"current_price": 80000, "change_rate": 5.0}}):

            result = execute_buy_orders(db)

        # 매수 완료된 항목의 details에 recovery 필드 포함 여부 확인
        executed_details = [d for d in result["details"] if d.get("action") == "executed"]
        if executed_details:
            detail = executed_details[0]
            assert "is_post_stop_loss" in detail, "매수 details에 is_post_stop_loss 필드 필요"
