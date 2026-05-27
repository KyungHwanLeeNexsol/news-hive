"""SPEC-AI-020: 특성화 테스트 (Characterization Tests).

PRESERVE 단계 — IMPROVE 전 현재 상태를 문서화한다.

CT-A: SurgeCandidate 데이터클래스 필드 셋 베이스라인
CT-B: SPEC-AI-018 Phase 3 테스트 케이스 베이스라인 (retire/invert 대상 확인용)
CT-C: surge 전체 테스트 슈트 통과 카운트 베이스라인

참고: SPEC-AI-019는 현재 main 브랜치에 미구현 상태이므로
      per/pbr 필드, _extract_valuation 헬퍼, piggy-back 수집은
      SPEC-AI-020 IMPROVE 단계에서 함께 구현한다.
"""

from __future__ import annotations

import dataclasses

import pytest

from app.services.surge_detector import SurgeCandidate
from app.surge_config.surge_settings import get_surge_config, _config_singleton
import app.surge_config.surge_settings as _settings_module


@pytest.fixture(autouse=True)
def reset_config_singleton():
    """각 테스트 전후로 config 싱글턴 초기화."""
    _settings_module._config_singleton = None
    yield
    _settings_module._config_singleton = None


# ===========================================================================
# CT-A: SurgeCandidate 데이터클래스 필드 셋 베이스라인
# ===========================================================================

class TestCharacterizeSurgeCandidateFields:
    """CT-A: SurgeCandidate 필드 구조 문서화.

    IMPROVE T-001 전 베이스라인:
    - per, pbr 필드는 존재하지 않음 (SPEC-AI-019 미구현)
    - IMPROVE T-001 실행 후 이 클래스의 assertions 중 per/pbr 관련 부분이 변경됨
    """

    def test_surge_candidate_has_required_base_fields(self):
        """SurgeCandidate 기본 필드 셋 확인."""
        candidate = SurgeCandidate(stock_code="000001", stock_name="테스트")
        assert candidate.stock_code == "000001"
        assert candidate.stock_name == "테스트"
        assert candidate.theme_cluster_score == 0.0
        assert candidate.combo_score == 0.0
        assert candidate.pattern_score == 0.0
        assert candidate.legacy_score == 0.0
        assert candidate.immediate_disclosure_score == 0.0
        assert candidate.active_detectors == []

    def test_surge_candidate_is_dataclass(self):
        """SurgeCandidate는 dataclass이다."""
        assert dataclasses.is_dataclass(SurgeCandidate)

    def test_surge_candidate_field_names_snapshot(self):
        """필드명 스냅샷 — SPEC-AI-020 IMPROVE T-001 완료 후 per/pbr 포함."""
        fields = {f.name for f in dataclasses.fields(SurgeCandidate)}
        assert "stock_code" in fields
        assert "stock_name" in fields
        assert "theme_cluster_score" in fields
        assert "combo_score" in fields
        assert "pattern_score" in fields
        assert "legacy_score" in fields
        assert "immediate_disclosure_score" in fields
        assert "active_detectors" in fields
        # SPEC-AI-020 IMPROVE T-001 추가: per/pbr data-only observability 필드
        assert "per" in fields
        assert "pbr" in fields


# ===========================================================================
# CT-B: SPEC-AI-018 Phase 3 테스트 케이스 현재 상태 확인
# ===========================================================================

class TestCharacterizeAI018Phase3CurrentBehavior:
    """CT-B: SPEC-AI-018 Phase 3 테스트 케이스 현재 동작 문서화.

    현재 상태 (IMPROVE T-006 전):
    - valuation_disqualifiers config schema는 존재하고 로드됨
    - fund_manager.py 라인 1707-1724에 필터 블록 존재
    - 이 테스트들은 T-006 후 retire/invert 대상

    RETIRE 결정: 스키마 config 필드 자체(max_per, max_pbr, skip_if_missing)는
    SPEC-AI-020 REQ-005에 의해 schema 유지되므로 이 테스트들은
    "config schema 존재" 관점에서 여전히 유효 → 그대로 유지.
    test_surge_ai018.py의 Phase 3 클래스는 retire 처리.
    """

    def test_valuation_disqualifiers_config_schema_present(self):
        """ValuationDisqualifiersConfig 스키마가 로드됨 (schema preserved by REQ-AI020-005)."""
        config = get_surge_config()
        assert hasattr(config, "valuation_disqualifiers")
        vd = config.valuation_disqualifiers
        # 스키마 필드 존재 확인 (값이 아닌 구조를 검증)
        assert hasattr(vd, "max_per")
        assert hasattr(vd, "max_pbr")
        assert hasattr(vd, "skip_if_missing")

    def test_valuation_disqualifiers_schema_values_intact(self):
        """ValuationDisqualifiersConfig 기본값 유지 (스키마 보존 확인)."""
        config = get_surge_config()
        vd = config.valuation_disqualifiers
        # 값 확인 — SPEC-AI-020 REQ-005: schema preserved
        assert vd.max_per == pytest.approx(500.0)
        assert vd.max_pbr == pytest.approx(30.0)
        assert vd.skip_if_missing is True


# ===========================================================================
# CT-C: 전체 surge 테스트 슈트 통과 카운트 메모
# ===========================================================================

class TestCharacterizeSurgeSuiteBaseline:
    """CT-C: 전체 surge 테스트 슈트 통과 카운트 베이스라인 문서화.

    2026-05-28 UTC 베이스라인:
    - test_surge_ai018.py: 30 passed
    - test_surge_detector.py: 22 passed
    - test_surge_scoring.py: 22 passed (수정: 실제 카운트 반영됨)
    - 합계: 84 passed

    IMPROVE 완료 후 기대값:
    - Phase 3 케이스 4개 retire → test_surge_ai018.py: 26 active + 4 skipped
    - 신규 test_surge_ai020_no_filter.py: 8개 추가
    - 전체 통과: 80+ (retire된 케이스 제외)
    """

    def test_surge_candidate_instantiation_smoke(self):
        """SurgeCandidate 인스턴스 생성 스모크 테스트."""
        c = SurgeCandidate(stock_code="005930", stock_name="삼성전자")
        assert c.stock_code == "005930"
        assert c.stock_name == "삼성전자"

    def test_config_loads_without_error(self):
        """surge_detection.yaml 로드 성공 확인."""
        config = get_surge_config()
        assert config is not None
        assert hasattr(config, "ensemble")
        assert hasattr(config, "theme_cluster")
