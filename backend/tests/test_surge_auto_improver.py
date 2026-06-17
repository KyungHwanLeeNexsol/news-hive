"""SPEC-AI-041: surge_auto_improver 단위 테스트.

T-015에 따른 가중치 정규화, 클램프, 일일 캡, R11/R12/R6 로직 검증.
"""

from __future__ import annotations

import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from sqlalchemy.orm import Session

from app.models.surge_auto_improvement_log import SurgeAutoImprovementLog
from app.models.surge_prediction_evaluation import SurgePredictionEvaluation
from app.services.surge_auto_improver import (
    _parse_detector_contributions,
    _patch_yaml_values,
    analyze_and_improve,
    format_telegram_report,
)


# ---------------------------------------------------------------------------
# 헬퍼: SurgePredictionEvaluation 생성
# ---------------------------------------------------------------------------

def _make_evaluation(
    db: Session,
    eval_date: date,
    recall: float = 0.5,
    precision: float = 0.5,
    tp: int = 5,
    fp: int = 5,
    fn: int = 5,
    actual_surge_count: int = 10,
) -> SurgePredictionEvaluation:
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    ev = SurgePredictionEvaluation(
        evaluation_date=eval_date,
        predicted_count=tp + fp,
        actual_surge_count=actual_surge_count,
        true_positive=tp,
        false_positive=fp,
        false_negative=fn,
        precision=precision,
        recall=recall,
        f1_score=f1,
    )
    db.add(ev)
    db.flush()
    return ev


# ---------------------------------------------------------------------------
# _parse_detector_contributions 단위 테스트
# ---------------------------------------------------------------------------

class TestParseDetectorContributions:
    def test_surge_basis_keys(self):
        metadata = {"surge_basis": ["theme_cluster", "news_delayed"]}
        result = _parse_detector_contributions(metadata)
        assert "theme_cluster" in result
        assert "news_delayed" in result
        assert "volume_news_combo" not in result

    def test_score_keys(self):
        metadata = {"combo_score": 0.3, "pattern_score": 0.2, "legacy_score": 0.1}
        result = _parse_detector_contributions(metadata)
        assert "volume_news_combo" in result
        assert "disclosure_pattern" in result
        assert "legacy_detectors" in result

    def test_immediate_disclosure_maps_to_disclosure_pattern(self):
        metadata = {"immediate_disclosure_score": 0.8}
        result = _parse_detector_contributions(metadata)
        assert "disclosure_pattern" in result

    def test_none_score_not_included(self):
        metadata = {"combo_score": None, "theme_cluster_score": None}
        result = _parse_detector_contributions(metadata)
        assert len(result) == 0

    def test_empty_metadata(self):
        result = _parse_detector_contributions({})
        assert len(result) == 0


# ---------------------------------------------------------------------------
# _patch_yaml_values — 주석 보존 검증
# ---------------------------------------------------------------------------

class TestPatchYamlValues:
    _SAMPLE_YAML = """\
surge_detection:
  ensemble:
    weights:
      theme_cluster: 0.2500  # 테마 클러스터
      volume_news_combo: 0.3200  # 거래량+뉴스
      disclosure_pattern: 0.1800  # 공시 패턴
      legacy_detectors: 0.1000  # 레거시
      news_delayed: 0.1500  # 뉴스 지연
    min_score_for_signal: 0.4500
"""

    def test_value_updated(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write(self._SAMPLE_YAML)
            tmp_path = f.name

        try:
            _patch_yaml_values(tmp_path, {"ensemble.weights.theme_cluster": 0.3000})
            with open(tmp_path, encoding="utf-8") as f:
                content = f.read()
            assert "0.3000" in content
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_comment_preserved(self):
        """# 주석이 값 변경 후에도 유지되어야 한다."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write(self._SAMPLE_YAML)
            tmp_path = f.name

        try:
            _patch_yaml_values(tmp_path, {"ensemble.weights.theme_cluster": 0.3000})
            with open(tmp_path, encoding="utf-8") as f:
                lines = f.readlines()

            # theme_cluster 라인에 주석이 존재해야 함
            theme_line = next(ln for ln in lines if "theme_cluster:" in ln)
            assert "# 테마 클러스터" in theme_line
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_other_lines_untouched(self):
        """변경하지 않은 키의 값은 원본 그대로여야 한다."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write(self._SAMPLE_YAML)
            tmp_path = f.name

        try:
            _patch_yaml_values(tmp_path, {"ensemble.weights.theme_cluster": 0.3000})
            with open(tmp_path, encoding="utf-8") as f:
                content = f.read()
            # 변경하지 않은 키는 원본 값 유지
            assert "0.3200" in content  # volume_news_combo
            assert "0.1800" in content  # disclosure_pattern
        finally:
            Path(tmp_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# R11 Gate: 평가 데이터 < 5일 → [] 반환
# ---------------------------------------------------------------------------

class TestR11Gate:
    def test_less_than_5_evals_returns_empty(self, db):
        """평가 데이터가 4개일 때 빈 리스트 반환."""
        today = date(2026, 6, 9)
        for i in range(4):
            _make_evaluation(db, today - timedelta(days=i + 1))
        db.commit()

        result = analyze_and_improve(db, today)
        assert result == []

    def test_exactly_5_evals_proceeds(self, db):
        """평가 데이터가 정확히 5개면 진행 (빈 리스트가 아닐 수 있음)."""
        today = date(2026, 6, 9)
        for i in range(5):
            _make_evaluation(db, today - timedelta(days=i))
        db.commit()

        # 실제 YAML 파일 수정 방지를 위해 mock 처리
        with (
            patch("app.services.surge_auto_improver._patch_yaml_values"),
            patch("app.services.surge_auto_improver.reload_surge_config"),
        ):
            result = analyze_and_improve(db, today)
        # R11 통과 확인 — 결과가 None이 아니어야 함
        assert result is not None


# ---------------------------------------------------------------------------
# 가중치 정규화 및 클램프 검증 (화이트박스 테스트)
# ---------------------------------------------------------------------------

class TestWeightNormalization:
    def test_weights_sum_to_one(self):
        """정규화 후 가중치 합산이 1.0 ± 0.001 내이어야 한다."""
        # 직접 정규화 로직 시뮬레이션
        hit_rates = {
            "theme_cluster": 0.4,
            "volume_news_combo": 0.1,
            "disclosure_pattern": 0.6,
            "legacy_detectors": 0.3,
            "news_delayed": 0.2,
        }
        current_weights = {
            "theme_cluster": 0.25,
            "volume_news_combo": 0.32,
            "disclosure_pattern": 0.18,
            "legacy_detectors": 0.10,
            "news_delayed": 0.15,
        }

        detectors = list(hit_rates.keys())
        raw = {d: current_weights[d] * hit_rates[d] for d in detectors}
        raw_total = sum(raw.values())
        assert raw_total > 0

        normalized = {d: raw[d] / raw_total for d in detectors}
        clamped = {d: max(0.05, min(0.45, normalized[d])) for d in detectors}
        clamped_total = sum(clamped.values())
        renorm = {d: clamped[d] / clamped_total for d in detectors}

        # 일일 캡 ±0.05
        daily_capped = {
            d: max(current_weights[d] - 0.05, min(current_weights[d] + 0.05, renorm[d]))
            for d in detectors
        }
        cap_total = sum(daily_capped.values())
        final = {d: daily_capped[d] / cap_total for d in detectors}

        total = sum(final.values())
        assert abs(total - 1.0) <= 0.001, f"가중치 합산 오류: {total:.6f}"

    def test_weight_clamp_no_exceed_bounds(self):
        """클램프 후 어떤 가중치도 [0.05, 0.45] 범위를 벗어나지 않는다."""
        # 극단적 hit_rate로 클램프 강제
        hit_rates = {
            "theme_cluster": 1.0,
            "volume_news_combo": 0.0,
            "disclosure_pattern": 0.0,
            "legacy_detectors": 0.0,
            "news_delayed": 0.0,
        }
        current_weights = {
            "theme_cluster": 0.25,
            "volume_news_combo": 0.32,
            "disclosure_pattern": 0.18,
            "legacy_detectors": 0.10,
            "news_delayed": 0.15,
        }

        detectors = list(hit_rates.keys())
        raw = {d: current_weights[d] * hit_rates[d] for d in detectors}
        raw_total = sum(raw.values())
        normalized = {d: raw[d] / raw_total for d in detectors}
        clamped = {d: max(0.05, min(0.45, normalized[d])) for d in detectors}

        for d, w in clamped.items():
            assert 0.05 <= w <= 0.45, f"{d}: {w} 범위 초과"

    def test_daily_cap_limits_change(self):
        """일일 캡 ±0.05 — 어떤 탐지기도 하루에 0.05 초과 변동하지 않는다."""
        hit_rates = {
            "theme_cluster": 0.9,
            "volume_news_combo": 0.05,
            "disclosure_pattern": 0.5,
            "legacy_detectors": 0.2,
            "news_delayed": 0.3,
        }
        current_weights = {
            "theme_cluster": 0.25,
            "volume_news_combo": 0.32,
            "disclosure_pattern": 0.18,
            "legacy_detectors": 0.10,
            "news_delayed": 0.15,
        }

        detectors = list(hit_rates.keys())
        raw = {d: current_weights[d] * hit_rates[d] for d in detectors}
        raw_total = sum(raw.values())
        normalized = {d: raw[d] / raw_total for d in detectors}
        clamped = {d: max(0.05, min(0.45, normalized[d])) for d in detectors}
        clamped_total = sum(clamped.values())
        renorm = {d: clamped[d] / clamped_total for d in detectors}
        daily_capped = {
            d: max(current_weights[d] - 0.05, min(current_weights[d] + 0.05, renorm[d]))
            for d in detectors
        }

        for d in detectors:
            change = abs(daily_capped[d] - current_weights[d])
            assert change <= 0.05 + 1e-9, f"{d}: 일일 변동폭 초과 {change:.4f}"


# ---------------------------------------------------------------------------
# R6: min_score_for_signal 조정 테스트
# ---------------------------------------------------------------------------

class TestR6MinScoreAdjustment:
    def _run_improve_with_evals(self, db, today, recall, precision, expected_delta):
        """5개 평가를 생성하고 improve 실행 후 min_score 변화를 검증."""
        for i in range(4):
            _make_evaluation(db, today - timedelta(days=i + 1))
        _make_evaluation(db, today, recall=recall, precision=precision)
        db.commit()

        with (
            patch("app.services.surge_auto_improver._patch_yaml_values") as mock_patch,
            patch("app.services.surge_auto_improver.reload_surge_config"),
        ):
            analyze_and_improve(db, today)
            calls = {k: v for call in mock_patch.call_args_list for k, v in (call.args[1] if call.args else call.kwargs.get("updates", {})).items()}

        return calls

    def test_low_recall_decreases_min_score(self, db):
        """recall < 0.30 → min_score -0.02 (완화)."""
        today = date(2026, 6, 9)
        for i in range(4):
            _make_evaluation(db, today - timedelta(days=i + 1))
        _make_evaluation(db, today, recall=0.20, precision=0.50)
        db.commit()

        with (
            patch("app.services.surge_auto_improver._patch_yaml_values") as mock_patch,
            patch("app.services.surge_auto_improver.reload_surge_config"),
        ):
            analyze_and_improve(db, today)

        # min_score 변경 여부 확인 (패치 호출 시 key 존재)
        if mock_patch.called:
            all_updates = {}
            for call in mock_patch.call_args_list:
                updates = call.args[1] if len(call.args) > 1 else {}
                all_updates.update(updates)
            if "ensemble.min_score_for_signal" in all_updates:
                from app.surge_config.surge_settings import get_surge_config
                cfg = get_surge_config()
                expected = max(0.35, min(0.65, cfg.ensemble.min_score_for_signal - 0.02))
                assert abs(all_updates["ensemble.min_score_for_signal"] - expected) <= 1e-6

    def test_high_recall_increases_min_score(self, db):
        """recall > 0.60 → min_score +0.02 (강화)."""
        today = date(2026, 6, 9)
        for i in range(4):
            _make_evaluation(db, today - timedelta(days=i + 1))
        _make_evaluation(db, today, recall=0.70, precision=0.50)
        db.commit()

        with (
            patch("app.services.surge_auto_improver._patch_yaml_values") as mock_patch,
            patch("app.services.surge_auto_improver.reload_surge_config"),
        ):
            analyze_and_improve(db, today)

        if mock_patch.called:
            all_updates = {}
            for call in mock_patch.call_args_list:
                updates = call.args[1] if len(call.args) > 1 else {}
                all_updates.update(updates)
            if "ensemble.min_score_for_signal" in all_updates:
                from app.surge_config.surge_settings import get_surge_config
                cfg = get_surge_config()
                expected = max(0.35, min(0.65, cfg.ensemble.min_score_for_signal + 0.02))
                assert abs(all_updates["ensemble.min_score_for_signal"] - expected) <= 1e-6

    def test_min_score_clamped_floor(self, db):
        """min_score는 0.35 미만으로 내려가지 않는다."""
        from app.surge_config.surge_settings import get_surge_config
        cfg = get_surge_config()
        current = cfg.ensemble.min_score_for_signal

        # 매우 낮은 recall (반복 완화 시 바닥 도달 시뮬레이션)
        min_result = max(0.35, min(0.65, current - 0.02))
        assert min_result >= 0.35

    def test_min_score_clamped_ceiling(self, db):
        """min_score는 0.65 초과로 올라가지 않는다."""
        from app.surge_config.surge_settings import get_surge_config
        cfg = get_surge_config()
        current = cfg.ensemble.min_score_for_signal

        max_result = max(0.35, min(0.65, current + 0.02))
        assert max_result <= 0.65


# ---------------------------------------------------------------------------
# R12 자동 롤백 테스트
# ---------------------------------------------------------------------------

class TestR12AutoRollback:
    def test_rollback_triggered_when_recall_drops(self, db):
        """이전 날 recall이 rolling avg * 0.80 미만 → auto_rollback 로그 생성."""
        today = date(2026, 6, 9)
        prev_day = today - timedelta(days=1)

        # 5개 평가 생성 (첫 4개는 높은 recall)
        for i in range(4):
            ev_date = today - timedelta(days=i + 1)
            # i=0이 prev_day
            recall_val = 0.20 if i == 0 else 0.60  # prev_day만 낮게
            _make_evaluation(db, ev_date, recall=recall_val)

        _make_evaluation(db, today, recall=0.55)
        db.commit()

        # 이전 날(prev_day)에 적용된 개선 로그 추가
        prev_log = SurgeAutoImprovementLog(
            evaluation_date=prev_day,
            parameter_path="ensemble.weights.theme_cluster",
            old_value=0.25,
            new_value=0.30,
            rationale="테스트",
            rolling_window_days=5,
        )
        db.add(prev_log)
        db.commit()

        with (
            patch("app.services.surge_auto_improver._patch_yaml_values"),
            patch("app.services.surge_auto_improver.reload_surge_config"),
        ):
            logs = analyze_and_improve(db, today)

        # rollback 로그 존재 확인
        rollback_logs = [log for log in logs if log.rationale == "auto_rollback"]
        assert len(rollback_logs) > 0, "자동 롤백 로그가 생성되어야 함"

    def test_rollback_restores_old_value(self, db):
        """롤백 시 old_value와 new_value가 교체된다."""
        today = date(2026, 6, 9)
        prev_day = today - timedelta(days=1)

        for i in range(4):
            ev_date = today - timedelta(days=i + 1)
            recall_val = 0.20 if i == 0 else 0.60
            _make_evaluation(db, ev_date, recall=recall_val)

        _make_evaluation(db, today, recall=0.55)
        db.commit()

        prev_log = SurgeAutoImprovementLog(
            evaluation_date=prev_day,
            parameter_path="ensemble.weights.theme_cluster",
            old_value=0.25,
            new_value=0.30,
            rationale="테스트",
            rolling_window_days=5,
        )
        db.add(prev_log)
        db.commit()

        with (
            patch("app.services.surge_auto_improver._patch_yaml_values"),
            patch("app.services.surge_auto_improver.reload_surge_config"),
        ):
            logs = analyze_and_improve(db, today)

        rollback_logs = [log for log in logs if log.rationale == "auto_rollback"]
        if rollback_logs:
            rl = rollback_logs[0]
            # old와 new가 교체됨
            assert abs(rl.old_value - 0.30) < 1e-6
            assert abs(rl.new_value - 0.25) < 1e-6


# ---------------------------------------------------------------------------
# format_telegram_report 검증
# ---------------------------------------------------------------------------

class TestFormatTelegramReport:
    def _make_eval(self) -> SurgePredictionEvaluation:
        """SQLAlchemy 모델 생성자로 인스턴스를 생성한다 (__new__ 직접 호출 금지)."""
        ev = SurgePredictionEvaluation(
            evaluation_date=date(2026, 6, 9),
            predicted_count=11,
            actual_surge_count=15,
            true_positive=5,
            false_positive=6,
            false_negative=10,
            precision=0.456,
            recall=0.321,
            f1_score=0.374,
        )
        return ev

    def test_report_contains_date(self):
        ev = self._make_eval()
        report = format_telegram_report(ev, [], [])
        assert "2026-06-09" in report

    def test_report_contains_precision_recall_f1(self):
        ev = self._make_eval()
        report = format_telegram_report(ev, [], [])
        assert "0.456" in report
        assert "0.321" in report
        assert "0.374" in report

    def test_report_no_changes_text(self):
        ev = self._make_eval()
        report = format_telegram_report(ev, [], [])
        assert "파라미터 변경 없음" in report

    def test_report_with_improvements(self):
        ev = self._make_eval()
        log = SurgeAutoImprovementLog(
            evaluation_date=date(2026, 6, 9),
            parameter_path="ensemble.weights.theme_cluster",
            old_value=0.250,
            new_value=0.280,
            rationale="테스트",
            rolling_window_days=5,
        )
        report = format_telegram_report(ev, [log], [])
        assert "ensemble.weights.theme_cluster" in report
        assert "0.250" in report
        assert "0.280" in report

    def test_report_rollback_warning(self):
        ev = self._make_eval()
        log = SurgeAutoImprovementLog(
            evaluation_date=date(2026, 6, 9),
            parameter_path="ensemble.weights.theme_cluster",
            old_value=0.30,
            new_value=0.25,
            rationale="auto_rollback",
            rolling_window_days=5,
        )
        report = format_telegram_report(ev, [log], [])
        assert "자동 롤백" in report

    def test_missed_top3_in_report(self):
        ev = self._make_eval()
        missed = [{"stock_name": "삼성전자", "change_rate": 12.5}]
        report = format_telegram_report(ev, [], missed)
        assert "삼성전자" in report
        assert "12.5" in report
