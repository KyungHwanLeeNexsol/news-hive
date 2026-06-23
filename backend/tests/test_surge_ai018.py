"""SPEC-AI-018: 급등예측 신호 품질 개선 — 특성화 테스트 및 검증 테스트.

특성화 테스트(Characterization Tests): 구현 전 현재 동작을 문서화한다.
IMPROVE 단계 후 추가된 검증 테스트들은 SPEC-AI-018 요구사항을 확인한다.
"""

from __future__ import annotations

import pytest

from app.surge_config.surge_settings import get_surge_config
import app.surge_config.surge_settings as _settings_module


# ---------------------------------------------------------------------------
# 헬퍼: 싱글턴 캐시를 리셋하여 YAML에서 새로 로드하도록 한다
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_config_singleton():
    """각 테스트 전후로 config 싱글턴을 초기화한다."""
    _settings_module._config_singleton = None
    yield
    _settings_module._config_singleton = None


# ===========================================================================
# PRESERVE: 특성화 테스트 (구현 전 현재 동작 문서화)
# ===========================================================================

class TestCharacterizeCurrentWeights:
    """특성화: 현재 앙상블 가중치 합산이 1.0이어야 한다."""

    def test_current_ensemble_weights_sum(self):
        """현재 가중치 합산 = 1.0 (±0.001). Pydantic 검증이 이를 보장한다.
        volume_breakout(0.12) 추가 → 7개 탐지기 합산.
        """
        config = get_surge_config()
        w = config.ensemble.weights
        total = (
            w.theme_cluster
            + w.volume_news_combo
            + w.disclosure_pattern
            + w.legacy_detectors
            + w.news_delayed
            + w.weekend_gap_up
            + w.volume_breakout
        )
        assert abs(total - 1.0) < 0.001


class TestCharacterizeCurrentThresholds:
    """특성화: 현재 bypass 임계값 문서화 (IMPROVE 후 변경됨)."""

    def test_current_strong_bypass_threshold_is_085(self):
        """IMPROVE Phase 1 후: strong_single_bypass_threshold == 0.85."""
        config = get_surge_config()
        # Phase 1 이후 0.72 → 0.85
        assert config.ensemble.strong_single_bypass_threshold == pytest.approx(0.85)

    def test_immediate_disclosure_bypass_threshold_exists(self):
        """IMPROVE Phase 1 후: immediate_disclosure_bypass_threshold 필드 존재."""
        config = get_surge_config()
        assert hasattr(config.ensemble, "immediate_disclosure_bypass_threshold")
        assert config.ensemble.immediate_disclosure_bypass_threshold == pytest.approx(0.85)


class TestCharacterizeComputeEnsembleScore:
    """특성화: compute_ensemble_score 현재 동작."""

    def test_ensemble_score_single_active_detector(self):
        """단일 탐지기만 활성 → multiplier=1.00 적용."""
        from app.services.surge_detector import SurgeCandidate, compute_ensemble_score

        candidate = SurgeCandidate(stock_code="000001", stock_name="테스트")
        candidate.theme_cluster_score = 0.80
        candidate.combo_score = 0.0
        candidate.pattern_score = 0.0
        candidate.immediate_disclosure_score = 0.0
        candidate.legacy_score = 0.0

        config = get_surge_config()
        score = compute_ensemble_score(candidate, config)
        # theme_cluster 가중치 * 0.80 * 1.00 (단일 그룹만 활성)
        assert score > 0.0
        assert score <= 1.0

    def test_ensemble_score_capped_at_one(self):
        """앙상블 점수는 최대 1.0을 초과하지 않는다."""
        from app.services.surge_detector import SurgeCandidate, compute_ensemble_score

        candidate = SurgeCandidate(stock_code="000002", stock_name="테스트2")
        candidate.theme_cluster_score = 1.0
        candidate.combo_score = 1.0
        candidate.pattern_score = 1.0
        candidate.immediate_disclosure_score = 1.0
        candidate.legacy_score = 1.0

        config = get_surge_config()
        score = compute_ensemble_score(candidate, config)
        assert score <= 1.0


# ===========================================================================
# IMPROVE 검증: Phase 1 — 설정 조정
# ===========================================================================

class TestPhase1ConfigChanges:
    """Phase 1: 설정 조정 검증 (REQ-AI018-001~004)."""

    def test_new_weights_sum_to_one(self):
        """새 가중치 합계 = 1.00 (volume_breakout 0.12 신규 추가 → 7개 탐지기 합산)."""
        config = get_surge_config()
        w = config.ensemble.weights
        total = (
            w.theme_cluster
            + w.volume_news_combo
            + w.disclosure_pattern
            + w.legacy_detectors
            + w.news_delayed
            + w.weekend_gap_up
            + w.volume_breakout
        )
        assert abs(total - 1.0) < 0.001

    def test_theme_cluster_weight_is_022(self):
        """theme_cluster 가중치 = 0.22 (volume_breakout 0.12 추가로 재조정: 0.25→0.22)."""
        config = get_surge_config()
        assert config.ensemble.weights.theme_cluster == pytest.approx(0.22)

    def test_legacy_detectors_weight_is_zero(self):
        """legacy_detectors 가중치 = 0.00 (SPEC-AI-050: 0.10→0.00)."""
        config = get_surge_config()
        assert config.ensemble.weights.legacy_detectors == pytest.approx(0.00)

    def test_volume_news_combo_weight_is_028(self):
        """volume_news_combo 가중치 = 0.28 (volume_breakout 추가로 재조정: 0.32→0.28)."""
        config = get_surge_config()
        assert config.ensemble.weights.volume_news_combo == pytest.approx(0.28)

    def test_disclosure_pattern_weight_is_016(self):
        """disclosure_pattern 가중치 = 0.16 (volume_breakout 추가로 재조정: 0.18→0.16)."""
        config = get_surge_config()
        assert config.ensemble.weights.disclosure_pattern == pytest.approx(0.16)

    def test_bypass_thresholds_raised_to_085(self):
        """bypass 임계값 모두 0.85로 상향 (REQ-AI018-001, 002)."""
        config = get_surge_config()
        assert config.ensemble.strong_single_bypass_threshold == pytest.approx(0.85)
        assert config.ensemble.immediate_disclosure_bypass_threshold == pytest.approx(0.85)

    def test_min_news_sentiment_raised_to_05(self):
        """min_news_sentiment = 0.5 (REQ-AI018-003: 0.3→0.5)."""
        config = get_surge_config()
        assert config.volume_news_combo.min_news_sentiment == pytest.approx(0.5)

    def test_regime_thresholds_unchanged(self):
        """레짐별 임계값 확인 (BULL=0.38, SIDEWAYS=0.45, BEAR=0.42).
        2026-06-05: BEAR 0.52→0.42, SIDEWAYS 0.50→0.45 완화 — BEAR 4일 탐지 0건 문제 수정.
        """
        config = get_surge_config()
        assert config.ensemble.regime_thresholds.get("BULL") == pytest.approx(0.38)
        assert config.ensemble.regime_thresholds.get("SIDEWAYS") == pytest.approx(0.45)
        assert config.ensemble.regime_thresholds.get("BEAR") == pytest.approx(0.42)

    def test_consensus_multipliers_unchanged(self):
        """컨센서스 배율 변경 없음 (1.30 / 1.55)."""
        config = get_surge_config()
        assert config.ensemble.consensus_multiplier_two == pytest.approx(1.30)
        assert config.ensemble.consensus_multiplier_three_plus == pytest.approx(1.55)

    def test_immediate_bypass_threshold_from_config_not_hardcoded(self):
        """surge_detector에서 _IMMEDIATE_BYPASS_THRESHOLD 하드코딩이 제거됐는지 확인 (REQ-AI018-001)."""
        import pathlib

        src = pathlib.Path("app/services/surge_detector.py").read_text(encoding="utf-8")
        # 하드코딩 0.70 패턴 없어야 함
        assert "_IMMEDIATE_BYPASS_THRESHOLD = 0.70" not in src
        assert "_IMMEDIATE_BYPASS_THRESHOLD = 0.7" not in src


# ===========================================================================
# IMPROVE 검증: Phase 2 — 최근 급등 페널티
# ===========================================================================

class TestPhase2RecentSurgePenalty:
    """Phase 2: 최근 급등 페널티 검증 (REQ-AI018-005)."""

    def test_recent_surge_penalty_high(self):
        """price_5d_trend > 20.0% → score * 0.6."""
        from app.services.surge_detector import _recent_surge_penalty

        result = _recent_surge_penalty(0.80, 25.0)
        assert result == pytest.approx(0.80 * 0.6)

    def test_recent_surge_penalty_high_boundary(self):
        """price_5d_trend = 20.01% (20% 초과) → score * 0.6."""
        from app.services.surge_detector import _recent_surge_penalty

        result = _recent_surge_penalty(1.0, 20.01)
        assert result == pytest.approx(1.0 * 0.6)

    def test_recent_surge_penalty_medium(self):
        """12% < price_5d_trend <= 20% → score * 0.8."""
        from app.services.surge_detector import _recent_surge_penalty

        result = _recent_surge_penalty(0.80, 15.0)
        assert result == pytest.approx(0.80 * 0.8)

    def test_recent_surge_penalty_medium_boundary(self):
        """price_5d_trend = 12.01% (12% 초과 20% 이하) → score * 0.8."""
        from app.services.surge_detector import _recent_surge_penalty

        result = _recent_surge_penalty(0.50, 12.01)
        assert result == pytest.approx(0.50 * 0.8)

    def test_recent_surge_penalty_no_penalty(self):
        """price_5d_trend <= 12% → 페널티 없음."""
        from app.services.surge_detector import _recent_surge_penalty

        result = _recent_surge_penalty(0.80, 8.0)
        assert result == pytest.approx(0.80)

    def test_recent_surge_penalty_zero_trend(self):
        """price_5d_trend = 0% → 페널티 없음."""
        from app.services.surge_detector import _recent_surge_penalty

        result = _recent_surge_penalty(0.60, 0.0)
        assert result == pytest.approx(0.60)

    def test_recent_surge_penalty_negative_trend(self):
        """price_5d_trend < 0% → 페널티 없음."""
        from app.services.surge_detector import _recent_surge_penalty

        result = _recent_surge_penalty(0.70, -5.0)
        assert result == pytest.approx(0.70)

    def test_recent_surge_penalty_none_input(self):
        """price_5d_trend = None → 페널티 없이 원본 점수 반환."""
        from app.services.surge_detector import _recent_surge_penalty

        result = _recent_surge_penalty(0.80, None)
        assert result == pytest.approx(0.80)

    def test_recent_surge_penalty_preserves_zero_score(self):
        """score=0 → 페널티 적용해도 0."""
        from app.services.surge_detector import _recent_surge_penalty

        result = _recent_surge_penalty(0.0, 30.0)
        assert result == pytest.approx(0.0)

    def test_recent_surge_penalty_exact_boundary_20(self):
        """price_5d_trend = 20.0% (경계: 20% 초과 아님) → 0.8 페널티."""
        from app.services.surge_detector import _recent_surge_penalty

        # 20.0 은 > 20.0 이 아니므로 0.8 구간
        result = _recent_surge_penalty(0.50, 20.0)
        assert result == pytest.approx(0.50 * 0.8)

    def test_recent_surge_penalty_exact_boundary_12(self):
        """price_5d_trend = 12.0% (경계: 12% 초과 아님) → 페널티 없음."""
        from app.services.surge_detector import _recent_surge_penalty

        # 12.0 은 > 12.0 이 아니므로 페널티 없음
        result = _recent_surge_penalty(0.50, 12.0)
        assert result == pytest.approx(0.50)


# ===========================================================================
# IMPROVE 검증: Phase 3 — 밸류에이션 부적격 필터
# RETIRED by SPEC-AI-020 REQ-AI020-008:
# 이 클래스의 테스트들은 SPEC-AI-018 Phase 3 필터 적용 행위를 검증하나,
# SPEC-AI-020이 해당 필터를 전면 제거함에 따라 retire 처리.
# 필터 스키마(config schema) 보존 여부는 test_surge_ai020_characterization.py의
# TestCharacterizeAI018Phase3CurrentBehavior에서 계속 검증됨.
# ===========================================================================

@pytest.mark.skip(reason="SPEC-AI-020 REQ-AI020-008: 밸류에이션 필터 제거로 retire. "
                          "스키마 보존은 test_surge_ai020_characterization.py에서 검증.")
class TestPhase3ValuationDisqualifier:
    """Phase 3: 밸류에이션 부적격 필터 검증 (REQ-AI018-006~008).

    RETIRED: SPEC-AI-020이 해당 필터를 제거함 (REQ-AI020-001, REQ-AI020-008).
    ValuationDisqualifiersConfig 스키마 자체는 REQ-AI020-005에 의해 보존되지만
    필터 행위(per>500 제외, pbr>30 제외)는 더 이상 동작하지 않음.
    """

    def test_valuation_disqualifier_config_exists(self):
        """valuation_disqualifiers 설정 필드 존재 (REQ-AI018-006)."""
        config = get_surge_config()
        assert hasattr(config, "valuation_disqualifiers")

    def test_valuation_disqualifier_max_per(self):
        """max_per = 500.0 (REQ-AI018-007)."""
        config = get_surge_config()
        assert config.valuation_disqualifiers.max_per == pytest.approx(500.0)

    def test_valuation_disqualifier_max_pbr(self):
        """max_pbr = 30.0 (REQ-AI018-007)."""
        config = get_surge_config()
        assert config.valuation_disqualifiers.max_pbr == pytest.approx(30.0)

    def test_valuation_disqualifier_skip_if_missing(self):
        """skip_if_missing = True → 데이터 없으면 부적격 처리 안 함 (REQ-AI018-008)."""
        config = get_surge_config()
        assert config.valuation_disqualifiers.skip_if_missing is True


# ===========================================================================
# IMPROVE 검증: Phase 4 — 컨센서스 독립성 교정
# ===========================================================================

class TestPhase4ConsensusIndependence:
    """Phase 4: 컨센서스 독립성 교정 검증 (REQ-AI018-009)."""

    def test_consensus_two_news_detectors_same_group(self):
        """theme+combo 동시 활성 → news 그룹 1개 활성 → 1.00x (REQ-AI018-009).

        기존 동작: active_count=2 → 1.30x
        신규 동작: news 그룹 1개 활성 → 1.00x
        """
        from app.services.surge_detector import SurgeCandidate, compute_ensemble_score

        candidate = SurgeCandidate(stock_code="000001", stock_name="테스트")
        candidate.theme_cluster_score = 0.60
        candidate.combo_score = 0.60
        candidate.pattern_score = 0.0
        candidate.immediate_disclosure_score = 0.0
        candidate.legacy_score = 0.0

        config = get_surge_config()
        score = compute_ensemble_score(candidate, config)

        # news 그룹만 활성 → 1.00x multiplier
        # (0.22*0.60 + 0.28*0.60) * 1.00 = (0.132 + 0.168) = 0.300
        assert score == pytest.approx(0.300, abs=0.01)

    def test_consensus_news_plus_disclosure_two_groups(self):
        """theme(news) + disclosure 활성 → 2개 그룹 → 1.30x (REQ-AI018-009)."""
        from app.services.surge_detector import SurgeCandidate, compute_ensemble_score

        candidate = SurgeCandidate(stock_code="000002", stock_name="테스트2")
        candidate.theme_cluster_score = 0.60
        candidate.combo_score = 0.0
        candidate.pattern_score = 0.60
        candidate.immediate_disclosure_score = 0.0
        candidate.legacy_score = 0.0

        config = get_surge_config()
        score = compute_ensemble_score(candidate, config)

        # news(0.22*0.60) + disclosure(0.16*0.60) = 0.132 + 0.096 = 0.228 → * 1.30 = 0.2964
        assert score == pytest.approx(0.228 * 1.30, abs=0.01)

    def test_consensus_all_three_groups(self):
        """news + disclosure + technical 3개 그룹 활성 → 1.55x (REQ-AI018-009)."""
        from app.services.surge_detector import SurgeCandidate, compute_ensemble_score

        candidate = SurgeCandidate(stock_code="000003", stock_name="테스트3")
        candidate.theme_cluster_score = 0.50
        candidate.combo_score = 0.0
        candidate.pattern_score = 0.50
        candidate.immediate_disclosure_score = 0.0
        candidate.legacy_score = 0.50

        config = get_surge_config()
        score = compute_ensemble_score(candidate, config)

        # legacy_score=0.50 > 0 → technical 그룹 활성 → 3그룹 → 1.55x
        # news(0.22*0.50) + disclosure(0.16*0.50) + technical(0.00*0.50) = 0.110+0.080=0.190 → *1.55=0.2945
        assert score == pytest.approx(0.2945, abs=0.01)

    def test_consensus_combo_only_in_news_group(self):
        """combo만 활성(theme=0) → news 그룹 1개 활성 → 1.00x."""
        from app.services.surge_detector import SurgeCandidate, compute_ensemble_score

        candidate = SurgeCandidate(stock_code="000004", stock_name="테스트4")
        candidate.theme_cluster_score = 0.0
        candidate.combo_score = 0.70
        candidate.pattern_score = 0.0
        candidate.immediate_disclosure_score = 0.0
        candidate.legacy_score = 0.0

        config = get_surge_config()
        score = compute_ensemble_score(candidate, config)

        # combo만 활성 → news 그룹 1개 → 1.00x
        # (0.28*0.70) * 1.00 = 0.196
        assert score == pytest.approx(0.196, abs=0.01)

    def test_consensus_immediate_disclosure_in_disclosure_group(self):
        """immediate_disclosure만 활성 → disclosure 그룹 1개 → 1.00x."""
        from app.services.surge_detector import SurgeCandidate, compute_ensemble_score

        candidate = SurgeCandidate(stock_code="000005", stock_name="테스트5")
        candidate.theme_cluster_score = 0.0
        candidate.combo_score = 0.0
        candidate.pattern_score = 0.0
        candidate.immediate_disclosure_score = 0.80
        candidate.legacy_score = 0.0

        config = get_surge_config()
        score = compute_ensemble_score(candidate, config)

        # best_disclosure = max(0, 0.80) = 0.80
        # disclosure 그룹만 활성 → 1.00x
        # (0.16*0.80) * 1.00 = 0.128
        assert score == pytest.approx(0.128, abs=0.01)

    def test_consensus_technical_plus_news_two_groups(self):
        """legacy(technical) + theme(news) → 2개 그룹 → 1.30x."""
        from app.services.surge_detector import SurgeCandidate, compute_ensemble_score

        candidate = SurgeCandidate(stock_code="000006", stock_name="테스트6")
        candidate.theme_cluster_score = 0.50
        candidate.combo_score = 0.0
        candidate.pattern_score = 0.0
        candidate.immediate_disclosure_score = 0.0
        candidate.legacy_score = 0.50

        config = get_surge_config()
        score = compute_ensemble_score(candidate, config)

        # legacy_score=0.50 > 0 → technical 그룹 활성 → news + technical 2개 그룹 → 1.30x
        # news(0.22*0.50) + technical(0.00*0.50) = 0.110 → * 1.30 = 0.143
        assert score == pytest.approx(0.143, abs=0.01)
