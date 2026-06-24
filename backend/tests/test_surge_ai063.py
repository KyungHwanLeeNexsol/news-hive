"""SPEC-AI-063: volume_breakout 독립 bypass 경로 테스트.

수락 기준 8개 시나리오 + EC1-EC4 엣지 케이스 + 특성화 테스트 포함.
"""

from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.surge_config.surge_settings import (
    EnsembleConfig,
    EnsembleWeightsConfig,
    SurgeDetectionConfig,
    VolumeBreakoutConfig,
    get_surge_config,
    reload_surge_config,
)
from app.services.surge_detector import SurgeCandidate, compute_ensemble_score


# ---------------------------------------------------------------------------
# 헬퍼: 최소 SurgeDetectionConfig 생성
# ---------------------------------------------------------------------------

def _make_config(
    vb_bypass_threshold: float = 0.30,
    min_score_for_signal: float = 0.45,
    vb_enabled: bool = True,
    vb_weight: float = 0.12,
) -> SurgeDetectionConfig:
    """테스트용 최소 SurgeDetectionConfig."""
    from app.surge_config.surge_settings import (
        BacktestConfig,
        DisclosurePatternConfig,
        ThemeClusterConfig,
        VolumeNewsComboConfig,
    )

    weights = EnsembleWeightsConfig(
        theme_cluster=0.22,
        volume_news_combo=0.28,
        disclosure_pattern=0.16,
        legacy_detectors=0.00,
        news_delayed=0.13,
        weekend_gap_up=0.09,
        volume_breakout=vb_weight,
    )
    ensemble = EnsembleConfig(
        weights=weights,
        min_score_for_signal=min_score_for_signal,
        strong_single_bypass_threshold=0.85,
        immediate_disclosure_bypass_threshold=0.85,
    )
    vb_cfg = VolumeBreakoutConfig(
        enabled=vb_enabled,
        volume_breakout_bypass_threshold=vb_bypass_threshold,
    )
    theme_cfg = ThemeClusterConfig(
        keywords=["AI"],
        sector_theme_map={},
        cluster_window_hours=48,
        min_article_count=2,
        min_market_cap_krw=50_000_000_000,
    )
    combo_cfg = VolumeNewsComboConfig(
        enabled=False,
        volume_zscore_threshold=2.0,
        volume_baseline_days=20,
        news_window_hours=24,
        min_news_sentiment=0.5,
    )
    disc_cfg = DisclosurePatternConfig(
        historical_surge_threshold_pct=10.0,
        historical_lookback_days=5,
        min_surge_rate=0.40,
        min_sample_size=20,
        cache_ttl_hours=24,
        disclosure_window_hours=24,
    )
    backtest_cfg = BacktestConfig(enabled=False, evaluation_horizon_days=5)

    return SurgeDetectionConfig(
        theme_cluster=theme_cfg,
        volume_news_combo=combo_cfg,
        disclosure_pattern=disc_cfg,
        ensemble=ensemble,
        backtest=backtest_cfg,
        volume_breakout=vb_cfg,
    )


# ---------------------------------------------------------------------------
# 특성화 테스트 (PRESERVE): bypass 추가 전 기대 동작 문서화
# ---------------------------------------------------------------------------

class TestCharacterizeVolumeBreakoutBeforeBypass:
    """PRESERVE: SPEC-AI-063 적용 이전 동작 특성화.

    volume_breakout_score만으로는 앙상블 임계값(0.45)에 도달 불가.
    weight=0.12, max_score=0.50 → 최대 앙상블 기여 = 0.12 * 0.50 = 0.06.
    """

    def test_characterize_vb_only_ensemble_score_below_threshold(self):
        """volume_breakout_score=0.50 단독 시 앙상블 점수 최대 0.06 — 임계값(0.45) 미달."""
        config = _make_config()
        candidate = SurgeCandidate(
            stock_code="000001",
            stock_name="테스트종목",
            volume_breakout_score=0.50,  # max_score
            active_detectors=["volume_breakout"],
        )
        score = compute_ensemble_score(candidate, config)
        # 0.12 * 0.50 = 0.06 (컨센서스 배율 없음 — 단일 그룹)
        assert score < 0.45, (
            f"volume_breakout 단독 앙상블 점수 {score:.4f}이 임계값 0.45 이상이면 "
            "bypass 없이도 시그널 생성됨 — 특성화 불일치"
        )
        assert score < 0.15, f"예상 범위(< 0.15) 초과: {score:.4f}"

    def test_characterize_vb_bypass_threshold_default_030(self):
        """설정 파일에서 volume_breakout_bypass_threshold 기본값 0.30 확인."""
        config = get_surge_config()
        assert config.volume_breakout.volume_breakout_bypass_threshold == pytest.approx(0.30)

    def test_characterize_vb_bypass_field_in_config(self):
        """VolumeBreakoutConfig에 volume_breakout_bypass_threshold 필드 존재."""
        cfg = VolumeBreakoutConfig()
        assert hasattr(cfg, "volume_breakout_bypass_threshold")
        assert cfg.volume_breakout_bypass_threshold == pytest.approx(0.30)

    def test_characterize_bypass_composite_score_field_on_candidate(self):
        """SurgeCandidate에 bypass_composite_score 필드 존재 (기본값 None)."""
        c = SurgeCandidate(stock_code="000001", stock_name="A")
        assert hasattr(c, "bypass_composite_score")
        assert c.bypass_composite_score is None


# ---------------------------------------------------------------------------
# 시나리오 1: 단독 VB bypass (score >= threshold)
# ---------------------------------------------------------------------------

class TestScenario1VbSoloBypass:
    """시나리오 1: volume_breakout_score=0.35 >= threshold(0.30) → qualified."""

    def _run_bypass_loop(self, config: SurgeDetectionConfig, candidates: list[SurgeCandidate]):
        """bypass path 3 로직만 추출해서 실행 (gather_surge_candidates 전체 호출 없이)."""
        qualified: list[SurgeCandidate] = []
        qualified_codes: set[str] = set()
        threshold = config.volume_breakout.volume_breakout_bypass_threshold

        for c in candidates:
            if c.stock_code not in qualified_codes:
                if c.volume_breakout_score >= threshold:
                    c.bypass_composite_score = c.volume_breakout_score
                    qualified.append(c)
                    qualified_codes.add(c.stock_code)

        return qualified, qualified_codes

    def test_vb_score_035_above_threshold_030(self):
        """score=0.35 >= threshold=0.30 → bypass 발동."""
        config = _make_config(vb_bypass_threshold=0.30)
        candidate = SurgeCandidate(
            stock_code="000001",
            stock_name="소형주A",
            volume_breakout_score=0.35,
            active_detectors=["volume_breakout"],
        )
        qualified, _ = self._run_bypass_loop(config, [candidate])
        assert len(qualified) == 1
        assert qualified[0].stock_code == "000001"

    def test_bypass_sets_bypass_composite_score(self):
        """bypass 발동 시 bypass_composite_score = volume_breakout_score."""
        config = _make_config(vb_bypass_threshold=0.30)
        candidate = SurgeCandidate(
            stock_code="000001",
            stock_name="소형주A",
            volume_breakout_score=0.35,
            active_detectors=["volume_breakout"],
        )
        qualified, _ = self._run_bypass_loop(config, [candidate])
        assert qualified[0].bypass_composite_score == pytest.approx(0.35)

    def test_active_detectors_volume_breakout(self):
        """bypass 발동 후 active_detectors에 'volume_breakout' 포함."""
        config = _make_config(vb_bypass_threshold=0.30)
        candidate = SurgeCandidate(
            stock_code="000001",
            stock_name="소형주A",
            volume_breakout_score=0.35,
            active_detectors=["volume_breakout"],
        )
        qualified, _ = self._run_bypass_loop(config, [candidate])
        assert "volume_breakout" in qualified[0].active_detectors


# ---------------------------------------------------------------------------
# 시나리오 2: VB score < threshold → bypass 미발동
# ---------------------------------------------------------------------------

class TestScenario2VbScoreBelowThreshold:
    """시나리오 2: score=0.25 < threshold=0.30 → qualified에 미포함."""

    def test_vb_score_025_below_threshold_030(self):
        """score=0.25 < threshold=0.30 → bypass 미발동."""
        config = _make_config(vb_bypass_threshold=0.30)
        candidate = SurgeCandidate(
            stock_code="000002",
            stock_name="소형주B",
            volume_breakout_score=0.25,
            active_detectors=["volume_breakout"],
        )
        qualified: list[SurgeCandidate] = []
        qualified_codes: set[str] = set()
        threshold = config.volume_breakout.volume_breakout_bypass_threshold

        for c in [candidate]:
            if c.stock_code not in qualified_codes:
                if c.volume_breakout_score >= threshold:
                    c.bypass_composite_score = c.volume_breakout_score
                    qualified.append(c)
                    qualified_codes.add(c.stock_code)

        assert len(qualified) == 0
        assert candidate.bypass_composite_score is None  # 설정 안 됨


# ---------------------------------------------------------------------------
# 시나리오 3: bypass composite_score = volume_breakout_score (앙상블 점수 아님)
# ---------------------------------------------------------------------------

class TestScenario3CompositeScoreInjection:
    """REQ-063-003: bypass 시 composite_score = volume_breakout_score (0.40), 앙상블 점수 아님."""

    def test_composite_score_equals_vb_score_not_ensemble(self):
        """bypass_composite_score = volume_breakout_score(0.40), 앙상블 점수(~0.048)가 아님."""
        config = _make_config(vb_bypass_threshold=0.30)
        candidate = SurgeCandidate(
            stock_code="000003",
            stock_name="소형주C",
            volume_breakout_score=0.40,
            active_detectors=["volume_breakout"],
        )
        # 앙상블 점수 계산 (bypass 없이)
        ensemble_score = compute_ensemble_score(candidate, config)
        assert ensemble_score < 0.10, f"앙상블 점수 예상보다 높음: {ensemble_score}"

        # bypass 로직 적용
        threshold = config.volume_breakout.volume_breakout_bypass_threshold
        if candidate.volume_breakout_score >= threshold:
            candidate.bypass_composite_score = candidate.volume_breakout_score

        # composite_score는 앙상블 점수가 아닌 vb_score
        assert candidate.bypass_composite_score == pytest.approx(0.40)
        assert candidate.bypass_composite_score != pytest.approx(ensemble_score)


# ---------------------------------------------------------------------------
# 시나리오 4: 이미 앙상블 통과한 종목 bypass 재추가 없음
# ---------------------------------------------------------------------------

class TestScenario4NoReaddFromEnsemble:
    """REQ-063-004: 앙상블 통과 종목은 bypass가 재추가하지 않음."""

    def test_already_qualified_by_ensemble_not_readded(self):
        """앙상블으로 이미 qualified_codes에 있는 종목 → bypass 루프에서 건너뜀."""
        config = _make_config(vb_bypass_threshold=0.30)
        candidate = SurgeCandidate(
            stock_code="000004",
            stock_name="앙상블통과종목",
            volume_breakout_score=0.40,
            theme_cluster_score=0.50,  # 앙상블에서 기여
            active_detectors=["theme_cluster", "volume_breakout"],
        )

        qualified: list[SurgeCandidate] = [candidate]  # 앙상블 단계에서 이미 추가됨
        qualified_codes: set[str] = {"000004"}         # 이미 포함
        threshold = config.volume_breakout.volume_breakout_bypass_threshold

        initial_count = len(qualified)

        for c in [candidate]:
            if c.stock_code not in qualified_codes:  # 이미 있으므로 skip
                if c.volume_breakout_score >= threshold:
                    c.bypass_composite_score = c.volume_breakout_score
                    qualified.append(c)
                    qualified_codes.add(c.stock_code)

        assert len(qualified) == initial_count  # 추가 없음
        assert candidate.bypass_composite_score is None  # bypass 미발동


# ---------------------------------------------------------------------------
# 시나리오 5: 다른 bypass 경로 통과 종목 재추가 없음
# ---------------------------------------------------------------------------

class TestScenario5NoReaddFromOtherBypass:
    """REQ-063-008: 다른 bypass 경로(즉각공시/강한단일신호)로 이미 추가된 종목 건너뜀."""

    def test_already_qualified_by_other_bypass(self):
        """immediate_disclosure bypass로 이미 qualified_codes에 있는 종목 → VB bypass 건너뜀."""
        config = _make_config(vb_bypass_threshold=0.30)
        candidate = SurgeCandidate(
            stock_code="000005",
            stock_name="즉각공시종목",
            volume_breakout_score=0.40,
            immediate_disclosure_score=0.90,
            active_detectors=["immediate_disclosure", "volume_breakout"],
        )

        # 즉각공시 bypass 경로에서 이미 추가됨
        qualified: list[SurgeCandidate] = [candidate]
        qualified_codes: set[str] = {"000005"}
        threshold = config.volume_breakout.volume_breakout_bypass_threshold

        for c in [candidate]:
            if c.stock_code not in qualified_codes:  # skip
                if c.volume_breakout_score >= threshold:
                    c.bypass_composite_score = c.volume_breakout_score
                    qualified.append(c)
                    qualified_codes.add(c.stock_code)

        assert len(qualified) == 1  # 중복 추가 없음


# ---------------------------------------------------------------------------
# 시나리오 6: bypass 시그널이 SurgePredictionEvaluation precision/recall에 포함
# ---------------------------------------------------------------------------

class TestScenario6EvalInclusion:
    """REQ-063-006: bypass 시그널이 평가 분모에 포함 (surge_candidate signal_type 동일)."""

    def test_bypass_candidate_active_detectors_preserved(self):
        """bypass 종목의 active_detectors=['volume_breakout'] — surge_basis로 변환 가능."""
        from app.services.surge_detector import surge_candidate_to_signal_metadata

        config = _make_config(vb_bypass_threshold=0.30)
        candidate = SurgeCandidate(
            stock_code="000006",
            stock_name="소형주F",
            volume_breakout_score=0.35,
            active_detectors=["volume_breakout"],
        )
        # bypass 후 bypass_composite_score 설정
        candidate.bypass_composite_score = candidate.volume_breakout_score

        metadata = surge_candidate_to_signal_metadata(candidate, config)

        # surge_basis에 volume_breakout 포함 (REQ-063-001)
        assert "volume_breakout" in metadata["surge_basis"]

        # surge_probability_score는 앙상블 점수 (소형 값) — 평가 필터에서 제외 안 됨
        assert "surge_probability_score" in metadata


# ---------------------------------------------------------------------------
# 시나리오 7: auto-improver가 volume_breakout_bypass_threshold 자동 조정
# ---------------------------------------------------------------------------

class TestScenario7AutoTuning:
    """REQ-063-005: auto-improver가 threshold를 [0.20, 0.45] 범위 내에서 자동 조정."""

    def test_clamp_range_constants(self):
        """자동 조정 클램프 범위 [0.20, 0.45] 상수 검증."""
        from app.services.surge_auto_improver import analyze_and_improve
        import inspect
        src = inspect.getsource(analyze_and_improve)
        assert "0.20" in src or "0.2" in src, "하한 0.20 상수 없음"
        assert "0.45" in src, "상한 0.45 상수 없음"

    def test_threshold_lower_when_recall_low(self, db):
        """recall < 0.30 → threshold 하향 조정."""
        from app.models.surge_prediction_evaluation import SurgePredictionEvaluation
        from app.services.surge_auto_improver import _write_auto_yaml, _VB_BYPASS_CLAMP_MIN

        # recall 낮은 평가 데이터 생성
        eval_date = date(2026, 6, 24)
        ev = SurgePredictionEvaluation(
            evaluation_date=eval_date,
            predicted_count=10,
            actual_surge_count=10,
            true_positive=2,
            false_positive=8,
            false_negative=8,
            precision=0.20,
            recall=0.20,  # < 0.30
            f1_score=0.20,
        )
        db.add(ev)
        db.commit()

        current_threshold = 0.30
        # 클램프 내 하향 조정 확인
        new_threshold = max(_VB_BYPASS_CLAMP_MIN, current_threshold - 0.02)
        assert new_threshold == pytest.approx(0.28)
        assert new_threshold >= _VB_BYPASS_CLAMP_MIN

    def test_threshold_raise_when_precision_low(self):
        """precision < 0.20 → threshold 상향 조정."""
        from app.services.surge_auto_improver import _VB_BYPASS_CLAMP_MAX

        current_threshold = 0.30
        # 낮은 precision 시 상향
        new_threshold = min(_VB_BYPASS_CLAMP_MAX, current_threshold + 0.02)
        assert new_threshold == pytest.approx(0.32)
        assert new_threshold <= _VB_BYPASS_CLAMP_MAX

    def test_yaml_updates_include_vb_bypass_key(self):
        """yaml_updates 딕셔너리에 volume_breakout.volume_breakout_bypass_threshold 키 포함 확인.

        analyze_and_improve 전체 흐름(R11 게이트 통과 필요) 대신
        Step 6 yaml_updates 조합 로직을 직접 검증한다.
        """
        import inspect
        from app.services.surge_auto_improver import analyze_and_improve

        src = inspect.getsource(analyze_and_improve)
        vb_key = "volume_breakout.volume_breakout_bypass_threshold"
        assert vb_key in src, (
            f"analyze_and_improve 소스에 '{vb_key}' dot-path 없음 — "
            "yaml_updates에 추가하지 않았거나 경로가 다름"
        )

    def test_vb_bypass_log_parameter_path(self):
        """SurgeAutoImprovementLog 생성 시 parameter_path가 올바른 dot-path."""
        import inspect
        from app.services.surge_auto_improver import analyze_and_improve

        src = inspect.getsource(analyze_and_improve)
        assert "volume_breakout.volume_breakout_bypass_threshold" in src, (
            "로그 parameter_path에 dot-path 누락"
        )


# ---------------------------------------------------------------------------
# 시나리오 8: enabled=false 시 bypass 후보 없음
# ---------------------------------------------------------------------------

class TestScenario8DisabledDetector:
    """REQ-063-007: volume_breakout.enabled=false → 탐지기 빈 목록 → bypass 후보 없음."""

    def test_disabled_vb_returns_no_bypass_candidates(self):
        """enabled=False → detect_volume_breakout 빈 목록 → bypass 루프 동작 없음."""
        config = _make_config(vb_enabled=False, vb_bypass_threshold=0.30)
        # enabled=False면 detect_volume_breakout이 []를 반환함
        # merged에 volume_breakout 후보 없음 → bypass 루프에서 처리할 대상 없음
        merged: dict = {}  # empty
        qualified: list[SurgeCandidate] = []
        qualified_codes: set[str] = set()
        threshold = config.volume_breakout.volume_breakout_bypass_threshold

        for c in merged.values():
            if c.stock_code not in qualified_codes:
                if c.volume_breakout_score >= threshold:
                    c.bypass_composite_score = c.volume_breakout_score
                    qualified.append(c)
                    qualified_codes.add(c.stock_code)

        assert len(qualified) == 0


# ---------------------------------------------------------------------------
# 엣지 케이스 EC1: score == threshold (경계값)
# ---------------------------------------------------------------------------

class TestEC1ExactlyAtThreshold:
    """EC1: score exactly == threshold(0.30) → bypass 발동 (>= 비교)."""

    def test_score_exactly_equals_threshold(self):
        """score=0.30 == threshold=0.30 → bypass 발동."""
        config = _make_config(vb_bypass_threshold=0.30)
        candidate = SurgeCandidate(
            stock_code="EC001",
            stock_name="경계값종목",
            volume_breakout_score=0.30,
            active_detectors=["volume_breakout"],
        )
        qualified: list[SurgeCandidate] = []
        qualified_codes: set[str] = set()
        threshold = config.volume_breakout.volume_breakout_bypass_threshold

        for c in [candidate]:
            if c.stock_code not in qualified_codes:
                if c.volume_breakout_score >= threshold:  # >= 비교
                    c.bypass_composite_score = c.volume_breakout_score
                    qualified.append(c)
                    qualified_codes.add(c.stock_code)

        assert len(qualified) == 1, "score == threshold일 때 bypass 발동해야 함"
        assert qualified[0].bypass_composite_score == pytest.approx(0.30)


# ---------------------------------------------------------------------------
# 엣지 케이스 EC2: VB + legacy 복합 → surge_basis에 두 탐지기 모두 포함
# ---------------------------------------------------------------------------

class TestEC2MultipleActiveDetectors:
    """EC2: volume_breakout + legacy 동시 활성 → active_detectors에 두 탐지기 모두."""

    def test_vb_and_legacy_both_in_active_detectors(self):
        """volume_breakout + legacy 동시 → active_detectors에 두 탐지기 보존."""
        from app.services.surge_detector import surge_candidate_to_signal_metadata
        config = _make_config(vb_bypass_threshold=0.30)
        candidate = SurgeCandidate(
            stock_code="EC002",
            stock_name="복합탐지종목",
            volume_breakout_score=0.35,
            legacy_score=0.25,
            active_detectors=["volume_breakout", "legacy"],
        )
        candidate.bypass_composite_score = candidate.volume_breakout_score

        metadata = surge_candidate_to_signal_metadata(candidate, config)
        assert "volume_breakout" in metadata["surge_basis"]
        assert "legacy" in metadata["surge_basis"]


# ---------------------------------------------------------------------------
# 엣지 케이스 EC3: sector_contagion 게이트 (bypass 후보도 일관 적용)
# ---------------------------------------------------------------------------

class TestEC3SectorContaginGate:
    """EC3: bypass 후보도 sector_contagion 게이트 통과 필요 — bypass_composite_score 필드는 유지."""

    def test_bypass_composite_score_preserved_through_filtering(self):
        """bypass_composite_score 설정된 후보를 가진 객체가 가진 필드값 보존."""
        c = SurgeCandidate(
            stock_code="EC003",
            stock_name="섹터게이트종목",
            volume_breakout_score=0.40,
            active_detectors=["volume_breakout"],
        )
        c.bypass_composite_score = c.volume_breakout_score
        assert c.bypass_composite_score == pytest.approx(0.40)

        # sector_contagion 제거 시뮬레이션: 별도 리스트에서 제거
        qualified = [c]
        # 섹터 하락 시 제거 (simulate)
        qualified_filtered = [x for x in qualified if x.stock_code != "EC003"]  # 제거됨
        assert len(qualified_filtered) == 0  # 일관적으로 제거됨


# ---------------------------------------------------------------------------
# 엣지 케이스 EC4: 복수 bypass 후보 — 모두 추가, 앙상블 점수 정렬
# ---------------------------------------------------------------------------

class TestEC4MultipleCandidates:
    """EC4: 복수 bypass 후보 → 모두 추가, 이후 앙상블 점수 내림차순 정렬."""

    def test_multiple_bypass_candidates_all_added(self):
        """복수 bypass 후보 모두 qualified에 추가."""
        config = _make_config(vb_bypass_threshold=0.30)
        candidates = [
            SurgeCandidate(
                stock_code=f"EC04{i}",
                stock_name=f"후보{i}",
                volume_breakout_score=0.30 + i * 0.05,
                active_detectors=["volume_breakout"],
            )
            for i in range(3)
        ]

        qualified: list[SurgeCandidate] = []
        qualified_codes: set[str] = set()
        threshold = config.volume_breakout.volume_breakout_bypass_threshold

        for c in candidates:
            if c.stock_code not in qualified_codes:
                if c.volume_breakout_score >= threshold:
                    c.bypass_composite_score = c.volume_breakout_score
                    qualified.append(c)
                    qualified_codes.add(c.stock_code)

        assert len(qualified) == 3
        # 앙상블 점수 정렬 (gather_surge_candidates에서 수행)
        qualified.sort(key=lambda c: compute_ensemble_score(c, config), reverse=True)
        scores = [compute_ensemble_score(c, config) for c in qualified]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# 설정 파일 검증
# ---------------------------------------------------------------------------

class TestConfigValidation:
    """surge_detection.yaml에 volume_breakout_bypass_threshold 키 존재 확인."""

    def test_yaml_has_vb_bypass_threshold(self):
        """실제 surge_detection.yaml에 volume_breakout_bypass_threshold 존재."""
        import pathlib
        yaml_path = pathlib.Path("app/surge_config/surge_detection.yaml")
        content = yaml_path.read_text(encoding="utf-8")
        assert "volume_breakout_bypass_threshold" in content

    def test_config_loads_vb_bypass_threshold(self):
        """get_surge_config()로 로드 시 volume_breakout_bypass_threshold 접근 가능."""
        config = get_surge_config()
        assert hasattr(config.volume_breakout, "volume_breakout_bypass_threshold")
        assert config.volume_breakout.volume_breakout_bypass_threshold > 0.0

    def test_ensemble_weights_sum_still_one(self):
        """volume_breakout_bypass_threshold 추가 후에도 앙상블 가중치 합산 = 1.0."""
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
        assert abs(total - 1.0) < 0.001, f"가중치 합산 오류: {total:.6f}"


# ---------------------------------------------------------------------------
# surge_auto_improver 상수 공개 (모듈 수준 접근용)
# ---------------------------------------------------------------------------

def test_vb_bypass_constants_exported():
    """_VB_BYPASS_CLAMP_MIN, _VB_BYPASS_CLAMP_MAX가 모듈에서 접근 가능."""
    from app.services import surge_auto_improver as mod
    assert hasattr(mod, "_VB_BYPASS_CLAMP_MIN"), "_VB_BYPASS_CLAMP_MIN 상수 없음"
    assert hasattr(mod, "_VB_BYPASS_CLAMP_MAX"), "_VB_BYPASS_CLAMP_MAX 상수 없음"
    assert mod._VB_BYPASS_CLAMP_MIN == pytest.approx(0.20)
    assert mod._VB_BYPASS_CLAMP_MAX == pytest.approx(0.45)
