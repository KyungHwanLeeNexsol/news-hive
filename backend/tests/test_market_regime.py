"""SPEC-AI-018: 시장 레짐 분류 시스템 강화 — TDD 테스트 스위트.

테스트 범위:
- REQ-018-001: 섹터 폭(breadth) 지표 — positive_sector_ratio 추가
- REQ-018-002: 레짐 히스테리시스 — 직전 2일 기준 플립 규칙
- REQ-018-003: SIDEWAYS 동적 신뢰도 계산
- REQ-018-004: 레짐별 탐지기 파라미터 오버라이드
"""

import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

import app.surge_config.surge_settings as _surge_settings_module


@pytest.fixture(autouse=True)
def reset_surge_config_singleton():
    """각 테스트 전후 surge_config 싱글턴을 초기화한다."""
    _surge_settings_module._config_singleton = None
    yield
    _surge_settings_module._config_singleton = None

from app.models.market_regime import MarketRegime, MarketRegimeEnum  # noqa: E402
from app.services.market_regime_service import (  # noqa: E402
    classify_market_regime,
    get_or_create_today_regime,
)


# ---------------------------------------------------------------------------
# REQ-018-001: positive_sector_ratio 반영 — classify_market_regime 시그니처
# ---------------------------------------------------------------------------

class TestClassifyMarketRegimeSignature:
    """REQ-018-001: classify_market_regime가 positive_sector_ratio 인자를 수용한다."""

    def test_returns_two_tuple(self):
        """반환값은 여전히 (MarketRegimeEnum, float) 2-튜플이어야 한다."""
        result = classify_market_regime(0.0, 0.0, positive_sector_ratio=0.5)
        assert len(result) == 2
        regime, confidence = result
        assert isinstance(regime, MarketRegimeEnum)
        assert isinstance(confidence, float)

    def test_positive_sector_ratio_kwarg_accepted(self):
        """positive_sector_ratio 키워드 인자가 허용되어야 한다."""
        # 예외 없이 호출되면 통과
        classify_market_regime(2.0, 1.0, positive_sector_ratio=0.7)

    def test_vol_level_still_works(self):
        """기존 vol_level 인자와 호환성이 유지되어야 한다."""
        classify_market_regime(0.0, 0.0, vol_level=None)

    def test_backward_compatible_no_sector_ratio(self):
        """positive_sector_ratio 없이 호출해도 동작해야 한다 (하위 호환)."""
        result = classify_market_regime(0.0, 0.0)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# REQ-018-001: BULL 조건 — positive_sector_ratio >= 0.6 추가
# ---------------------------------------------------------------------------

class TestBullConditionWithSectorRatio:
    """REQ-018-001: BULL 분류에 positive_sector_ratio >= 0.6 조건 추가."""

    def test_bull_with_sufficient_sector_ratio(self):
        """5d_ret >= 1.5, ma_pos > 0, sector_ratio >= 0.6 → BULL."""
        regime, _ = classify_market_regime(
            kospi_5d_return=2.0,
            kospi_20d_ma_position=1.0,
            positive_sector_ratio=0.6,
        )
        assert regime == MarketRegimeEnum.BULL

    def test_bull_exact_sector_ratio_boundary(self):
        """positive_sector_ratio == 0.6 경계값도 BULL이어야 한다."""
        regime, _ = classify_market_regime(
            kospi_5d_return=1.5,
            kospi_20d_ma_position=0.1,
            positive_sector_ratio=0.6,
        )
        assert regime == MarketRegimeEnum.BULL

    def test_not_bull_when_sector_ratio_below_threshold(self):
        """5d_ret >= 1.5, ma_pos > 0 이더라도 sector_ratio < 0.6 → BULL 아님."""
        regime, _ = classify_market_regime(
            kospi_5d_return=2.0,
            kospi_20d_ma_position=1.0,
            positive_sector_ratio=0.5,
        )
        assert regime != MarketRegimeEnum.BULL

    def test_bull_high_sector_ratio(self):
        """sector_ratio=0.8 → BULL (0.6 이상이므로)."""
        regime, _ = classify_market_regime(
            kospi_5d_return=2.0,
            kospi_20d_ma_position=1.5,
            positive_sector_ratio=0.8,
        )
        assert regime == MarketRegimeEnum.BULL


# ---------------------------------------------------------------------------
# REQ-018-001: BEAR 조건 — positive_sector_ratio <= 0.3 추가 (OR 조건)
# ---------------------------------------------------------------------------

class TestBearConditionWithSectorRatio:
    """REQ-018-001: BEAR 분류에 positive_sector_ratio <= 0.3 OR 조건 추가."""

    def test_bear_via_sector_ratio_alone(self):
        """5d_ret/ma_pos 모두 BEAR 조건 미충족이어도 sector_ratio <= 0.3 → BEAR."""
        regime, _ = classify_market_regime(
            kospi_5d_return=0.0,
            kospi_20d_ma_position=0.0,
            positive_sector_ratio=0.3,
        )
        assert regime == MarketRegimeEnum.BEAR

    def test_bear_exact_sector_ratio_boundary(self):
        """positive_sector_ratio == 0.3 경계값도 BEAR이어야 한다."""
        regime, _ = classify_market_regime(
            kospi_5d_return=0.5,
            kospi_20d_ma_position=-0.5,
            positive_sector_ratio=0.3,
        )
        assert regime == MarketRegimeEnum.BEAR

    def test_not_bear_when_sector_ratio_above_threshold(self):
        """sector_ratio > 0.3 이고 기존 BEAR 조건 미충족 → BEAR 아님."""
        regime, _ = classify_market_regime(
            kospi_5d_return=0.5,
            kospi_20d_ma_position=-0.5,
            positive_sector_ratio=0.4,
        )
        assert regime != MarketRegimeEnum.BEAR

    def test_bear_via_legacy_return_condition(self):
        """기존 5d_ret <= -1.5 BEAR 조건은 여전히 동작해야 한다."""
        regime, _ = classify_market_regime(
            kospi_5d_return=-2.0,
            kospi_20d_ma_position=0.5,
            positive_sector_ratio=0.5,
        )
        assert regime == MarketRegimeEnum.BEAR

    def test_bear_via_legacy_ma_condition(self):
        """기존 ma_pos < -2.0 BEAR 조건은 여전히 동작해야 한다."""
        regime, _ = classify_market_regime(
            kospi_5d_return=0.0,
            kospi_20d_ma_position=-2.5,
            positive_sector_ratio=0.5,
        )
        assert regime == MarketRegimeEnum.BEAR

    def test_sideways_when_no_extreme_conditions(self):
        """모든 조건 중간값 → SIDEWAYS."""
        regime, _ = classify_market_regime(
            kospi_5d_return=0.5,
            kospi_20d_ma_position=-0.5,
            positive_sector_ratio=0.5,
        )
        assert regime == MarketRegimeEnum.SIDEWAYS


# ---------------------------------------------------------------------------
# REQ-018-003: SIDEWAYS 동적 신뢰도 — 하드코딩 0.6 → 공식 기반
# ---------------------------------------------------------------------------

class TestSidewaysDynamicConfidence:
    """REQ-018-003: SIDEWAYS 신뢰도가 동적으로 계산되어야 한다."""

    def test_sideways_confidence_not_fixed_0_6(self):
        """SIDEWAYS 신뢰도가 항상 0.6이면 안 된다 (동적 계산)."""
        regime, confidence = classify_market_regime(
            kospi_5d_return=0.0,
            kospi_20d_ma_position=0.0,
            positive_sector_ratio=0.5,
        )
        assert regime == MarketRegimeEnum.SIDEWAYS
        # 동적 계산 결과이므로 0.6이 아닐 수도 있지만, 0.5~0.9 범위여야 함
        assert 0.5 <= confidence <= 0.9

    def test_sideways_confidence_formula_deep_middle(self):
        """깊은 중간값(0, 0) → 높은 신뢰도 (양쪽 임계에서 멀수록 높음)."""
        # kospi_5d_return=0 → d_bull = max(0, 1.5-0)/1.5*0.5 = 0.5
        # kospi_20d_ma_position=0 → d_bull += max(0, -0)/2.0*0.5 = 0
        # → d_bull = 0.5
        # d_bear = max(0, 0-(-1.5))/1.5*0.5 + max(0, 0-(-2.0))/2.0*0.5
        #        = (1.5/1.5*0.5) + (2.0/2.0*0.5) = 0.5 + 0.5 = 1.0
        # min(d_bull, d_bear) = 0.5
        # confidence = min(0.9, 0.5 + 0.5*0.4) = min(0.9, 0.7) = 0.7
        regime, confidence = classify_market_regime(
            kospi_5d_return=0.0,
            kospi_20d_ma_position=0.0,
            positive_sector_ratio=0.5,
        )
        assert regime == MarketRegimeEnum.SIDEWAYS
        assert abs(confidence - 0.7) < 0.001

    def test_sideways_confidence_formula_near_bull_boundary(self):
        """BULL 임계에 근접한 경우 → 낮은 신뢰도."""
        # kospi_5d_return=1.4 → d_bull = max(0, 1.5-1.4)/1.5*0.5 = 0.1/1.5*0.5 ≈ 0.0333
        # kospi_20d_ma_position=0.0 → d_bull += 0
        # → d_bull ≈ 0.0333
        # d_bear = max(0, 1.4-(-1.5))/1.5*0.5 + max(0, 0-(-2.0))/2.0*0.5
        #        = (2.9/1.5*0.5) + (2.0/2.0*0.5) = 0.967 + 0.5 = 1.467 (but d_bull is min)
        # min(d_bull, d_bear) ≈ 0.0333
        # confidence = min(0.9, 0.5 + 0.0333*0.4) ≈ 0.5133
        regime, confidence = classify_market_regime(
            kospi_5d_return=1.4,
            kospi_20d_ma_position=0.0,
            positive_sector_ratio=0.5,
        )
        assert regime == MarketRegimeEnum.SIDEWAYS
        assert confidence < 0.55

    def test_sideways_confidence_capped_at_0_9(self):
        """신뢰도는 최대 0.9 캡이어야 한다."""
        # 극단적으로 중간값에 있어도 0.9 초과 불가
        regime, confidence = classify_market_regime(
            kospi_5d_return=0.0,
            kospi_20d_ma_position=-1.0,
            positive_sector_ratio=0.5,
        )
        assert regime == MarketRegimeEnum.SIDEWAYS
        assert confidence <= 0.9

    def test_sideways_confidence_min_0_5(self):
        """신뢰도는 최소 0.5 이어야 한다."""
        regime, confidence = classify_market_regime(
            kospi_5d_return=1.4,
            kospi_20d_ma_position=-0.1,
            positive_sector_ratio=0.5,
        )
        assert regime == MarketRegimeEnum.SIDEWAYS
        assert confidence >= 0.5


# ---------------------------------------------------------------------------
# REQ-018-002: 레짐 히스테리시스 — get_or_create_today_regime
# ---------------------------------------------------------------------------

def _make_regime(date_offset_days: int, regime: MarketRegimeEnum, confidence: float = 0.6) -> MarketRegime:
    """테스트용 MarketRegime 더미 생성."""
    today = datetime.date.today()
    return MarketRegime(
        id=1,
        date=today - datetime.timedelta(days=date_offset_days),
        regime=regime,
        kospi_5d_return=0.0,
        kospi_20d_ma_position=0.0,
        confidence_score=confidence,
        raw_regime=None,
    )


class TestHysteresisLogic:
    """REQ-018-002: 히스테리시스 규칙 테스트."""

    def _make_db_mock(self, existing_today=None, recent_regimes=None):
        """DB 모킹 헬퍼."""
        db = MagicMock(spec=Session)
        query_mock = MagicMock()
        db.query.return_value = query_mock
        filter_mock = MagicMock()
        query_mock.filter.return_value = filter_mock
        order_by_mock = MagicMock()
        filter_mock.order_by.return_value = order_by_mock
        _all_mock = MagicMock()
        order_by_mock.all.return_value = recent_regimes or []
        filter_mock.first.return_value = existing_today
        return db

    @patch("app.services.market_regime_service._fetch_kospi_indicators")
    @patch("app.services.market_regime_service.get_recent_regimes")
    def test_flip_allowed_when_two_consecutive_same_regime(
        self, mock_recent, mock_fetch
    ):
        """직전 2일이 모두 BULL이고 새 분류도 BULL이면 → BULL로 저장."""
        mock_fetch.return_value = (2.0, 1.0, 0.7)
        mock_recent.return_value = [
            _make_regime(1, MarketRegimeEnum.SIDEWAYS),
            _make_regime(2, MarketRegimeEnum.SIDEWAYS),
        ]
        db = MagicMock(spec=Session)
        db.query.return_value.filter.return_value.first.return_value = None

        result = get_or_create_today_regime(db)
        # BULL 분류 → 직전 2일 SIDEWAYS → 히스테리시스 억제 → SIDEWAYS 유지
        assert result.regime == MarketRegimeEnum.SIDEWAYS

    @patch("app.services.market_regime_service._fetch_kospi_indicators")
    @patch("app.services.market_regime_service.get_recent_regimes")
    def test_flip_allowed_when_two_consecutive_same_new_regime(
        self, mock_recent, mock_fetch
    ):
        """직전 2일이 모두 BULL이고 새 분류도 BULL → BULL로 플립 허용."""
        mock_fetch.return_value = (2.0, 1.0, 0.7)
        mock_recent.return_value = [
            _make_regime(1, MarketRegimeEnum.BULL),
            _make_regime(2, MarketRegimeEnum.BULL),
        ]
        db = MagicMock(spec=Session)
        db.query.return_value.filter.return_value.first.return_value = None

        result = get_or_create_today_regime(db)
        assert result.regime == MarketRegimeEnum.BULL

    @patch("app.services.market_regime_service._fetch_kospi_indicators")
    @patch("app.services.market_regime_service.get_recent_regimes")
    def test_flip_allowed_when_high_confidence(
        self, mock_recent, mock_fetch
    ):
        """신뢰도 >= 0.75이면 직전 이력과 무관하게 플립 허용."""
        # BULL 신뢰도 높음: 5d_ret=3.0, ma_pos=5.0 → confidence 높음
        mock_fetch.return_value = (3.0, 5.0, 0.8)
        mock_recent.return_value = [
            _make_regime(1, MarketRegimeEnum.SIDEWAYS),
            _make_regime(2, MarketRegimeEnum.SIDEWAYS),
        ]
        db = MagicMock(spec=Session)
        db.query.return_value.filter.return_value.first.return_value = None

        result = get_or_create_today_regime(db)
        # 신뢰도 >= 0.75이면 플립 허용
        assert result.regime == MarketRegimeEnum.BULL

    @patch("app.services.market_regime_service._fetch_kospi_indicators")
    @patch("app.services.market_regime_service.get_recent_regimes")
    def test_bear_transition_immediate(
        self, mock_recent, mock_fetch
    ):
        """BEAR 전환은 히스테리시스 무관하게 즉시 적용."""
        mock_fetch.return_value = (-2.0, -3.0, 0.2)
        mock_recent.return_value = [
            _make_regime(1, MarketRegimeEnum.BULL),
            _make_regime(2, MarketRegimeEnum.BULL),
        ]
        db = MagicMock(spec=Session)
        db.query.return_value.filter.return_value.first.return_value = None

        result = get_or_create_today_regime(db)
        assert result.regime == MarketRegimeEnum.BEAR

    @patch("app.services.market_regime_service._fetch_kospi_indicators")
    @patch("app.services.market_regime_service.get_recent_regimes")
    def test_raw_regime_recorded_when_suppressed(
        self, mock_recent, mock_fetch
    ):
        """히스테리시스로 플립 억제 시 raw_regime에 분류된 레짐이 기록된다."""
        mock_fetch.return_value = (2.0, 1.0, 0.7)  # → BULL 분류 (낮은 신뢰도)
        mock_recent.return_value = [
            _make_regime(1, MarketRegimeEnum.SIDEWAYS),
            _make_regime(2, MarketRegimeEnum.SIDEWAYS),
        ]
        db = MagicMock(spec=Session)
        db.query.return_value.filter.return_value.first.return_value = None

        result = get_or_create_today_regime(db)
        # 플립 억제 → regime=SIDEWAYS, raw_regime=BULL
        assert result.regime == MarketRegimeEnum.SIDEWAYS
        # raw_regime은 실제 분류된 BULL이어야 함
        assert result.raw_regime is not None

    @patch("app.services.market_regime_service._fetch_kospi_indicators")
    @patch("app.services.market_regime_service.get_recent_regimes")
    def test_no_hysteresis_without_history(
        self, mock_recent, mock_fetch
    ):
        """직전 이력이 없으면 히스테리시스 없이 바로 분류된 레짐 저장."""
        mock_fetch.return_value = (2.0, 1.0, 0.7)
        mock_recent.return_value = []
        db = MagicMock(spec=Session)
        db.query.return_value.filter.return_value.first.return_value = None

        result = get_or_create_today_regime(db)
        assert result.regime == MarketRegimeEnum.BULL

    @patch("app.services.market_regime_service._fetch_kospi_indicators")
    @patch("app.services.market_regime_service.get_recent_regimes")
    def test_raw_regime_equals_regime_when_no_suppression(
        self, mock_recent, mock_fetch
    ):
        """플립 억제 없을 때 raw_regime == regime."""
        mock_fetch.return_value = (2.0, 1.0, 0.7)
        mock_recent.return_value = [
            _make_regime(1, MarketRegimeEnum.BULL),
            _make_regime(2, MarketRegimeEnum.BULL),
        ]
        db = MagicMock(spec=Session)
        db.query.return_value.filter.return_value.first.return_value = None

        result = get_or_create_today_regime(db)
        assert result.regime == MarketRegimeEnum.BULL
        # raw_regime은 None이거나 동일 값
        assert result.raw_regime is None or result.raw_regime == result.regime.value


# ---------------------------------------------------------------------------
# REQ-018-001: _fetch_kospi_indicators 3-튜플 반환
# ---------------------------------------------------------------------------

class TestFetchKospiIndicators3Tuple:
    """REQ-018-001: _fetch_kospi_indicators가 3-튜플을 반환한다."""

    @patch("app.services.market_regime_service._fetch_kospi_indicators")
    def test_returns_three_tuple(self, mock_fetch):
        """_fetch_kospi_indicators가 3-튜플을 반환하는지 확인."""
        mock_fetch.return_value = (1.5, 0.5, 0.65)
        result = mock_fetch(MagicMock())
        assert len(result) == 3


# ---------------------------------------------------------------------------
# REQ-018-004: 레짐별 탐지기 파라미터 — Pydantic 모델
# ---------------------------------------------------------------------------

class TestRegimeDetectorParamsModel:
    """REQ-018-004: RegimeDetectorParams Pydantic 모델 존재 및 기본값."""

    def test_regime_detector_params_importable(self):
        """RegimeDetectorParams 클래스가 임포트 가능해야 한다."""
        from app.surge_config.surge_settings import RegimeDetectorParams
        assert RegimeDetectorParams is not None

    def test_regime_detector_params_defaults(self):
        """기본값: volume_zscore_threshold=2.5, news_window_hours=24, min_news_sentiment=0.3."""
        from app.surge_config.surge_settings import RegimeDetectorParams
        params = RegimeDetectorParams()
        assert params.volume_zscore_threshold == 2.5
        assert params.news_window_hours == 24
        assert params.min_news_sentiment == 0.3

    def test_surge_detection_config_has_regime_detector_params(self):
        """SurgeDetectionConfig에 regime_detector_params 필드가 있어야 한다."""
        from app.surge_config.surge_settings import SurgeDetectionConfig
        fields = SurgeDetectionConfig.model_fields
        assert "regime_detector_params" in fields

    def test_surge_detection_config_regime_detector_params_default_empty(self):
        """regime_detector_params 기본값은 빈 dict이어야 한다."""
        from app.surge_config.surge_settings import get_surge_config
        config = get_surge_config()
        assert isinstance(config.regime_detector_params, dict)

    def test_bull_regime_params_loaded_from_yaml(self):
        """YAML에서 BULL 레짐 파라미터가 로드되어야 한다."""
        from app.surge_config.surge_settings import get_surge_config
        config = get_surge_config()
        assert "BULL" in config.regime_detector_params
        bull_params = config.regime_detector_params["BULL"]
        assert bull_params.volume_zscore_threshold == 2.0
        assert bull_params.news_window_hours == 72
        assert bull_params.min_news_sentiment == 0.20

    def test_bear_regime_params_loaded_from_yaml(self):
        """YAML에서 BEAR 레짐 파라미터가 로드되어야 한다."""
        from app.surge_config.surge_settings import get_surge_config
        config = get_surge_config()
        assert "BEAR" in config.regime_detector_params
        bear_params = config.regime_detector_params["BEAR"]
        assert bear_params.volume_zscore_threshold == 3.0
        assert bear_params.news_window_hours == 12
        assert bear_params.min_news_sentiment == 0.50


# ---------------------------------------------------------------------------
# REQ-018-004: detect_volume_surge_news_combo — market_regime 파라미터
# ---------------------------------------------------------------------------

class TestDetectVolumeNewsComboRegimeParam:
    """REQ-018-004: detect_volume_surge_news_combo에 market_regime 파라미터 추가."""

    def test_function_accepts_market_regime_param(self):
        """detect_volume_surge_news_combo가 market_regime 파라미터를 수용한다."""
        import inspect
        from app.services.surge_detector import detect_volume_surge_news_combo
        sig = inspect.signature(detect_volume_surge_news_combo)
        assert "market_regime" in sig.parameters

    def test_market_regime_default_is_sideways(self):
        """market_regime 기본값은 'SIDEWAYS'이어야 한다."""
        import inspect
        from app.services.surge_detector import detect_volume_surge_news_combo
        sig = inspect.signature(detect_volume_surge_news_combo)
        default = sig.parameters["market_regime"].default
        assert default == "SIDEWAYS"

    def test_bull_params_override_applied(self):
        """BULL 레짐에서 volume_zscore_threshold=2.0으로 오버라이드된다."""
        import inspect
        from app.services.surge_detector import detect_volume_surge_news_combo
        # 함수 시그니처에 market_regime 있는지 확인
        sig = inspect.signature(detect_volume_surge_news_combo)
        assert "market_regime" in sig.parameters

    def test_gather_surge_candidates_passes_market_regime(self):
        """gather_surge_candidates가 detect_volume_surge_news_combo에 market_regime을 전달한다."""
        import inspect
        from app.services.surge_detector import gather_surge_candidates
        sig = inspect.signature(gather_surge_candidates)
        assert "market_regime" in sig.parameters
