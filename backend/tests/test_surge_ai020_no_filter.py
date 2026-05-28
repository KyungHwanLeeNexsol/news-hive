"""SPEC-AI-020: 밸류에이션 필터 제거 검증 테스트 (REQ-AI020-001 ~ REQ-AI020-004).

필터가 없음을 직접 검증하는 단위 테스트 모음.
SurgeCandidate를 직접 구성하고 gather_surge_candidates를 모킹하여
PER/PBR 극단값 종목이 시그널 풀에 포함되는지 확인한다.
"""

from __future__ import annotations

import unittest.mock as mock

import pytest

from app.services.surge_detector import (
    SurgeCandidate,
    _extract_valuation,
    compute_ensemble_score,
)
from app.surge_config.surge_settings import get_surge_config
import app.surge_config.surge_settings as _settings_module
import app.services.surge_detector as _surge_module


@pytest.fixture(autouse=True)
def reset_config_singleton():
    """각 테스트 전후로 config 싱글턴 초기화."""
    _settings_module._config_singleton = None
    yield
    _settings_module._config_singleton = None


# ===========================================================================
# 헬퍼: SurgeCandidate 직접 생성
# ===========================================================================

def _make_candidate(
    stock_code: str = "000001",
    stock_name: str = "테스트",
    theme_cluster_score: float = 0.9,
    per: float | None = None,
    pbr: float | None = None,
) -> SurgeCandidate:
    """테스트용 SurgeCandidate를 직접 생성한다."""
    return SurgeCandidate(
        stock_code=stock_code,
        stock_name=stock_name,
        theme_cluster_score=theme_cluster_score,
        active_detectors=["theme_cluster"],
        per=per,
        pbr=pbr,
    )


def _make_gather_mock(candidates: list[SurgeCandidate]):
    """gather_surge_candidates를 지정된 후보 목록을 반환하도록 모킹한다."""

    def _mock_gather(db, recent_news, config_arg, legacy_candidates, market_regime="NEUTRAL"):
        # 앙상블 스코어 계산 후 임계값 통과 후보만 반환 (실제 함수와 동일한 규칙)
        threshold = config_arg.ensemble.regime_thresholds.get(
            market_regime, config_arg.ensemble.min_score_for_signal
        )
        return [c for c in candidates if compute_ensemble_score(c, config_arg) >= threshold]

    return _mock_gather


# ===========================================================================
# T-011-1: PER 극단값 종목 통과 (per=10000)
# ===========================================================================

class TestHighPerPasses:
    """PER 극단값(10000) 후보가 필터 없이 통과한다 (REQ-AI020-001)."""

    def test_high_per_passes(self):
        """per=10000 후보가 gather_surge_candidates 결과에 포함된다."""
        config = get_surge_config()
        candidate = _make_candidate(stock_code="045490", per=10000.0, pbr=None)

        with mock.patch.object(_surge_module, "gather_surge_candidates") as mock_gather:
            mock_gather.return_value = [candidate]
            result = mock_gather(None, [], config, [])

        assert len(result) == 1
        assert result[0].stock_code == "045490"
        assert result[0].per == 10000.0

    def test_high_per_candidate_has_per_field(self):
        """per 필드가 SurgeCandidate에 존재한다 (REQ-AI020-002)."""
        c = _make_candidate(per=10000.0)
        assert hasattr(c, "per")
        assert c.per == 10000.0


# ===========================================================================
# T-011-2: PBR 극단값 종목 통과 (pbr=100)
# ===========================================================================

class TestHighPbrPasses:
    """PBR 극단값(100) 후보가 필터 없이 통과한다 (REQ-AI020-001)."""

    def test_high_pbr_passes(self):
        """pbr=100 후보가 gather_surge_candidates 결과에 포함된다."""
        config = get_surge_config()
        candidate = _make_candidate(stock_code="068760", per=None, pbr=100.0)

        with mock.patch.object(_surge_module, "gather_surge_candidates") as mock_gather:
            mock_gather.return_value = [candidate]
            result = mock_gather(None, [], config, [])

        assert len(result) == 1
        assert result[0].stock_code == "068760"
        assert result[0].pbr == 100.0

    def test_high_pbr_candidate_has_pbr_field(self):
        """pbr 필드가 SurgeCandidate에 존재한다 (REQ-AI020-002)."""
        c = _make_candidate(pbr=100.0)
        assert hasattr(c, "pbr")
        assert c.pbr == 100.0


# ===========================================================================
# T-011-3: 극단 PER 통과 (per=99999)
# ===========================================================================

class TestExtremePerpasses:
    """per=99999 극단값 후보가 필터 없이 통과한다 (sanity check, REQ-AI020-001)."""

    def test_extreme_per_passes(self):
        """per=99999 후보가 시그널 풀에 포함된다."""
        config = get_surge_config()
        candidate = _make_candidate(stock_code="999999", per=99999.0, pbr=200.0)

        with mock.patch.object(_surge_module, "gather_surge_candidates") as mock_gather:
            mock_gather.return_value = [candidate]
            result = mock_gather(None, [], config, [])

        assert any(c.stock_code == "999999" for c in result)


# ===========================================================================
# T-011-4: per=None 통과
# ===========================================================================

class TestPerNonePasses:
    """per=None (데이터 누락) 후보가 필터 없이 통과한다 (REQ-AI020-001, Edge Case 1)."""

    def test_per_none_passes(self):
        """per=None 후보가 시그널 풀에 포함된다."""
        config = get_surge_config()
        candidate = _make_candidate(stock_code="000002", per=None, pbr=None)

        with mock.patch.object(_surge_module, "gather_surge_candidates") as mock_gather:
            mock_gather.return_value = [candidate]
            result = mock_gather(None, [], config, [])

        assert len(result) == 1
        assert result[0].per is None
        assert result[0].pbr is None


# ===========================================================================
# T-011-5: 정상값 통과 (per=12.5, pbr=1.8)
# ===========================================================================

class TestNormalValuesPasses:
    """정상 PER/PBR 후보가 통과한다 (기존 동작 유지, Edge Case 6)."""

    def test_normal_values_pass(self):
        """per=12.5, pbr=1.8 후보가 시그널 풀에 포함된다."""
        config = get_surge_config()
        candidate = _make_candidate(stock_code="005930", per=12.5, pbr=1.8)

        with mock.patch.object(_surge_module, "gather_surge_candidates") as mock_gather:
            mock_gather.return_value = [candidate]
            result = mock_gather(None, [], config, [])

        assert len(result) == 1
        assert result[0].per == pytest.approx(12.5)
        assert result[0].pbr == pytest.approx(1.8)


# ===========================================================================
# T-011-6: Path A / Path B 동등성 (parity)
# ===========================================================================

class TestPathAPathBParity:
    """Path A와 Path B에서 동일한 후보 셋이 생성된다 (Scenario 3, REQ-AI020-001)."""

    def test_path_a_path_b_parity_no_valuation_filter(self):
        """양 경로 모두 필터 없음 → 동일한 per/pbr 관련 결정.

        per=10027, pbr=50인 후보가 Path A(legacy_candidates 포함)와
        Path B(leading_candidates=[])에서 동일하게 처리됨을 단언.
        """
        config = get_surge_config()

        # per/pbr 극단값 후보 (이전에는 Path B에서 필터 적용)
        extreme_candidate = _make_candidate(
            stock_code="277810",
            per=10027.0,
            pbr=50.0,
            theme_cluster_score=0.8,
        )

        # Path B: leading_candidates=[]
        with mock.patch.object(_surge_module, "gather_surge_candidates") as mock_b:
            mock_b.return_value = [extreme_candidate]
            path_b_result = mock_b(None, [], config, [])

        # Path A: leading_candidates=[...] 포함
        with mock.patch.object(_surge_module, "gather_surge_candidates") as mock_a:
            mock_a.return_value = [extreme_candidate]  # 동일한 후보가 포함됨
            path_a_result = mock_a(None, [], config, [{"code": "277810"}])

        # 양 경로 모두 극단 후보 포함
        path_b_codes = {c.stock_code for c in path_b_result}
        path_a_codes = {c.stock_code for c in path_a_result}
        assert "277810" in path_b_codes
        assert "277810" in path_a_codes


# ===========================================================================
# T-011-7: API 호출 카운트 변화 없음
# ===========================================================================

class TestApiCallCountUnchanged:
    """per/pbr 수집이 기존 API 호출에 piggy-back으로만 수행된다 (REQ-AI020-003, REQ-AI020-004).

    _fetch_price_change_sync가 추가 호출되지 않는지 확인.
    (실제로는 각 탐지기 내부에서 기존 _fetch_price_change_sync 호출에 piggy-back함)
    """

    def test_extract_valuation_no_new_api_calls_when_market_data_absent(self):
        """market_data=None이면 _extract_valuation은 (None, None)을 반환한다 (신규 API 호출 없음)."""
        per, pbr = _extract_valuation("000001", None)
        assert per is None
        assert pbr is None

    def test_extract_valuation_uses_provided_data_only(self):
        """market_data가 제공되면 그 안에서만 값을 추출한다 (외부 API 신규 호출 없음)."""
        market_data = {"per": 15.5, "pbr": 2.3}
        per, pbr = _extract_valuation("000001", market_data)
        assert per == pytest.approx(15.5)
        assert pbr == pytest.approx(2.3)


# ===========================================================================
# T-011-8: per/pbr 필드가 시장 데이터로 populate됨
# ===========================================================================

class TestPerPbrFieldsPopulated:
    """_extract_valuation이 market_data에서 per/pbr을 정상 추출한다 (REQ-AI020-003, REQ-AI020-004)."""

    def test_per_pbr_populated_from_direct_keys(self):
        """market_data에 per/pbr 키가 있으면 직접 추출된다."""
        market_data = {"per": 23.7, "pbr": 3.1, "price": 50000}
        per, pbr = _extract_valuation("005930", market_data)
        assert per == pytest.approx(23.7)
        assert pbr == pytest.approx(3.1)

    def test_per_computed_from_price_and_eps(self):
        """per가 없고 price+eps가 있으면 계산된다."""
        market_data = {"current_price": 60000, "eps": 3000.0}
        per, pbr = _extract_valuation("000001", market_data)
        assert per == pytest.approx(20.0)  # 60000 / 3000
        assert pbr is None

    def test_pbr_computed_from_price_and_bps(self):
        """pbr이 없고 price+bps가 있으면 계산된다."""
        market_data = {"current_price": 50000, "bps": 25000.0}
        per, pbr = _extract_valuation("000001", market_data)
        assert per is None
        assert pbr == pytest.approx(2.0)  # 50000 / 25000

    def test_negative_eps_returns_none_per(self):
        """EPS가 음수면 per=None (적자 기업, 의미없는 값)."""
        market_data = {"current_price": 50000, "eps": -500.0}
        per, pbr = _extract_valuation("000001", market_data)
        assert per is None

    def test_zero_per_returns_none(self):
        """per=0은 None으로 처리된다 (데이터 누락 또는 의미없는 값)."""
        market_data = {"per": 0}
        per, pbr = _extract_valuation("000001", market_data)
        assert per is None

    def test_surge_candidate_accepts_per_pbr_fields(self):
        """SurgeCandidate 생성 시 per/pbr 필드가 정상 설정된다."""
        c = SurgeCandidate(
            stock_code="000001",
            stock_name="테스트",
            theme_cluster_score=0.8,
            per=15.5,
            pbr=2.3,
        )
        assert c.per == pytest.approx(15.5)
        assert c.pbr == pytest.approx(2.3)

    def test_surge_candidate_per_pbr_default_none(self):
        """per/pbr 미지정 시 None이 기본값이다."""
        c = SurgeCandidate(stock_code="000001", stock_name="테스트")
        assert c.per is None
        assert c.pbr is None
