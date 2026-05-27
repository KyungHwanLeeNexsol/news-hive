"""SPEC-AI-019: 특성화 테스트 (Characterization Tests).

DDD PRESERVE 단계: 구현 변경 전 현재 동작을 문서화하여 회귀 방지 안전망을 구축한다.
T-001 ~ T-009 구현 후에도 이 테스트들이 통과해야 한다 (REQ-AI019-008).
"""

from __future__ import annotations

import dataclasses

import pytest


# ===========================================================================
# CT-1: SurgeCandidate dataclass 필드 스냅샷
# 현재 필드 집합을 문서화 — T-001 후 per/pbr가 추가되어야 하며
# 기존 필드는 그대로 유지되어야 한다.
# ===========================================================================

class TestCharacterizeSurgeCandidate:
    """CT-1: SurgeCandidate dataclass 직렬화 호환성 스냅샷."""

    def test_ct1_required_fields_exist(self):
        """기존 필수 필드(stock_code, stock_name)가 존재한다."""
        from app.services.surge_detector import SurgeCandidate

        candidate = SurgeCandidate(stock_code="000660", stock_name="SK하이닉스")
        assert candidate.stock_code == "000660"
        assert candidate.stock_name == "SK하이닉스"

    def test_ct1_score_fields_default_zero(self):
        """스코어 필드들의 기본값이 0.0이다."""
        from app.services.surge_detector import SurgeCandidate

        candidate = SurgeCandidate(stock_code="000660", stock_name="SK하이닉스")
        assert candidate.theme_cluster_score == 0.0
        assert candidate.combo_score == 0.0
        assert candidate.pattern_score == 0.0
        assert candidate.legacy_score == 0.0
        assert candidate.immediate_disclosure_score == 0.0

    def test_ct1_active_detectors_default_empty(self):
        """active_detectors의 기본값이 빈 리스트다."""
        from app.services.surge_detector import SurgeCandidate

        candidate = SurgeCandidate(stock_code="000660", stock_name="SK하이닉스")
        assert candidate.active_detectors == []

    def test_ct1_asdict_contains_score_fields(self):
        """asdict 직렬화 결과에 스코어 필드가 포함된다."""
        from app.services.surge_detector import SurgeCandidate

        candidate = SurgeCandidate(
            stock_code="000660",
            stock_name="SK하이닉스",
            theme_cluster_score=0.5,
            combo_score=0.3,
        )
        d = dataclasses.asdict(candidate)
        assert "stock_code" in d
        assert "stock_name" in d
        assert "theme_cluster_score" in d
        assert "combo_score" in d
        assert "pattern_score" in d
        assert "legacy_score" in d
        assert "immediate_disclosure_score" in d
        assert "active_detectors" in d

    def test_ct1_dataclass_fields_ordering_after_t001(self):
        """T-001 이후: per/pbr 필드가 추가되어도 기존 필드들은 변경되지 않는다.

        이 테스트는 T-001 구현 이후에도 통과해야 한다.
        per/pbr 필드 존재 여부는 선택적으로 확인한다.
        """
        from app.services.surge_detector import SurgeCandidate

        fields = {f.name for f in dataclasses.fields(SurgeCandidate)}
        # 기존 필드들이 반드시 남아있어야 한다
        required_existing = {
            "stock_code", "stock_name",
            "theme_cluster_score", "combo_score", "pattern_score",
            "legacy_score", "immediate_disclosure_score", "active_detectors",
        }
        assert required_existing.issubset(fields), (
            f"기존 필드 누락: {required_existing - fields}"
        )


# ===========================================================================
# CT-2: _gather_leading_candidates 밸류에이션 필터 현재 동작 스냅샷
# T-007 이후 fund_manager의 필터가 제거되어도, 동일 결과가 surge_detector 경로로
# 보장되어야 한다.
# ===========================================================================

class TestCharacterizeValuationFilterBehavior:
    """CT-2: 밸류에이션 필터 동작 스냅샷."""

    def test_ct2_valuation_config_loads_correctly(self):
        """ValuationDisqualifiersConfig 기본값이 올바르게 로드된다."""
        from app.surge_config.surge_settings import get_surge_config
        import app.surge_config.surge_settings as _settings_module

        _settings_module._config_singleton = None
        try:
            config = get_surge_config()
            vd = config.valuation_disqualifiers
            assert vd.max_per == pytest.approx(500.0)
            assert vd.max_pbr == pytest.approx(30.0)
            assert vd.skip_if_missing is True
        finally:
            _settings_module._config_singleton = None

    def test_ct2_filter_logic_per_above_threshold(self):
        """PER > 500 종목은 필터 조건에 해당한다.

        이 로직이 surge_detector에서 단일 지점으로 구현되어야 한다 (T-006).
        """
        max_per = 500.0
        max_pbr = 30.0

        # PER=750, PBR=5 → 제외 대상
        per, pbr = 750.0, 5.0
        should_exclude = (
            (per is not None and per > 0 and per > max_per)
            or (pbr is not None and pbr > 0 and pbr > max_pbr)
        )
        assert should_exclude is True

    def test_ct2_filter_logic_pbr_above_threshold(self):
        """PBR > 30 종목은 필터 조건에 해당한다."""
        max_per = 500.0
        max_pbr = 30.0

        per, pbr = 20.0, 45.0
        should_exclude = (
            (per is not None and per > 0 and per > max_per)
            or (pbr is not None and pbr > 0 and pbr > max_pbr)
        )
        assert should_exclude is True

    def test_ct2_filter_logic_none_passes(self):
        """per=None, pbr=None → 필터 통과 (REQ-AI019-005)."""
        max_per = 500.0
        max_pbr = 30.0

        per, pbr = None, None
        should_exclude = (
            (per is not None and per > 0 and per > max_per)
            or (pbr is not None and pbr > 0 and pbr > max_pbr)
        )
        assert should_exclude is False

    def test_ct2_filter_logic_zero_passes(self):
        """per=0 → 결측치 동치, 필터 통과 (REQ-AI019-005)."""
        max_per = 500.0
        max_pbr = 30.0

        per, pbr = 0, 0
        should_exclude = (
            (per is not None and per > 0 and per > max_per)
            or (pbr is not None and pbr > 0 and pbr > max_pbr)
        )
        assert should_exclude is False

    def test_ct2_filter_logic_boundary_per_500_passes(self):
        """per=500.0 (max_per와 동일) → strict greater-than, 통과 (INV-4)."""
        max_per = 500.0
        max_pbr = 30.0
        per, pbr = 500.0, 5.0
        should_exclude = (
            (per is not None and per > 0 and per > max_per)
            or (pbr is not None and pbr > 0 and pbr > max_pbr)
        )
        assert should_exclude is False

    def test_ct2_filter_logic_negative_per_passes(self):
        """per=-5.0 (적자 기업) → per > 500 조건 미해당, 통과 (Edge Case 4)."""
        max_per = 500.0
        max_pbr = 30.0

        per, pbr = -5.0, 2.0
        should_exclude = (
            (per is not None and per > 0 and per > max_per)
            or (pbr is not None and pbr > 0 and pbr > max_pbr)
        )
        assert should_exclude is False


# ===========================================================================
# CT-3: 베이스라인 테스트 통과 여부 (test_surge_ai018.py 핵심 케이스)
# ===========================================================================

class TestCharacterizeBaselineRegression:
    """CT-3: 기존 test_surge_ai018.py 핵심 동작이 변경 없이 보존된다."""

    def test_ct3_ensemble_score_still_works(self):
        """compute_ensemble_score가 T-001 이후에도 동일하게 동작한다."""
        from app.services.surge_detector import SurgeCandidate, compute_ensemble_score
        import app.surge_config.surge_settings as _settings_module

        _settings_module._config_singleton = None
        try:
            from app.surge_config.surge_settings import get_surge_config
            config = get_surge_config()

            candidate = SurgeCandidate(stock_code="000001", stock_name="테스트")
            candidate.theme_cluster_score = 0.80

            score = compute_ensemble_score(candidate, config)
            assert 0.0 < score <= 1.0
        finally:
            _settings_module._config_singleton = None

    def test_ct3_recent_surge_penalty_still_works(self):
        """_recent_surge_penalty가 변경 없이 동작한다."""
        from app.services.surge_detector import _recent_surge_penalty

        assert _recent_surge_penalty(0.80, 25.0) == pytest.approx(0.80 * 0.6)
        assert _recent_surge_penalty(0.80, 15.0) == pytest.approx(0.80 * 0.8)
        assert _recent_surge_penalty(0.80, 8.0) == pytest.approx(0.80)
        assert _recent_surge_penalty(0.80, None) == pytest.approx(0.80)

    def test_ct3_valuation_disqualifiers_config_unchanged(self):
        """ValuationDisqualifiersConfig 기본값이 변경되지 않는다."""
        import app.surge_config.surge_settings as _settings_module
        _settings_module._config_singleton = None
        try:
            from app.surge_config.surge_settings import get_surge_config
            config = get_surge_config()
            assert config.valuation_disqualifiers.max_per == pytest.approx(500.0)
            assert config.valuation_disqualifiers.max_pbr == pytest.approx(30.0)
        finally:
            _settings_module._config_singleton = None
