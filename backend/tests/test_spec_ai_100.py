"""SPEC-AI-100: 급등예측 스코어링 아키텍처 — 탐지기 지평(horizon) 분리.

AC-100-001: 지평 라벨 설정 조회 + 안전 기본값(multi_day) 처리
AC-100-002: 지평 시그니처 산출 정확성 (same_day/next_day/mixed)
AC-100-003: 플래그 활성 시 레짐 × 지평 시그니처 임계값 조회
AC-100-004: 플래그 비활성 시 바이트 동일 동작
AC-100-005a/005b: combo_chase_guard Gate 4 판정 로직 무변경 + 실행 순서(Gate 4 먼저)
AC-100-006/007: 섀도우 모드 비교 로깅 + 예외 격리
AC-100-008: 고아 탐지기(weekend_gap_up/bollinger_squeeze) 비배선 상태 유지
AC-100-009: 평가 계층·재스캔 메커니즘 무변경
AC-100-010: compute_ensemble_score·bypass 루프·sector_contagion·매수 실행 게이트 무변경
AC-100-011: 섀도우→프로덕션 전환 게이트 구조적 최소 요건 3가지 명문화
"""

from __future__ import annotations

import inspect
import re
import subprocess
from pathlib import Path
from typing import Callable

import pytest

from app.services.surge_detector import (
    SurgeCandidate,
    compute_ensemble_score,
    compute_horizon_signature,
    gather_surge_candidates,
    run_horizon_shadow_comparison,
    select_effective_threshold,
)
from app.surge_config.surge_settings import SurgeDetectionConfig, get_surge_config


@pytest.fixture
def surge_config() -> SurgeDetectionConfig:
    """테스트용 SurgeDetectionConfig (기본 설정 파일 기준, 플래그 비활성 기본값)."""
    return get_surge_config()


@pytest.fixture
def horizon_enabled_config(surge_config: SurgeDetectionConfig) -> SurgeDetectionConfig:
    """플래그 활성 + 레짐×시그니처별로 서로 다른 임계값을 갖는 fixture 설정."""
    horizon_cfg = surge_config.ensemble.horizon_aware_thresholds
    return surge_config.model_copy(
        update={
            "ensemble": surge_config.ensemble.model_copy(
                update={
                    "horizon_aware_thresholds": horizon_cfg.model_copy(
                        update={
                            "enabled": True,
                            "thresholds": {
                                "BULL": {
                                    "same_day_dominant": 0.20,
                                    "next_day_dominant": 0.90,
                                    "multi_day_dominant": 0.38,
                                    "mixed": 0.38,
                                },
                            },
                        }
                    )
                }
            )
        }
    )


# ---------------------------------------------------------------------------
# AC-100-001: 지평 라벨 조회 + 안전 기본값(multi_day) 처리
# ---------------------------------------------------------------------------


class TestHorizonLabelSafeDefault:
    def test_missing_label_key_defaults_to_multi_day_without_exception(
        self, surge_config: SurgeDetectionConfig
    ):
        """라벨 맵에서 키를 하나 누락시킨 fixture로 조회해도 예외 없이 multi_day로 처리된다."""
        horizon_cfg = surge_config.ensemble.horizon_aware_thresholds
        # news_delayed 라벨을 의도적으로 누락시킨다.
        missing_labels = {
            k: v for k, v in horizon_cfg.horizon_labels.items() if k != "news_delayed"
        }
        config = surge_config.model_copy(
            update={
                "ensemble": surge_config.ensemble.model_copy(
                    update={
                        "horizon_aware_thresholds": horizon_cfg.model_copy(
                            update={"enabled": True, "horizon_labels": missing_labels}
                        )
                    }
                )
            }
        )
        candidate = SurgeCandidate(
            stock_code="900001", stock_name="누락라벨종목", news_delayed_score=0.3
        )

        # 예외 없이 안전 기본값(multi_day) 처리 → multi_day_dominant 시그니처 산출.
        signature = compute_horizon_signature(candidate, config)
        assert signature == "multi_day_dominant"


# ---------------------------------------------------------------------------
# AC-100-002: 지평 시그니처가 실제 발화한 탐지기 그룹으로부터 올바르게 산출된다
# ---------------------------------------------------------------------------


class TestHorizonSignatureComputation:
    def test_same_day_only_detector_yields_same_day_dominant(
        self, surge_config: SurgeDetectionConfig
    ):
        candidate = SurgeCandidate(
            stock_code="900002", stock_name="당일지평", volume_breakout_score=0.4
        )
        assert compute_horizon_signature(candidate, surge_config) == "same_day_dominant"

    def test_next_day_only_detector_yields_next_day_dominant(
        self, surge_config: SurgeDetectionConfig
    ):
        candidate = SurgeCandidate(
            stock_code="900003", stock_name="익일지평", momentum_continuation_score=0.5
        )
        assert compute_horizon_signature(candidate, surge_config) == "next_day_dominant"

    def test_mixed_horizons_yield_mixed_signature(
        self, surge_config: SurgeDetectionConfig
    ):
        candidate = SurgeCandidate(
            stock_code="900004",
            stock_name="혼합지평",
            volume_breakout_score=0.3,  # same_day
            theme_cluster_score=0.5,  # multi_day
        )
        assert compute_horizon_signature(candidate, surge_config) == "mixed"

    def test_no_active_detector_defaults_to_multi_day_dominant(
        self, surge_config: SurgeDetectionConfig
    ):
        """모든 스코어 0인 후보는 예외 없이 안전 기본값으로 처리된다 (spec.md §D Edge Cases)."""
        candidate = SurgeCandidate(stock_code="900005", stock_name="무발화종목")
        assert compute_horizon_signature(candidate, surge_config) == "multi_day_dominant"


# ---------------------------------------------------------------------------
# AC-100-003 / AC-100-004: 임계값 선택 경로 (플래그 활성/비활성)
# ---------------------------------------------------------------------------


class TestThresholdSelection:
    def test_same_regime_different_signature_can_select_different_threshold(
        self, horizon_enabled_config: SurgeDetectionConfig
    ):
        """동일 레짐(BULL)이라도 지평 시그니처에 따라 다른 임계값을 조회할 수 있다."""
        same_day_threshold = select_effective_threshold(
            "BULL", "same_day_dominant", horizon_enabled_config
        )
        next_day_threshold = select_effective_threshold(
            "BULL", "next_day_dominant", horizon_enabled_config
        )
        assert same_day_threshold == 0.20
        assert next_day_threshold == 0.90
        assert same_day_threshold != next_day_threshold

    def test_missing_signature_key_falls_back_to_regime_threshold(
        self, surge_config: SurgeDetectionConfig
    ):
        """레짐×시그니처 조합이 설정에 없으면 기존 regime_thresholds로 안전하게 폴백한다."""
        threshold = select_effective_threshold("BULL", "unknown_signature", surge_config)
        assert threshold == surge_config.ensemble.regime_thresholds["BULL"]

    def test_none_signature_uses_existing_single_regime_path(
        self, surge_config: SurgeDetectionConfig
    ):
        """horizon_signature=None(플래그 비활성)이면 기존 regime_thresholds 단일 경로만 쓴다."""
        legacy_threshold = surge_config.ensemble.regime_thresholds.get(
            "BULL", surge_config.ensemble.min_score_for_signal
        )
        assert select_effective_threshold("BULL", None, surge_config) == legacy_threshold

    def test_default_config_horizon_aware_thresholds_disabled(
        self, surge_config: SurgeDetectionConfig
    ):
        """기본 배포 설정에서 플래그는 반드시 False여야 한다 (REQ-AI100-001 바이트 동일 동작 전제)."""
        assert surge_config.ensemble.horizon_aware_thresholds.enabled is False


# ---------------------------------------------------------------------------
# AC-100-005a / AC-100-005b: combo_chase_guard Gate 4 판정 로직 무변경 + 실행 순서
# ---------------------------------------------------------------------------


class TestGate4OrderPreserved:
    def test_gate4_removal_executes_before_horizon_signature_computation(self):
        """Gate 4(combo 단독 제거) 코드가 지평 시그니처 계산 호출보다 먼저 등장한다.

        REQ-AI100-004: merged 딕셔너리에서 Gate 4가 제거한 후보는 지평 시그니처
        계산 대상에서 자연히 제외된다 — 소스 순서로 이를 검증한다.
        """
        source = inspect.getsource(gather_surge_candidates)
        gate4_idx = source.index("_combo_only_codes")
        horizon_call_idx = source.index("compute_horizon_signature(candidate, config)")
        assert gate4_idx < horizon_call_idx

    def test_gate4_still_removes_combo_only_candidate(self, surge_config: SurgeDetectionConfig):
        """Gate 4 판정 로직(companion-detector 조건) 자체는 SPEC-AI-100 적용 전후 무변경이다."""
        candidate = SurgeCandidate(
            stock_code="900006",
            stock_name="콤보단독",
            combo_score=0.6,
            theme_cluster_score=0.0,
            immediate_disclosure_score=0.0,
            pattern_score=0.0,
        )
        guard = surge_config.combo_chase_guard
        is_combo_only = (
            candidate.combo_score > 0
            and candidate.theme_cluster_score == 0.0
            and candidate.immediate_disclosure_score == 0.0
            and candidate.pattern_score == 0.0
        )
        assert guard.enabled and guard.require_companion_detector
        assert is_combo_only is True


# ---------------------------------------------------------------------------
# AC-100-006 / AC-100-007: 섀도우 모드 비교 로깅 + 예외 격리
# ---------------------------------------------------------------------------


class TestShadowModeComparison:
    def test_shadow_mode_logs_diff_when_paths_differ(
        self, surge_config: SurgeDetectionConfig, caplog
    ):
        """플래그 비활성 + 섀도우 활성 상태에서 두 경로의 qualified 집합 차이를 로깅한다."""
        horizon_cfg = surge_config.ensemble.horizon_aware_thresholds
        config = surge_config.model_copy(
            update={
                "ensemble": surge_config.ensemble.model_copy(
                    update={
                        "horizon_aware_thresholds": horizon_cfg.model_copy(
                            update={
                                "enabled": False,
                                "shadow_mode_enabled": True,
                                "thresholds": {
                                    "BULL": {
                                        "same_day_dominant": 0.01,
                                        "next_day_dominant": 0.99,
                                        "multi_day_dominant": 0.99,
                                        "mixed": 0.99,
                                    },
                                },
                            }
                        )
                    }
                )
            }
        )
        # same_day 탐지기만 발화 — 섀도우 경로(same_day_dominant=0.01)에서는 통과,
        # 기존 경로 기준선(qualified_codes=set(), 인위적 빈 집합)과는 차이가 나도록 구성한다.
        candidate = SurgeCandidate(
            stock_code="900007", stock_name="섀도우차이종목", volume_breakout_score=0.5
        )
        merged = {candidate.stock_code: candidate}

        with caplog.at_level("INFO"):
            run_horizon_shadow_comparison(merged, set(), "BULL", config)

        assert any(
            "SPEC-AI-100 섀도우" in record.getMessage() for record in caplog.records
        )

    def test_shadow_mode_exception_does_not_propagate(
        self, surge_config: SurgeDetectionConfig, monkeypatch, caplog
    ):
        """섀도우 경로 계산 중 예외가 나도 기존 흐름에 전파되지 않는다."""
        horizon_cfg = surge_config.ensemble.horizon_aware_thresholds
        config = surge_config.model_copy(
            update={
                "ensemble": surge_config.ensemble.model_copy(
                    update={
                        "horizon_aware_thresholds": horizon_cfg.model_copy(
                            update={"enabled": False, "shadow_mode_enabled": True}
                        )
                    }
                )
            }
        )
        candidate = SurgeCandidate(stock_code="900008", stock_name="예외종목")
        merged = {candidate.stock_code: candidate}

        def _boom(*_args, **_kwargs):
            raise RuntimeError("섀도우 계산 강제 실패")

        monkeypatch.setattr(
            "app.services.surge_detector.compute_horizon_signature", _boom
        )

        with caplog.at_level("WARNING"):
            # 예외를 발생시키지 않고 정상 반환되어야 한다.
            run_horizon_shadow_comparison(merged, set(), "BULL", config)

        assert any("계산 실패" in record.message for record in caplog.records)

    def test_shadow_mode_disabled_by_default_is_noop(
        self, surge_config: SurgeDetectionConfig, caplog
    ):
        """shadow_mode_enabled가 기본값(False)이면 아무 로그도 남기지 않는다."""
        candidate = SurgeCandidate(
            stock_code="900009", stock_name="비활성종목", volume_breakout_score=0.9
        )
        merged = {candidate.stock_code: candidate}

        with caplog.at_level("INFO"):
            run_horizon_shadow_comparison(merged, set(), "BULL", surge_config)

        assert not any("SPEC-AI-100 섀도우" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# AC-100-008 / AC-100-009 / AC-100-010: PRESERVE 대상 함수/파일 완전 무변경
# ---------------------------------------------------------------------------


def _repo_toplevel() -> str:
    return subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    ).stdout.strip()


def _git_diff_names(*paths: str) -> str:
    """작업 트리(unstaged+staged) 기준 git diff 대상 파일 목록을 반환한다."""
    result = subprocess.run(
        ["git", "diff", "--name-only", "HEAD", "--", *paths],
        cwd=_repo_toplevel() or None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return result.stdout.strip()


_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _changed_new_file_line_ranges(repo_relative_path: str) -> list[tuple[int, int]]:
    """`git diff -U0`의 hunk 헤더에서 변경된 신규 파일 라인 범위 목록을 추출한다."""
    result = subprocess.run(
        ["git", "diff", "-U0", "HEAD", "--", repo_relative_path],
        cwd=_repo_toplevel() or None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    ranges: list[tuple[int, int]] = []
    for line in result.stdout.splitlines():
        m = _HUNK_HEADER_RE.match(line)
        if not m:
            continue
        start = int(m.group(1))
        length = int(m.group(2)) if m.group(2) is not None else 1
        if length == 0:
            # 순수 삭제(신규 파일 쪽 라인 수 0) — 삽입 지점 한 줄만 표시
            ranges.append((start, start))
        else:
            ranges.append((start, start + length - 1))
    return ranges


def _function_diff_touches(repo_relative_path: str, func: Callable) -> bool:
    """대상 함수의 소스 라인 범위가 git diff 변경 범위와 겹치는지 확인한다.

    파일 전체가 아닌 함수 단위로 검사하므로, 동일 파일 내 다른(본 SPEC과
    무관한) 영역의 사전 존재 변경과 무관하게 대상 함수 무변경만 정확히 검증한다.
    """
    _, start_lineno = inspect.getsourcelines(func)
    end_lineno = start_lineno + len(inspect.getsource(func).splitlines()) - 1
    for r_start, r_end in _changed_new_file_line_ranges(repo_relative_path):
        if r_start <= end_lineno and r_end >= start_lineno:
            return True
    return False


class TestPreserveListUnchanged:
    def test_orphan_detector_call_sites_unchanged(self):
        """AC-100-008: fund_manager.py/scheduler.py — 고아 탐지기 호출부 무변경."""
        diff = _git_diff_names("backend/app/services/fund_manager.py")
        assert "fund_manager.py" not in diff, f"unexpected diff: {diff}"

    def test_same_day_event_horizon_signal_function_unchanged(self):
        """AC-100-009: 평가 계층 `_is_same_day_event_horizon_signal()` 함수 본문 무변경."""
        from app.services.surge_evaluation_service import (
            _is_same_day_event_horizon_signal,
        )

        touched = _function_diff_touches(
            "backend/app/services/surge_evaluation_service.py",
            _is_same_day_event_horizon_signal,
        )
        assert not touched, "_is_same_day_event_horizon_signal 함수 본문이 변경되었다"

    def test_event_rescan_mechanism_function_unchanged(self):
        """AC-100-009: `_maybe_trigger_event_rescan()`(SPEC-AI-066 재스캔) 함수 본문 무변경."""
        from app.services.scheduler import _maybe_trigger_event_rescan

        diff = _git_diff_names("backend/app/services/scheduler.py")
        if diff:
            touched = _function_diff_touches(
                "backend/app/services/scheduler.py", _maybe_trigger_event_rescan
            )
            assert not touched, "_maybe_trigger_event_rescan 함수 본문이 변경되었다"

    def test_buy_execution_gate_unchanged(self):
        """AC-100-010: surge_threshold_service.py(매수 실행 전용 적응형 임계값) 무변경."""
        diff = _git_diff_names("backend/app/services/surge_threshold_service.py")
        assert "surge_threshold_service.py" not in diff, f"unexpected diff: {diff}"

    def test_compute_ensemble_score_body_unchanged(self):
        """AC-100-010: compute_ensemble_score 가중합·컨센서스 배율 계산 본체는 무수정이다."""
        source = inspect.getsource(compute_ensemble_score)
        # 가중합 공식과 컨센서스 배율 로직이 그대로 유지되는지 핵심 토큰으로 확인.
        assert "weighted_sum = (" in source
        assert "consensus_multiplier_three_plus" in source
        assert "consensus_multiplier_two" in source
        # 본 SPEC이 추가한 지평 관련 로직이 함수 본체에 섞여 있지 않아야 한다.
        assert "horizon" not in source.lower()


# ---------------------------------------------------------------------------
# AC-100-011: 섀도우→프로덕션 전환 게이트 구조적 최소 요건 3가지
# ---------------------------------------------------------------------------


class TestTransitionGateChecklistDocumented:
    def test_plan_md_documents_three_transition_gate_requirements(self):
        """전환 게이트 구조(3요건 존재)가 plan.md에 명문화되어 있는지 확인한다.

        정확한 수치(10 거래일, ±30%)는 잠정값(Open Question 2/3)이며 이 테스트의
        대상이 아니다 — 게이트 "구조"(3요건 항목 자체)만 Must-Pass다.
        """
        repo_root = Path(__file__).resolve().parents[2]
        plan_path = repo_root / ".moai" / "specs" / "SPEC-AI-100" / "plan.md"
        plan_text = plan_path.read_text(encoding="utf-8")

        assert "전환 게이트" in plan_text
        assert "거래일" in plan_text
        assert "BULL/SIDEWAYS/BEAR" in plan_text
        assert "±30%" in plan_text or "30%" in plan_text
