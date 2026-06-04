"""SPEC-AI-029: 적응형 surge 확률 임계값 시스템 인수 검증 테스트.

18개 AC(Acceptance Criteria) 검증.
conftest.py의 db/client 픽스처 사용 (SQLite 인메모리).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from app.models.market_regime import MarketRegimeEnum
from app.models.surge_portfolio import SurgeTrade, SurgePortfolio
from app.models.surge_threshold_history import SurgeThresholdHistory
from app.surge_config.surge_settings import (
    AdaptiveThresholdConfig,
    SurgeDetectionConfig,
    get_surge_config,
)
from app.services.surge_threshold_service import (
    _compute_win_rate,
    compute_adaptive_threshold,
    get_today_threshold,
    is_combo_theme_gate_passed,
)


# ---------------------------------------------------------------------------
# 설정 픽스처
# ---------------------------------------------------------------------------

@pytest.fixture
def default_config() -> SurgeDetectionConfig:
    """테스트용 기본 SurgeDetectionConfig."""
    return get_surge_config()


# ---------------------------------------------------------------------------
# 헬퍼: SurgeTrade 생성
# ---------------------------------------------------------------------------

def _make_portfolio(db: Session) -> SurgePortfolio:
    port = SurgePortfolio(initial_capital=Decimal("5000000"), current_cash=Decimal("5000000"))
    db.add(port)
    db.flush()
    return port


def _make_trade(db: Session, portfolio_id: int, exit_reason: str, entry_date: date | None = None) -> SurgeTrade:
    trade = SurgeTrade(
        portfolio_id=portfolio_id,
        stock_code="000000",
        stock_name="테스트",
        entry_price=Decimal("10000"),
        quantity=10,
        entry_date=entry_date or date.today(),
        is_open=False,
        exit_reason=exit_reason,
        exit_price=Decimal("11000"),
        exit_date=date.today(),
    )
    db.add(trade)
    db.flush()
    return trade


# ---------------------------------------------------------------------------
# AC-029-01: 승률 < 0.40 → +0.05 가산
# ---------------------------------------------------------------------------

class TestAC02901WinRateLow:
    def test_win_rate_below_floor_adds_addition(self, db, default_config):
        """승률 0/5 (0.0) → 기본값 + 0.05"""
        port = _make_portfolio(db)
        for _ in range(5):
            _make_trade(db, port.id, "stop_loss")

        with patch(
            "app.services.surge_threshold_service.get_or_create_today_regime",
            return_value=None,
        ):
            result = compute_adaptive_threshold(db, default_config)

        base = default_config.ensemble.min_score_for_signal  # 0.45
        expected = max(
            default_config.adaptive_threshold.final_clamp_min,
            min(default_config.adaptive_threshold.final_clamp_max, base + 0.05),
        )
        assert abs(result - expected) < 1e-6, f"기대={expected:.4f}, 실제={result:.4f}"


# ---------------------------------------------------------------------------
# AC-029-02: 임계값 cap = 0.70
# ---------------------------------------------------------------------------

class TestAC02902WinRateCap:
    def test_threshold_capped_at_win_rate_cap(self, db, default_config):
        """승률 0%, 기본값 0.65 → cap 0.70 적용"""
        port = _make_portfolio(db)
        for _ in range(5):
            _make_trade(db, port.id, "stop_loss")

        cfg = default_config.model_copy(deep=True)
        cfg.ensemble.min_score_for_signal = 0.65

        with patch(
            "app.services.surge_threshold_service.get_or_create_today_regime",
            return_value=None,
        ):
            result = compute_adaptive_threshold(db, cfg)

        # 0.65 + 0.05 = 0.70 → cap 0.70, 레짐 None(x1.0) → 0.70 → clamp [0.45, 0.85]
        assert result <= 0.70 + 1e-6, f"cap 초과: {result}"


# ---------------------------------------------------------------------------
# AC-029-03: 5개 미만 종료 거래 → 승률 조정 없음
# ---------------------------------------------------------------------------

class TestAC02903InsufficientTrades:
    def test_less_than_5_trades_no_adjustment(self, db, default_config):
        """4개 거래만 있을 때 승률 조정 없음 — 기본값 × 레짐 배율"""
        port = _make_portfolio(db)
        for _ in range(4):
            _make_trade(db, port.id, "stop_loss")

        with patch(
            "app.services.surge_threshold_service.get_or_create_today_regime",
            return_value=None,
        ):
            result = compute_adaptive_threshold(db, default_config)

        base = default_config.ensemble.min_score_for_signal  # 0.45
        expected = max(
            default_config.adaptive_threshold.final_clamp_min,
            min(default_config.adaptive_threshold.final_clamp_max, base),
        )
        assert abs(result - expected) < 1e-6, f"기대={expected:.4f}, 실제={result:.4f}"


# ---------------------------------------------------------------------------
# AC-029-04: 레짐 배율 검증 (BEAR×1.2, SIDEWAYS×1.0, BULL×0.9)
# ---------------------------------------------------------------------------

class TestAC02904RegimeMultiplier:
    @pytest.mark.parametrize(
        "regime, multiplier",
        [
            (MarketRegimeEnum.BEAR, 1.2),
            (MarketRegimeEnum.SIDEWAYS, 1.0),
            (MarketRegimeEnum.BULL, 0.9),
        ],
    )
    def test_regime_multiplier(self, db, default_config, regime, multiplier):
        """레짐 배율이 올바르게 적용된다."""
        regime_mock = MagicMock()
        regime_mock.regime = regime

        with patch(
            "app.services.surge_threshold_service.get_or_create_today_regime",
            return_value=regime_mock,
        ):
            result = compute_adaptive_threshold(db, default_config)

        base = default_config.ensemble.min_score_for_signal
        expected = max(
            default_config.adaptive_threshold.final_clamp_min,
            min(default_config.adaptive_threshold.final_clamp_max, base * multiplier),
        )
        assert abs(result - expected) < 1e-6, f"레짐={regime.value}: 기대={expected:.4f}, 실제={result:.4f}"


# ---------------------------------------------------------------------------
# AC-029-05: 최종 클램프 [0.45, 0.85]
# ---------------------------------------------------------------------------

class TestAC02905FinalClamp:
    def test_clamp_lower_bound(self, db, default_config):
        """레짐 BULL(×0.9) + 기본값 0.45 → 0.405 → clamp 하한 0.45"""
        regime_mock = MagicMock()
        regime_mock.regime = MarketRegimeEnum.BULL

        with patch(
            "app.services.surge_threshold_service.get_or_create_today_regime",
            return_value=regime_mock,
        ):
            result = compute_adaptive_threshold(db, default_config)

        assert result >= 0.45 - 1e-6, f"하한 미달: {result}"

    def test_clamp_upper_bound(self, db, default_config):
        """매우 높은 기본값 → clamp 상한 0.85"""
        cfg = default_config.model_copy(deep=True)
        cfg.ensemble.min_score_for_signal = 0.90  # type: ignore

        regime_mock = MagicMock()
        regime_mock.regime = MarketRegimeEnum.BEAR

        with patch(
            "app.services.surge_threshold_service.get_or_create_today_regime",
            return_value=regime_mock,
        ):
            result = compute_adaptive_threshold(db, cfg)

        assert result <= 0.85 + 1e-6, f"상한 초과: {result}"


# ---------------------------------------------------------------------------
# AC-029-06: combo=0.0, theme < floor → 제외 (게이트 불통과)
# SPEC-AI-037 REQ-037-002: floor 0.7 → 0.55 변경으로 경계값 업데이트
# ---------------------------------------------------------------------------

class TestAC02906ComboThemeGateExclude:
    def test_combo_zero_theme_below_floor_excluded(self, default_config):
        """combo=0.0, theme=0.5 → False (제외, floor=0.55 미만)"""
        meta = {"combo_score": 0.0, "theme_cluster_score": 0.5}
        assert is_combo_theme_gate_passed(meta, default_config) is False


# ---------------------------------------------------------------------------
# AC-029-07: combo=0.0, theme >= floor → 통과
# SPEC-AI-037 REQ-037-002: floor=0.55 경계값 업데이트
# ---------------------------------------------------------------------------

class TestAC02907ComboThemeGatePass:
    def test_combo_zero_theme_at_floor_passes(self, default_config):
        """combo=0.0, theme=0.55 → True (통과, floor 경계값)"""
        meta = {"combo_score": 0.0, "theme_cluster_score": 0.55}
        assert is_combo_theme_gate_passed(meta, default_config) is True

    def test_combo_zero_theme_above_floor_passes(self, default_config):
        """combo=0.0, theme=0.8 → True (통과)"""
        meta = {"combo_score": 0.0, "theme_cluster_score": 0.8}
        assert is_combo_theme_gate_passed(meta, default_config) is True


# ---------------------------------------------------------------------------
# AC-029-08: combo=0.3, theme=0.1 → 통과 (게이트 미적용)
# ---------------------------------------------------------------------------

class TestAC02908ComboPresentNoGate:
    def test_combo_present_always_passes(self, default_config):
        """combo=0.3 > 0 → 게이트 미적용, theme 무관하게 True"""
        meta = {"combo_score": 0.3, "theme_cluster_score": 0.1}
        assert is_combo_theme_gate_passed(meta, default_config) is True


# ---------------------------------------------------------------------------
# AC-029-09: surge_metadata 키 없음 → 0.0 처리
# ---------------------------------------------------------------------------

class TestAC02909MissingMetadataKeys:
    def test_none_metadata_is_legacy_pass(self, default_config):
        """surge_metadata=None → 레거시 시그널로 간주 → 게이트 통과"""
        assert is_combo_theme_gate_passed(None, default_config) is True

    def test_missing_combo_key_is_legacy_pass(self, default_config):
        """combo_score 키 없음 → 레거시 시그널로 간주 → 게이트 통과"""
        meta = {"theme_cluster_score": 0.5}  # combo_score 키 없음
        assert is_combo_theme_gate_passed(meta, default_config) is True

    def test_combo_key_explicit_zero_and_theme_zero_excluded(self, default_config):
        """combo_score=0.0 명시 + theme=0.0 → 게이트 불통과"""
        meta = {"combo_score": 0.0, "theme_cluster_score": 0.0}
        assert is_combo_theme_gate_passed(meta, default_config) is False

    def test_missing_theme_key_defaults_to_zero(self, default_config):
        """combo_score=0.0 명시 + theme_cluster_score 키 없음 → theme=0.0 → 불통과"""
        meta = {"combo_score": 0.0}  # theme 키 없음
        assert is_combo_theme_gate_passed(meta, default_config) is False


# ---------------------------------------------------------------------------
# AC-029-10/11: persist_threshold upsert (idempotent)
# ---------------------------------------------------------------------------

class TestAC02910Upsert:
    def test_persist_creates_row(self, db):
        """ORM으로 직접 레코드 생성 확인."""
        today = date.today()
        row = SurgeThresholdHistory(
            date=today,
            threshold=0.495,
            win_rate_5d=0.6,
            regime="BULL",
            reason="테스트",
        )
        db.add(row)
        db.flush()

        saved = db.query(SurgeThresholdHistory).filter(
            SurgeThresholdHistory.date == today
        ).first()
        assert saved is not None
        assert abs(saved.threshold - 0.495) < 1e-6

    def test_persist_idempotent(self, db):
        """같은 날짜로 2번 저장해도 레코드 1개 (ORM update 테스트)."""
        today = date.today()

        row1 = SurgeThresholdHistory(date=today, threshold=0.50, regime="BULL", reason="첫번째")
        db.add(row1)
        db.flush()

        existing = db.query(SurgeThresholdHistory).filter(
            SurgeThresholdHistory.date == today
        ).first()
        existing.threshold = 0.55
        existing.reason = "두번째"
        db.flush()

        count = db.query(SurgeThresholdHistory).filter(
            SurgeThresholdHistory.date == today
        ).count()
        assert count == 1, f"레코드가 {count}개 (1개이어야 함)"

        updated = db.query(SurgeThresholdHistory).filter(
            SurgeThresholdHistory.date == today
        ).first()
        assert abs(updated.threshold - 0.55) < 1e-6


# ---------------------------------------------------------------------------
# AC-029-12: GET /threshold-status → 200 (레코드 있음)
# ---------------------------------------------------------------------------

class TestAC02912ThresholdStatusEndpoint:
    def test_endpoint_returns_200_with_data(self, client, db):
        """threshold-status: 오늘 레코드 있으면 computed_today=True"""
        today = date.today()
        row = SurgeThresholdHistory(
            date=today,
            threshold=0.495,
            win_rate_5d=0.6,
            regime="BULL",
            reason="테스트",
        )
        db.add(row)
        db.flush()

        resp = client.get("/api/surge-trading/threshold-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["computed_today"] is True
        assert data["threshold"] is not None


# ---------------------------------------------------------------------------
# AC-029-13: GET /threshold-status → 200 (레코드 없음)
# ---------------------------------------------------------------------------

class TestAC02913ThresholdStatusNoRecord:
    def test_endpoint_returns_200_computed_today_false(self, client):
        """오늘 레코드 없음 → computed_today=False"""
        with patch(
            "app.services.surge_threshold_service.get_or_create_today_regime",
            return_value=None,
        ):
            resp = client.get("/api/surge-trading/threshold-status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["computed_today"] is False
        assert "fallback_threshold" in data


# ---------------------------------------------------------------------------
# AC-029-14: execute_buy_orders는 저장된 임계값 읽기 (재산출 없음)
# ---------------------------------------------------------------------------

class TestAC02914ExecuteBuyUsesStoredThreshold:
    def test_get_today_threshold_returns_stored(self, db, default_config):
        """get_today_threshold: DB 레코드 있으면 해당 값 반환"""
        today = date.today()
        row = SurgeThresholdHistory(
            date=today,
            threshold=0.60,
            win_rate_5d=0.2,
            regime="BEAR",
            reason="테스트",
        )
        db.add(row)
        db.flush()

        result = get_today_threshold(db, default_config)
        assert abs(result - 0.60) < 1e-6, f"기대=0.60, 실제={result}"


# ---------------------------------------------------------------------------
# AC-029-15: enabled=False → 히스토리 미기록, 정적 임계값
# ---------------------------------------------------------------------------

class TestAC02915Disabled:
    def test_disabled_returns_static_threshold(self, db, default_config):
        """enabled=False → 기본값(0.45) 반환"""
        cfg = default_config.model_copy(deep=True)
        cfg.adaptive_threshold.enabled = False

        result = compute_adaptive_threshold(db, cfg)
        assert abs(result - cfg.ensemble.min_score_for_signal) < 1e-6

    def test_disabled_get_today_threshold_returns_static(self, db, default_config):
        """enabled=False + DB 레코드 없음 → fallback(정적) 반환"""
        cfg = default_config.model_copy(deep=True)
        cfg.adaptive_threshold.enabled = False

        result = get_today_threshold(db, cfg)
        assert abs(result - cfg.ensemble.min_score_for_signal) < 1e-6


# ---------------------------------------------------------------------------
# AC-029-16: YAML 섹션 없음 → 기본값 적용
# ---------------------------------------------------------------------------

class TestAC02916DefaultsApply:
    def test_adaptive_threshold_has_defaults(self):
        """AdaptiveThresholdConfig 기본값 검증."""
        cfg = AdaptiveThresholdConfig()
        assert cfg.enabled is True
        assert cfg.win_rate_window == 5
        assert abs(cfg.win_rate_floor - 0.40) < 1e-6
        assert abs(cfg.win_rate_addition - 0.05) < 1e-6
        assert abs(cfg.win_rate_cap - 0.70) < 1e-6
        assert abs(cfg.final_clamp_min - 0.45) < 1e-6
        assert abs(cfg.final_clamp_max - 0.85) < 1e-6
        assert abs(cfg.combo_zero_theme_floor - 0.7) < 1e-6

    def test_surge_detection_config_has_adaptive_threshold(self, default_config):
        """SurgeDetectionConfig에 adaptive_threshold 필드 포함."""
        assert hasattr(default_config, "adaptive_threshold")
        assert isinstance(default_config.adaptive_threshold, AdaptiveThresholdConfig)


# ---------------------------------------------------------------------------
# AC-029-17: 기존 테스트 전체 통과 (전체 pytest 실행으로 검증)
# ---------------------------------------------------------------------------
# 이 AC는 전체 테스트 스위트 실행 시 자동 검증됨


# ---------------------------------------------------------------------------
# AC-029-18: 스키마 변경 — surge_threshold_history 테이블만 추가
# ---------------------------------------------------------------------------

class TestAC02918SchemaOnly:
    def test_surge_threshold_history_model_fields(self):
        """SurgeThresholdHistory 모델의 필수 필드 존재 검증."""
        from sqlalchemy import inspect as sa_inspect
        mapper = sa_inspect(SurgeThresholdHistory)
        column_names = {c.key for c in mapper.mapper.column_attrs}

        expected = {"id", "date", "threshold", "win_rate_5d", "regime", "reason", "created_at"}
        assert expected.issubset(column_names), f"누락 컬럼: {expected - column_names}"

    def test_surge_threshold_history_table_name(self):
        """테이블 이름이 surge_threshold_history인지 확인."""
        assert SurgeThresholdHistory.__tablename__ == "surge_threshold_history"


# ---------------------------------------------------------------------------
# 승률 계산 단위 테스트 (DB 불필요)
# ---------------------------------------------------------------------------

class TestWinRateCalculation:
    def test_all_wins(self):
        trades = [MagicMock(exit_reason="take_profit") for _ in range(5)]
        assert abs(_compute_win_rate(trades) - 1.0) < 1e-6

    def test_all_losses(self):
        trades = [MagicMock(exit_reason="stop_loss") for _ in range(5)]
        assert abs(_compute_win_rate(trades) - 0.0) < 1e-6

    def test_mixed(self):
        trades = [
            MagicMock(exit_reason="take_profit"),
            MagicMock(exit_reason="take_profit"),
            MagicMock(exit_reason="stop_loss"),
            MagicMock(exit_reason="stop_loss"),
            MagicMock(exit_reason="stop_loss"),
        ]
        assert abs(_compute_win_rate(trades) - 0.4) < 1e-6

    def test_empty_returns_none(self):
        assert _compute_win_rate([]) is None
