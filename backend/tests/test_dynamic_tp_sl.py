# SPEC-AI-005 테스트: 동적 목표가/손절가 계산
"""ATR 기반 동적 TP/SL 시스템 테스트.

테스트 범위:
- calculate_atr(): ATR 계산 (Wilder's smoothing)
- calculate_dynamic_tp_sl(): 동적 TP/SL 계산 (ATR/섹터 기본값)
- get_sector_defaults(): 섹터별 기본 비율
- calculate_trailing_stop(): 트레일링 스탑 계산
- should_activate_trailing_stop(): 트레일링 스탑 활성화 조건
- paper_trading: 기존 TP/SL 동작 특성화
- 마이그레이션: ai_provided 보호
"""

import pytest
from unittest.mock import AsyncMock, patch


# ---------------------------------------------------------------------------
# TASK-001: calculate_atr() 테스트
# ---------------------------------------------------------------------------

class TestCalculateATR:
    """ATR (Average True Range) 계산 테스트."""

    def test_atr_returns_none_when_insufficient_data(self):
        """데이터 부족 시 None 반환 (period+1 미만)."""
        from app.services.technical_indicators import calculate_atr

        # period=14 → 15개 미만이면 None
        prices = [{"high": 100, "low": 90, "close": 95}] * 14
        result = calculate_atr(prices, period=14)
        assert result is None

    def test_atr_returns_none_for_empty_list(self):
        """빈 리스트에서 None 반환."""
        from app.services.technical_indicators import calculate_atr

        result = calculate_atr([], period=14)
        assert result is None

    def test_atr_returns_float_with_sufficient_data(self):
        """충분한 데이터(period+1 이상)로 float 반환."""
        from app.services.technical_indicators import calculate_atr

        # 15개 데이터 (period=14 → 최소 15개 필요)
        prices = []
        for i in range(15):
            prices.append({"high": 100 + i, "low": 90 + i, "close": 95 + i})
        result = calculate_atr(prices, period=14)
        assert result is not None
        assert isinstance(result, float)
        assert result > 0

    def test_atr_true_range_calculation(self):
        """True Range 계산: max(H-L, |H-prev_close|, |L-prev_close|)."""
        from app.services.technical_indicators import calculate_atr

        # 최신 → 과거 순으로 데이터 구성
        # prices[0]이 최신, prices[-1]이 가장 오래된 데이터
        # ATR 계산에는 prices를 역순으로 사용 (과거 → 최신)
        prices = []
        # 간단한 케이스: H-L=10, 갭 없음 → TR=10
        for i in range(20):
            prices.append({"high": 110, "low": 100, "close": 105})
        result = calculate_atr(prices, period=14)
        assert result is not None
        # H-L=10, |H-prev_close|=5, |L-prev_close|=5 → TR=10
        assert abs(result - 10.0) < 1.0

    def test_atr_wilder_smoothing_period_5(self):
        """기간 5로 ATR 계산 검증."""
        from app.services.technical_indicators import calculate_atr

        # 6개 이상 데이터로 period=5 ATR 계산 가능
        prices = [{"high": 110, "low": 90, "close": 100}] * 10
        result = calculate_atr(prices, period=5)
        assert result is not None
        assert result > 0

    def test_atr_default_period_14(self):
        """기본 period=14 사용."""
        from app.services.technical_indicators import calculate_atr

        prices = [{"high": 110, "low": 90, "close": 100}] * 20
        result_default = calculate_atr(prices)
        result_14 = calculate_atr(prices, period=14)
        assert result_default == result_14

    def test_atr_with_gap_up(self):
        """갭 상승 시 True Range가 H-L보다 큰 케이스."""
        from app.services.technical_indicators import calculate_atr

        # 가장 최신 데이터가 [0], 과거 데이터가 마지막
        # 갭 상승: 이전 종가 100, 오늘 시가 120, 고가 125, 저가 118
        prices = []
        # 먼저 과거 안정 데이터
        for _ in range(14):
            prices.append({"high": 102, "low": 98, "close": 100})
        # 갭 업 데이터 (최신에 추가) - 실제로는 앞에 놓임
        prices.insert(0, {"high": 125, "low": 118, "close": 122})

        result = calculate_atr(prices, period=14)
        assert result is not None
        assert result > 4  # H-L=7보다는 크거나 같아야 함 (갭 포함)


# ---------------------------------------------------------------------------
# TASK-002: dynamic_tp_sl 서비스 테스트
# ---------------------------------------------------------------------------

class TestGetSectorDefaults:
    """섹터 기본값 반환 테스트."""

    def test_sector_defaults_bio_pharma(self, db):
        """바이오/제약 섹터 기본값: +15%/-8%."""
        from app.services.dynamic_tp_sl import get_sector_defaults
        from app.models.sector import Sector

        sector = Sector(name="바이오제약", is_custom=False)
        db.add(sector)
        db.flush()

        result = get_sector_defaults(sector.id, db)
        assert result["target_pct"] == pytest.approx(0.15)
        assert result["stop_pct"] == pytest.approx(0.08)

    def test_sector_defaults_it_semiconductor(self, db):
        """IT/반도체 섹터 기본값: +12%/-6%."""
        from app.services.dynamic_tp_sl import get_sector_defaults
        from app.models.sector import Sector

        sector = Sector(name="반도체", is_custom=False)
        db.add(sector)
        db.flush()

        result = get_sector_defaults(sector.id, db)
        assert result["target_pct"] == pytest.approx(0.12)
        assert result["stop_pct"] == pytest.approx(0.06)

    def test_sector_defaults_banking_insurance(self, db):
        """은행/보험 섹터 기본값: +6%/-3%."""
        from app.services.dynamic_tp_sl import get_sector_defaults
        from app.models.sector import Sector

        sector = Sector(name="은행", is_custom=False)
        db.add(sector)
        db.flush()

        result = get_sector_defaults(sector.id, db)
        assert result["target_pct"] == pytest.approx(0.06)
        assert result["stop_pct"] == pytest.approx(0.03)

    def test_sector_defaults_none_sector(self, db):
        """섹터 없을 때 기본값: +10%/-5%."""
        from app.services.dynamic_tp_sl import get_sector_defaults

        result = get_sector_defaults(None, db)
        assert result["target_pct"] == pytest.approx(0.10)
        assert result["stop_pct"] == pytest.approx(0.05)

    def test_sector_defaults_unknown_sector(self, db):
        """알 수 없는 섹터 기본값: +10%/-5%."""
        from app.services.dynamic_tp_sl import get_sector_defaults
        from app.models.sector import Sector

        sector = Sector(name="알수없는섹터ABC", is_custom=False)
        db.add(sector)
        db.flush()

        result = get_sector_defaults(sector.id, db)
        assert result["target_pct"] == pytest.approx(0.10)
        assert result["stop_pct"] == pytest.approx(0.05)

    def test_sector_defaults_nonexistent_id(self, db):
        """존재하지 않는 섹터 ID → 기본값."""
        from app.services.dynamic_tp_sl import get_sector_defaults

        result = get_sector_defaults(99999, db)
        assert result["target_pct"] == pytest.approx(0.10)
        assert result["stop_pct"] == pytest.approx(0.05)


class TestCalculateTrailingStop:
    """트레일링 스탑 계산 테스트."""

    def test_trailing_stop_basic(self):
        """기본 트레일링 스탑: high_water_mark - ATR * 1.5."""
        from app.services.dynamic_tp_sl import calculate_trailing_stop

        result = calculate_trailing_stop(high_water_mark=55000, atr=1000.0)
        expected = 55000 - int(1000.0 * 1.5)
        assert result == expected

    def test_trailing_stop_integer_result(self):
        """결과는 정수 (원화)."""
        from app.services.dynamic_tp_sl import calculate_trailing_stop

        result = calculate_trailing_stop(high_water_mark=100000, atr=500.5)
        assert isinstance(result, int)

    def test_trailing_stop_monotonic_increase(self):
        """트레일링 스탑은 단조증가해야 함 (직접 enforce)."""
        from app.services.dynamic_tp_sl import calculate_trailing_stop

        # 시뮬레이션: 가격 상승 → high_water_mark 상승 → 스탑도 상승
        stop1 = calculate_trailing_stop(high_water_mark=50000, atr=1000.0)
        stop2 = calculate_trailing_stop(high_water_mark=55000, atr=1000.0)
        assert stop2 > stop1


class TestShouldActivateTrailingStop:
    """트레일링 스탑 활성화 조건 테스트."""

    def test_activate_when_profit_over_5pct(self):
        """수익률 +5% 이상 시 활성화."""
        from app.services.dynamic_tp_sl import should_activate_trailing_stop

        # 진입가 100,000 → 현재가 105,000 (+5%)
        result = should_activate_trailing_stop(entry_price=100000, current_price=105000)
        assert result is True

    def test_activate_when_profit_exactly_5pct(self):
        """정확히 +5% 시 활성화 (경계값)."""
        from app.services.dynamic_tp_sl import should_activate_trailing_stop

        result = should_activate_trailing_stop(entry_price=100000, current_price=105000)
        assert result is True

    def test_no_activate_when_profit_below_5pct(self):
        """수익률 +5% 미만 시 비활성화."""
        from app.services.dynamic_tp_sl import should_activate_trailing_stop

        # 진입가 100,000 → 현재가 104,000 (+4%)
        result = should_activate_trailing_stop(entry_price=100000, current_price=104000)
        assert result is False

    def test_no_activate_when_loss(self):
        """손실 상태에서는 비활성화."""
        from app.services.dynamic_tp_sl import should_activate_trailing_stop

        result = should_activate_trailing_stop(entry_price=100000, current_price=95000)
        assert result is False


class TestCalculateDynamicTpSl:
    """동적 TP/SL 계산 메인 함수 테스트."""

    @pytest.mark.asyncio
    async def test_atr_based_calculation_high_confidence(self, db):
        """신뢰도 높음(>=0.8): target=2.5x ATR, stop=1.0x ATR."""
        from app.services.dynamic_tp_sl import calculate_dynamic_tp_sl

        # ATR=2000을 직접 반환하도록 _fetch_atr 패치
        with patch(
            "app.services.dynamic_tp_sl._fetch_atr",
            new_callable=AsyncMock,
            return_value=2000.0,
        ):
            result = await calculate_dynamic_tp_sl(
                stock_code="005930",
                entry_price=50000,
                confidence=0.85,  # 높은 신뢰도
                sector_id=None,
                db=db,
            )

        assert result["method"] == "atr_dynamic"
        # target = 50000 + int(2000 * 2.5) = 55000
        assert result["target_price"] == 50000 + int(2000.0 * 2.5)
        # stop = 50000 - int(2000 * 1.0) = 48000
        assert result["stop_loss"] == 50000 - int(2000.0 * 1.0)

    @pytest.mark.asyncio
    async def test_atr_based_calculation_low_confidence(self, db):
        """신뢰도 낮음(<0.5): target=1.5x ATR, stop=2.0x ATR."""
        from app.services.dynamic_tp_sl import calculate_dynamic_tp_sl

        with patch(
            "app.services.dynamic_tp_sl._fetch_atr",
            new_callable=AsyncMock,
            return_value=2000.0,
        ):
            result = await calculate_dynamic_tp_sl(
                stock_code="005930",
                entry_price=50000,
                confidence=0.4,  # 낮은 신뢰도
                sector_id=None,
                db=db,
            )

        # 낮은 신뢰도: stop multiplier 2.0 (더 넓은 손절)
        assert result["method"] == "atr_dynamic"
        assert result["target_price"] == 50000 + int(2000.0 * 1.5)
        assert result["stop_loss"] == 50000 - int(2000.0 * 2.0)

    @pytest.mark.asyncio
    async def test_sector_default_fallback_when_atr_none(self, db):
        """ATR=None 시 섹터 기본값으로 폴백."""
        from app.services.dynamic_tp_sl import calculate_dynamic_tp_sl

        with patch(
            "app.services.dynamic_tp_sl._fetch_atr",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await calculate_dynamic_tp_sl(
                stock_code="005930",
                entry_price=50000,
                confidence=0.7,
                sector_id=None,
                db=db,
            )

        # 섹터 기본값: +10%/-5%
        assert result["method"] == "sector_default"
        assert result["target_price"] == int(50000 * 1.10)
        assert result["stop_loss"] == int(50000 * 0.95)

    @pytest.mark.asyncio
    async def test_sector_default_fallback_when_fetch_raises(self, db):
        """_fetch_atr 예외 시 섹터 기본값으로 폴백."""
        from app.services.dynamic_tp_sl import calculate_dynamic_tp_sl

        with patch(
            "app.services.dynamic_tp_sl._fetch_atr",
            new_callable=AsyncMock,
            side_effect=Exception("네트워크 오류"),
        ):
            result = await calculate_dynamic_tp_sl(
                stock_code="005930",
                entry_price=50000,
                confidence=0.7,
                sector_id=None,
                db=db,
            )

        assert result["method"] == "sector_default"
        assert result["target_price"] > 50000
        assert result["stop_loss"] < 50000

    @pytest.mark.asyncio
    async def test_result_contains_required_keys(self, db):
        """반환값에 필수 키 포함 확인."""
        from app.services.dynamic_tp_sl import calculate_dynamic_tp_sl

        with patch(
            "app.services.dynamic_tp_sl._fetch_atr",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await calculate_dynamic_tp_sl(
                stock_code="005930",
                entry_price=50000,
                confidence=0.7,
                sector_id=None,
                db=db,
            )

        assert "target_price" in result
        assert "stop_loss" in result
        assert "method" in result

    @pytest.mark.asyncio
    async def test_target_always_above_entry(self, db):
        """목표가는 항상 진입가보다 높아야 함."""
        from app.services.dynamic_tp_sl import calculate_dynamic_tp_sl

        with patch(
            "app.services.dynamic_tp_sl._fetch_atr",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await calculate_dynamic_tp_sl(
                stock_code="005930",
                entry_price=50000,
                confidence=0.7,
                sector_id=None,
                db=db,
            )

        assert result["target_price"] > 50000

    @pytest.mark.asyncio
    async def test_stop_always_below_entry(self, db):
        """손절가는 항상 진입가보다 낮아야 함."""
        from app.services.dynamic_tp_sl import calculate_dynamic_tp_sl

        with patch(
            "app.services.dynamic_tp_sl._fetch_atr",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await calculate_dynamic_tp_sl(
                stock_code="005930",
                entry_price=50000,
                confidence=0.7,
                sector_id=None,
                db=db,
            )

        assert result["stop_loss"] < 50000


# ---------------------------------------------------------------------------
# 기존 동작 특성화: paper_trading.py DEFAULT 상수
# ---------------------------------------------------------------------------

class TestCharacterizePaperTradingDefaults:
    """기존 paper_trading.py TP/SL 기본 동작 특성화.

    이 테스트들은 현재 동작을 문서화한다.
    리팩토링 후에도 동일하게 동작해야 한다.
    """

    def test_characterize_default_target_pct(self):
        """기존 기본 목표가 비율: +10%."""
        from app.services.paper_trading import DEFAULT_TARGET_PCT
        # 현재 동작 캡처: 기존 상수값
        assert DEFAULT_TARGET_PCT == pytest.approx(0.10)

    def test_characterize_default_stop_loss_pct(self):
        """기존 기본 손절가 비율: -5%."""
        from app.services.paper_trading import DEFAULT_STOP_LOSS_PCT
        assert DEFAULT_STOP_LOSS_PCT == pytest.approx(0.05)

    def test_characterize_target_calculation(self):
        """기존 목표가 계산: entry_price * (1 + DEFAULT_TARGET_PCT)."""
        from app.services.paper_trading import DEFAULT_TARGET_PCT

        entry_price = 50000
        expected_target = int(entry_price * (1 + DEFAULT_TARGET_PCT))
        assert expected_target == 55000

    def test_characterize_stop_loss_calculation(self):
        """기존 손절가 계산: entry_price * (1 - DEFAULT_STOP_LOSS_PCT)."""
        from app.services.paper_trading import DEFAULT_STOP_LOSS_PCT

        entry_price = 50000
        expected_stop = int(entry_price * (1 - DEFAULT_STOP_LOSS_PCT))
        assert expected_stop == 47500


# ---------------------------------------------------------------------------
# TASK-010: ai_provided 보호 테스트 (마이그레이션 안전성)
# ---------------------------------------------------------------------------

class TestMigrationProtection:
    """기존 포지션 마이그레이션 시 ai_provided 보호 테스트."""

    def test_ai_provided_signals_not_overwritten(self, db):
        """tp_sl_method='ai_provided'인 시그널은 재계산하지 않음."""
        from app.services.dynamic_tp_sl import should_recalculate_tp_sl

        # ai_provided 메서드 → 재계산 불가
        result = should_recalculate_tp_sl(tp_sl_method="ai_provided")
        assert result is False

    def test_legacy_fixed_should_be_recalculated(self):
        """tp_sl_method='legacy_fixed'이면 재계산 대상."""
        from app.services.dynamic_tp_sl import should_recalculate_tp_sl

        result = should_recalculate_tp_sl(tp_sl_method="legacy_fixed")
        assert result is True

    def test_null_method_should_be_recalculated(self):
        """tp_sl_method=None이면 재계산 대상."""
        from app.services.dynamic_tp_sl import should_recalculate_tp_sl

        result = should_recalculate_tp_sl(tp_sl_method=None)
        assert result is True


# ---------------------------------------------------------------------------
# 통합 케이스: ATR 승수 (신뢰도별)
# ---------------------------------------------------------------------------

class TestConfidenceMultipliers:
    """신뢰도별 ATR 승수 테스트."""

    def test_high_confidence_target_multiplier(self):
        """신뢰도 >=0.8: target multiplier=2.5."""
        from app.services.dynamic_tp_sl import (
            TARGET_ATR_HIGH_CONF, STOP_ATR_HIGH_CONF,
        )
        assert TARGET_ATR_HIGH_CONF == pytest.approx(2.5)
        assert STOP_ATR_HIGH_CONF == pytest.approx(1.0)

    def test_low_confidence_multiplier(self):
        """신뢰도 <0.5: target multiplier=1.5, stop multiplier=2.0."""
        from app.services.dynamic_tp_sl import (
            TARGET_ATR_LOW_CONF, STOP_ATR_LOW_CONF,
        )
        assert TARGET_ATR_LOW_CONF == pytest.approx(1.5)
        assert STOP_ATR_LOW_CONF == pytest.approx(2.0)

    def test_default_multiplier(self):
        """기본(중간): target multiplier=2.0, stop multiplier=1.5."""
        from app.services.dynamic_tp_sl import (
            TARGET_ATR_DEFAULT, STOP_ATR_DEFAULT,
        )
        assert TARGET_ATR_DEFAULT == pytest.approx(2.0)
        assert STOP_ATR_DEFAULT == pytest.approx(1.5)
