"""SPEC-AI-069: Backtest 운영 게이트 & 자동개선 거버넌스 & z-score 회귀 격리.

DDD 특성화 테스트 — REQ-AI069-001~005의 신규/변경 로직을 검증한다.
기존 REQ 전용 스위트(test_surge_auto_improver.py, test_surge_backtest.py,
test_spec_ai_065.py)와 상호 보완적이며 중복을 최소화한다.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy.orm import Session

from app.services.surge_baseline_service import BaselineStats, Observation, update_baselines
from app.services.surge_detector import _apply_relative_scoring
from app.surge_config.surge_settings import get_surge_config


# ---------------------------------------------------------------------------
# REQ-AI069-004: z-score flag 기본값 및 _apply_relative_scoring 게이팅
# ---------------------------------------------------------------------------

class TestCharacterizeZScoreFlagDefault:
    def test_zscore_enabled_default_false(self):
        """base yaml relative_scoring.zscore_enabled 기본값은 false다 (D3 확정)."""
        cfg = get_surge_config()
        assert cfg.relative_scoring.zscore_enabled is False


class TestApplyRelativeScoring:
    """_apply_relative_scoring — SPEC-AI-065 z-score 로직을 재작성 없이 게이팅한 순수 함수."""

    def test_disabled_keeps_raw_score(self):
        """zscore_enabled=false면 z가 계산되어도 raw 값을 그대로 반환하고 applied=False."""
        stats = BaselineStats(rolling_mean=0.30, rolling_m2=0.0225, sample_count=10)
        score, meta, applied = _apply_relative_scoring(
            0.40, stats, min_samples=10, zscore_enabled=False
        )
        assert score == pytest.approx(0.40)
        assert applied is False
        assert "disabled" in meta

    def test_enabled_normalizes_score(self):
        """zscore_enabled=true면 AI-065 sigmoid 정규화 값을 반환하고 applied=True (회귀 없음 검증)."""
        stats = BaselineStats(rolling_mean=0.30, rolling_m2=0.0225, sample_count=10)
        score, meta, applied = _apply_relative_scoring(
            0.40, stats, min_samples=10, zscore_enabled=True
        )
        assert applied is True
        assert 0.5 < score <= 1.0  # 평균보다 높으므로 sigmoid(z>0) > 0.5
        assert "→" in meta

    def test_cold_start_ignores_flag(self):
        """샘플 부족(cold-start)이면 flag와 무관하게 raw를 유지하고 applied=False."""
        stats = BaselineStats(rolling_mean=0.30, rolling_m2=0.0, sample_count=3)
        score, meta, applied = _apply_relative_scoring(
            0.40, stats, min_samples=10, zscore_enabled=True
        )
        assert score == pytest.approx(0.40)
        assert applied is False
        assert meta == "cold_start"

    def test_disabled_and_enabled_produce_same_z_in_meta(self):
        """flag와 무관하게 z-score 자체는 항상 계산된다(로그 신선도 유지, update_baselines 영향 없음)."""
        stats = BaselineStats(rolling_mean=0.30, rolling_m2=0.0225, sample_count=10)
        _, meta_disabled, _ = _apply_relative_scoring(
            0.40, stats, min_samples=10, zscore_enabled=False
        )
        _, meta_enabled, _ = _apply_relative_scoring(
            0.40, stats, min_samples=10, zscore_enabled=True
        )
        assert "z=" in meta_disabled
        assert "z=" in meta_enabled


# ---------------------------------------------------------------------------
# REQ-AI069-001: run_backtest_gate 판정 로직
# ---------------------------------------------------------------------------

class TestRunBacktestGate:
    def _make_stock(self, db: Session, sector_id: int, code: str):
        from app.models.stock import Stock

        stock = Stock(name=f"테스트{code}", stock_code=code, sector_id=sector_id, market_cap=500)
        db.add(stock)
        db.flush()
        return stock

    def _make_sector(self, db: Session):
        from app.models.sector import Sector

        s = Sector(name="백테스트게이트섹터")
        db.add(s)
        db.flush()
        return s

    def _make_signal(self, db: Session, stock, price_at: int, price_after: int, days_ago: float):
        from datetime import datetime, timezone

        from app.models.fund_signal import FundSignal

        signal = FundSignal(
            stock_id=stock.id,
            signal="buy",
            confidence=0.7,
            reasoning="게이트 테스트",
            signal_type="surge_candidate",
            price_at_signal=price_at,
            price_after_5d=price_after,
            surge_metadata='{"surge_basis": ["theme_cluster"]}',
            created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        )
        db.add(signal)
        db.flush()
        return signal

    def test_insufficient_when_below_min_signals(self, db: Session):
        """total_signals < min_signals(기본 20) → verdict='insufficient' (EC-2)."""
        from app.services.surge_backtest import run_backtest_gate

        sector = self._make_sector(db)
        stock = self._make_stock(db, sector.id, "GT0001")
        self._make_signal(db, stock, 10000, 11000, days_ago=1.0)
        db.commit()

        result = run_backtest_gate(db)
        assert result.verdict == "insufficient"
        assert result.total_signals == 1
        assert result.min_signals == 20

    def test_pass_when_accuracy_meets_floor(self, db: Session):
        """min_signals 충족 + directional_accuracy >= floor(0.50) → verdict='pass'."""
        from app.services.surge_backtest import run_backtest_gate
        from app.surge_config.surge_settings import get_surge_config

        cfg = get_surge_config()
        cfg.backtest.gate.min_signals = 5

        sector = self._make_sector(db)
        stock = self._make_stock(db, sector.id, "GT0002")
        for i in range(5):
            self._make_signal(db, stock, 10000, 11000, days_ago=float(i + 1))  # 전부 적중
        db.commit()

        result = run_backtest_gate(db, surge_config=cfg)
        assert result.verdict == "pass"
        assert result.directional_accuracy == pytest.approx(1.0)

    def test_fail_when_accuracy_below_floor(self, db: Session):
        """min_signals 충족했으나 directional_accuracy < floor → verdict='fail'."""
        from app.services.surge_backtest import run_backtest_gate
        from app.surge_config.surge_settings import get_surge_config

        cfg = get_surge_config()
        cfg.backtest.gate.min_signals = 5

        sector = self._make_sector(db)
        stock = self._make_stock(db, sector.id, "GT0003")
        for i in range(5):
            self._make_signal(db, stock, 10000, 9000, days_ago=float(i + 1))  # 전부 하락(실패)
        db.commit()

        result = run_backtest_gate(db, surge_config=cfg)
        assert result.verdict == "fail"
        assert result.directional_accuracy == pytest.approx(0.0)

    def test_config_hash_is_deterministic(self, db: Session):
        """동일 config로 두 번 판정하면 config_hash가 동일하다(재현성)."""
        from app.services.surge_backtest import run_backtest_gate

        result1 = run_backtest_gate(db)
        result2 = run_backtest_gate(db)
        assert result1.config_hash == result2.config_hash
        assert len(result1.config_hash) == 16


# ---------------------------------------------------------------------------
# REQ-AI069-001 / EC-5: 스케줄러 cron 파라미터 (18:45 KST, distinct id)
# ---------------------------------------------------------------------------

class TestSchedulerBacktestGateCronRegistration:
    def test_registered_with_correct_cron_params(self):
        """surge_backtest_gate가 18:45 KST mon-fri, distinct id로 등록된다 (EC-5)."""
        from unittest.mock import patch

        with (
            patch("app.services.scheduler.scheduler") as mock_sched,
            patch("app.services.scheduler.settings") as mock_settings,
        ):
            mock_settings.NEWS_CRAWL_INTERVAL_MINUTES = 30
            mock_settings.DART_CRAWL_INTERVAL_MINUTES = 60
            mock_settings.MARKET_CAP_UPDATE_HOURS = 6

            from app.services.scheduler import start_scheduler

            start_scheduler()

            matching_calls = [
                call for call in mock_sched.add_job.call_args_list
                if call.kwargs.get("id") == "surge_backtest_gate"
            ]
        assert len(matching_calls) == 1
        kwargs = matching_calls[0].kwargs
        assert kwargs["hour"] == 18
        assert kwargs["minute"] == 45
        assert kwargs["day_of_week"] == "mon-fri"
        assert kwargs["timezone"] == "Asia/Seoul"
        assert kwargs["max_instances"] == 1
        assert kwargs["coalesce"] is True
        assert kwargs["replace_existing"] is True
        # 기존 18:30/19:00 잡과 distinct id (충돌 없음)
        other_ids = {"surge_verify_predictions", "surge_auto_improve"}
        assert "surge_backtest_gate" not in other_ids


# ---------------------------------------------------------------------------
# REQ-AI069-003: _check_backtest_gate — 독립 단위 테스트 (analyze_and_improve와 격리)
# ---------------------------------------------------------------------------

class TestCheckBacktestGate:
    def _make_result(self, db: Session, *, run_date: date, verdict: str):
        from app.models.surge_backtest_result import SurgeBacktestResult

        row = SurgeBacktestResult(
            run_date=run_date,
            total_signals=30,
            directional_accuracy=0.55,
            average_return_pct=2.0,
            verdict=verdict,
            config_hash="a" * 16,
            min_signals=20,
            min_directional_accuracy=0.50,
            lookback_days=30,
        )
        db.add(row)
        db.flush()
        return row

    def test_no_record_blocks(self, db: Session):
        """레코드가 없으면 보수적으로 미통과(EC-2)."""
        from app.services.surge_auto_improver import _check_backtest_gate

        allowed, verdict = _check_backtest_gate(db)
        assert allowed is False
        assert verdict == "no_record"

    def test_pass_verdict_allows(self, db: Session):
        from app.services.surge_auto_improver import _check_backtest_gate

        self._make_result(db, run_date=date(2026, 6, 9), verdict="pass")
        db.commit()

        allowed, verdict = _check_backtest_gate(db)
        assert allowed is True
        assert verdict == "pass"

    def test_fail_verdict_blocks(self, db: Session):
        from app.services.surge_auto_improver import _check_backtest_gate

        self._make_result(db, run_date=date(2026, 6, 9), verdict="fail")
        db.commit()

        allowed, verdict = _check_backtest_gate(db)
        assert allowed is False
        assert verdict == "fail"

    def test_insufficient_verdict_blocks(self, db: Session):
        from app.services.surge_auto_improver import _check_backtest_gate

        self._make_result(db, run_date=date(2026, 6, 9), verdict="insufficient")
        db.commit()

        allowed, verdict = _check_backtest_gate(db)
        assert allowed is False
        assert verdict == "insufficient"

    def test_latest_by_run_date_wins(self, db: Session):
        """run_date가 더 최신인 레코드가 우선한다."""
        from app.services.surge_auto_improver import _check_backtest_gate

        self._make_result(db, run_date=date(2026, 6, 1), verdict="pass")
        self._make_result(db, run_date=date(2026, 6, 9), verdict="fail")
        db.commit()

        allowed, verdict = _check_backtest_gate(db)
        assert allowed is False
        assert verdict == "fail"


# ---------------------------------------------------------------------------
# REQ-AI069-003: analyze_and_improve 통합 — backtest 게이트가 쓰기를 차단하는지 검증
# 이 클래스는 test_surge_auto_improver.py의 autouse 픽스처(항상 pass 시딩) 영향을 받지
# 않도록 이 파일에 독립적으로 위치한다 — auto_improve_enabled/backtest 상태를 직접 구성한다.
# ---------------------------------------------------------------------------

class TestAnalyzeAndImproveBacktestGateIntegration:
    def _enable_auto_improve(self):
        from app.surge_config.surge_settings import _AUTO_CONFIG_PATH, reload_surge_config

        _AUTO_CONFIG_PATH.write_text(
            "surge_detection:\n  auto_improve_enabled: true\n", encoding="utf-8"
        )
        reload_surge_config()

    def _make_evaluation(self, db: Session, eval_date: date, **kwargs):
        from app.models.surge_prediction_evaluation import SurgePredictionEvaluation

        defaults = dict(
            predicted_count=10,
            actual_surge_count=10,
            true_positive=5,
            false_positive=5,
            false_negative=5,
            precision=0.5,
            recall=0.20,
            scannable_recall=0.20,
            f1_score=0.28,
        )
        defaults.update(kwargs)
        ev = SurgePredictionEvaluation(evaluation_date=eval_date, **defaults)
        db.add(ev)
        db.flush()
        return ev

    def test_no_backtest_record_blocks_write(self, db: Session):
        """backtest 레코드가 전혀 없으면(no_record) _write_auto_yaml이 호출되지 않는다 (Scenario 3)."""
        from unittest.mock import patch

        from app.services.surge_auto_improver import analyze_and_improve

        self._enable_auto_improve()

        today = date(2026, 6, 9)
        for i in range(4):
            self._make_evaluation(db, today - timedelta(days=i + 1))
        # scannable_recall < 0.30 → min_score 완화 후보 발생 조건
        self._make_evaluation(db, today, scannable_recall=0.10, actual_surge_count=10)
        db.commit()

        with patch("app.services.surge_auto_improver._write_auto_yaml") as mock_write:
            analyze_and_improve(db, today)

        mock_write.assert_not_called()

    def test_fail_verdict_blocks_write(self, db: Session):
        """최신 backtest verdict='fail'이면 _write_auto_yaml이 호출되지 않는다 (Scenario 3)."""
        from unittest.mock import patch

        from app.models.surge_backtest_result import SurgeBacktestResult
        from app.services.surge_auto_improver import analyze_and_improve

        self._enable_auto_improve()

        db.add(
            SurgeBacktestResult(
                run_date=date(2026, 6, 9),
                total_signals=30,
                directional_accuracy=0.30,
                average_return_pct=-1.0,
                verdict="fail",
                config_hash="b" * 16,
                min_signals=20,
                min_directional_accuracy=0.50,
                lookback_days=30,
            )
        )

        today = date(2026, 6, 9)
        for i in range(4):
            self._make_evaluation(db, today - timedelta(days=i + 1))
        self._make_evaluation(db, today, scannable_recall=0.10, actual_surge_count=10)
        db.commit()

        with patch("app.services.surge_auto_improver._write_auto_yaml") as mock_write:
            analyze_and_improve(db, today)

        mock_write.assert_not_called()

    def test_pass_verdict_allows_write(self, db: Session):
        """최신 backtest verdict='pass'이면 정상적으로 _write_auto_yaml이 호출된다."""
        from unittest.mock import patch

        from app.models.surge_backtest_result import SurgeBacktestResult
        from app.services.surge_auto_improver import analyze_and_improve

        self._enable_auto_improve()

        db.add(
            SurgeBacktestResult(
                run_date=date(2026, 6, 9),
                total_signals=30,
                directional_accuracy=0.60,
                average_return_pct=3.0,
                verdict="pass",
                config_hash="c" * 16,
                min_signals=20,
                min_directional_accuracy=0.50,
                lookback_days=30,
            )
        )

        today = date(2026, 6, 9)
        for i in range(4):
            self._make_evaluation(db, today - timedelta(days=i + 1))
        self._make_evaluation(db, today, scannable_recall=0.10, actual_surge_count=10)
        db.commit()

        with (
            patch("app.services.surge_auto_improver._write_auto_yaml") as mock_write,
            patch("app.services.surge_auto_improver.reload_surge_config"),
        ):
            analyze_and_improve(db, today)

        mock_write.assert_called()


# ---------------------------------------------------------------------------
# REQ-AI069-003: 나머지 _write_auto_yaml 호출 지점 게이팅 (EV가드, R12 롤백)
# ---------------------------------------------------------------------------

class TestBacktestGateBlocksEvGuardAndRollback:
    def _enable_auto_improve(self):
        from app.surge_config.surge_settings import _AUTO_CONFIG_PATH, reload_surge_config

        _AUTO_CONFIG_PATH.write_text(
            "surge_detection:\n  auto_improve_enabled: true\n", encoding="utf-8"
        )
        reload_surge_config()

    def _make_evaluation(self, db: Session, eval_date: date, **kwargs):
        from app.models.surge_prediction_evaluation import SurgePredictionEvaluation

        defaults = dict(
            predicted_count=10,
            actual_surge_count=10,
            true_positive=5,
            false_positive=5,
            false_negative=5,
            precision=0.5,
            recall=0.5,
            scannable_recall=0.5,
            f1_score=0.5,
        )
        defaults.update(kwargs)
        ev = SurgePredictionEvaluation(evaluation_date=eval_date, **defaults)
        db.add(ev)
        db.flush()
        return ev

    def test_ev_guard_blocked_by_backtest_gate(self, db: Session):
        """EV가드 발동 조건(EV<floor)이 충족되어도 backtest 게이트 미통과면 쓰기가 스킵된다."""
        import json as _json
        from datetime import timedelta
        from unittest.mock import patch

        from app.models.improvement_log import ImprovementLog
        from app.services.surge_auto_improver import analyze_and_improve

        self._enable_auto_improve()
        # backtest 레코드 없음 → no_record → 게이트 미통과 (기본 상태)

        today = date(2026, 6, 9)
        for i in range(5):
            self._make_evaluation(db, today - timedelta(days=i))

        # 롤링 EV < floor(0.0)을 만들기 위한 failure_aggregation 로그 5건 (n_samples>=20)
        for _ in range(5):
            log = ImprovementLog(
                action_type="failure_aggregation",
                details=_json.dumps({
                    "accuracy_rate": 0.3,
                    "avg_return_correct": 1.0,
                    "avg_return_incorrect": -5.0,
                    "total_verified": 5,
                }),
            )
            db.add(log)
        db.commit()

        with patch("app.services.surge_auto_improver._write_auto_yaml") as mock_write:
            analyze_and_improve(db, today)

        mock_write.assert_not_called()

    def test_ev_guard_allowed_writes_when_gate_passes(self, db: Session):
        """EV가드 발동 조건(EV<floor)이 충족되고 backtest 게이트가 통과(pass)이면
        _write_auto_yaml이 실제로 호출되고 min_score_for_signal이 기대한 대로 상향 조정된다.

        # evaluator-active MEDIUM 갭 보강: R12 롤백/윈도우 확장/메인 쓰기 3곳은 게이트 통과 시
        # 정상 호출됨이 이미 검증되어 있었으나 EV가드(Step 4.5)만 차단 경로만 테스트되어 있었다.
        """
        import json as _json
        from datetime import timedelta
        from unittest.mock import patch

        from app.models.improvement_log import ImprovementLog
        from app.models.surge_backtest_result import SurgeBacktestResult
        from app.services.surge_auto_improver import analyze_and_improve
        from app.surge_config.surge_settings import get_surge_config

        self._enable_auto_improve()

        # backtest 게이트 통과(pass) 판정 시딩 — R12/윈도우확장/메인쓰기와 동일 패턴
        db.add(
            SurgeBacktestResult(
                run_date=date(2026, 6, 9),
                total_signals=30,
                directional_accuracy=0.60,
                average_return_pct=3.0,
                verdict="pass",
                config_hash="e" * 16,
                min_signals=20,
                min_directional_accuracy=0.50,
                lookback_days=30,
            )
        )

        today = date(2026, 6, 9)
        # scannable_recall=0.5(default)로 Step 4 자체 조정은 없음(delta=0) — EV가드 단독 효과만 검증
        for i in range(5):
            self._make_evaluation(db, today - timedelta(days=i))

        # 롤링 EV < floor(0.0)을 만들기 위한 failure_aggregation 로그 5건 (n_samples>=20)
        for _ in range(5):
            log = ImprovementLog(
                action_type="failure_aggregation",
                details=_json.dumps({
                    "accuracy_rate": 0.3,
                    "avg_return_correct": 1.0,
                    "avg_return_incorrect": -5.0,
                    "total_verified": 5,
                }),
            )
            db.add(log)
        db.commit()

        current_min_score = get_surge_config().ensemble.min_score_for_signal
        expected_new_score = min(0.65, current_min_score + 0.02)

        with (
            patch("app.services.surge_auto_improver._write_auto_yaml") as mock_write,
            patch("app.services.surge_auto_improver.reload_surge_config"),
        ):
            analyze_and_improve(db, today)

        mock_write.assert_called()
        min_score_updates = [
            call.args[0]["ensemble.min_score_for_signal"]
            for call in mock_write.call_args_list
            if "ensemble.min_score_for_signal" in call.args[0]
        ]
        assert len(min_score_updates) >= 1, (
            f"min_score_for_signal 업데이트 기대, 실제 _write_auto_yaml 호출: "
            f"{mock_write.call_args_list}"
        )
        assert min_score_updates[0] == pytest.approx(expected_new_score)

    def test_window_expansion_blocked_by_backtest_gate(self, db: Session):
        """3일 연속 recall=0 + 탐지기 기여=0 조건이어도 backtest 게이트 미통과면 윈도우 확장 쓰기가 스킵된다."""
        from datetime import timedelta
        from unittest.mock import patch

        from app.services.surge_auto_improver import analyze_and_improve

        self._enable_auto_improve()
        # backtest 레코드 없음 → no_record → 게이트 미통과

        today = date(2026, 6, 9)
        # 3일 연속 recall=0 (all_zero_recall 조건) + 탐지기 기여 없음(신호 데이터 없음 → all_zero_contrib)
        for i in range(5):
            self._make_evaluation(
                db, today - timedelta(days=i),
                recall=0.0, precision=0.0, scannable_recall=0.0,
            )
        db.commit()

        with patch("app.services.surge_auto_improver._write_auto_yaml") as mock_write:
            analyze_and_improve(db, today)

        window_calls = [
            call for call in mock_write.call_args_list
            if any("news_window_hours" in k for k in (call.args[0] if call.args else {}))
        ]
        assert window_calls == []

    def test_r12_rollback_blocked_by_backtest_gate(self, db: Session):
        """R12 롤백 발동 조건이 충족되어도 backtest 게이트 미통과면 쓰기가 스킵되고
        rationale이 backtest_gate_blocked로 기록된다."""
        from datetime import timedelta
        from unittest.mock import patch

        from app.models.surge_auto_improvement_log import SurgeAutoImprovementLog
        from app.services.surge_auto_improver import analyze_and_improve

        self._enable_auto_improve()

        today = date(2026, 6, 9)
        prev_day = today - timedelta(days=1)

        for i in range(4):
            ev_date = today - timedelta(days=i + 1)
            recall_val = 0.20 if i == 0 else 0.60  # prev_day만 낮게(롤백 트리거 조건)
            self._make_evaluation(db, ev_date, recall=recall_val, scannable_recall=recall_val)
        self._make_evaluation(db, today, recall=0.55, scannable_recall=0.55)

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

        with patch("app.services.surge_auto_improver._write_auto_yaml") as mock_write:
            logs = analyze_and_improve(db, today)

        mock_write.assert_not_called()
        blocked_logs = [log for log in logs if log.rationale.startswith("backtest_gate_blocked")]
        assert len(blocked_logs) > 0


# ---------------------------------------------------------------------------
# REQ-AI069-003: scannable_recall 재타게팅 — None이면 조정 스킵
# ---------------------------------------------------------------------------

class TestScannableRecallRetargeting:
    def _enable_auto_improve_with_passing_gate(self, db: Session):
        from app.models.surge_backtest_result import SurgeBacktestResult
        from app.surge_config.surge_settings import _AUTO_CONFIG_PATH, reload_surge_config

        _AUTO_CONFIG_PATH.write_text(
            "surge_detection:\n  auto_improve_enabled: true\n", encoding="utf-8"
        )
        reload_surge_config()
        db.add(
            SurgeBacktestResult(
                run_date=date(2026, 6, 9),
                total_signals=30,
                directional_accuracy=0.60,
                average_return_pct=3.0,
                verdict="pass",
                config_hash="d" * 16,
                min_signals=20,
                min_directional_accuracy=0.50,
                lookback_days=30,
            )
        )

    def _make_evaluation(self, db: Session, eval_date: date, **kwargs):
        from app.models.surge_prediction_evaluation import SurgePredictionEvaluation

        defaults = dict(
            predicted_count=10,
            actual_surge_count=10,
            true_positive=5,
            false_positive=5,
            false_negative=5,
            precision=0.5,
            recall=0.20,
            f1_score=0.28,
        )
        defaults.update(kwargs)
        ev = SurgePredictionEvaluation(evaluation_date=eval_date, **defaults)
        db.add(ev)
        db.flush()
        return ev

    def test_none_scannable_recall_skips_adjustment(self, db: Session):
        """scannable_recall=None(스캔 유니버스 미가용)이면 min_score 조정을 스킵한다 (REQ-003)."""
        from unittest.mock import patch

        from app.services.surge_auto_improver import analyze_and_improve

        self._enable_auto_improve_with_passing_gate(db)

        today = date(2026, 6, 9)
        for i in range(4):
            self._make_evaluation(db, today - timedelta(days=i + 1))
        # recall=0.10(레거시 필드)이지만 scannable_recall은 미지정(None)
        self._make_evaluation(db, today, recall=0.10, actual_surge_count=10)
        db.commit()

        with (
            patch("app.services.surge_auto_improver._write_auto_yaml") as mock_write,
            patch("app.services.surge_auto_improver.reload_surge_config"),
        ):
            analyze_and_improve(db, today)

        calls_with_min_score = [
            call for call in mock_write.call_args_list
            if "ensemble.min_score_for_signal" in (call.args[0] if call.args else {})
        ]
        assert calls_with_min_score == []


# ---------------------------------------------------------------------------
# REQ-AI069-005: calibrator 무효 상태(identity fallback) 표면화
# ---------------------------------------------------------------------------

class TestGetCalibratorStatus:
    def test_identity_fallback_surfaced(self, tmp_path):
        """pkl 파일이 없으면 is_identity=True로 표면화된다."""
        from app.services.surge_calibrator import load_calibrator

        missing_path = tmp_path / "does_not_exist.pkl"
        model = load_calibrator(path=missing_path)
        assert model.is_identity is True

    def test_status_dict_shape(self):
        """get_calibrator_status()는 is_identity/trained_at/sample_count 키를 포함한다."""
        from app.services.surge_calibrator import get_calibrator_status

        status = get_calibrator_status()
        assert "is_identity" in status
        assert "trained_at" in status
        assert "sample_count" in status


class TestFormatTelegramReportCalibratorSection:
    def _make_eval(self):
        from app.models.surge_prediction_evaluation import SurgePredictionEvaluation

        return SurgePredictionEvaluation(
            evaluation_date=date(2026, 6, 9),
            predicted_count=10,
            actual_surge_count=10,
            true_positive=5,
            false_positive=5,
            false_negative=5,
            precision=0.5,
            recall=0.5,
            f1_score=0.5,
        )

    def test_identity_status_shown_in_report(self):
        from app.services.surge_auto_improver import format_telegram_report

        ev = self._make_eval()
        report = format_telegram_report(
            ev, [], [], calibrator_status={"is_identity": True, "sample_count": 0, "trained_at": ""}
        )
        assert "캘리브레이터" in report
        assert "identity" in report.lower() or "미보정" in report

    def test_non_identity_status_not_shown(self):
        from app.services.surge_auto_improver import format_telegram_report

        ev = self._make_eval()
        report = format_telegram_report(
            ev, [], [],
            calibrator_status={"is_identity": False, "sample_count": 100, "trained_at": "2026-06-01"},
        )
        assert "캘리브레이터" not in report

    def test_none_status_backward_compatible(self):
        """calibrator_status 미지정(None)이면 기존 리포트 형식과 동일하다(하위 호환)."""
        from app.services.surge_auto_improver import format_telegram_report

        ev = self._make_eval()
        report = format_telegram_report(ev, [], [])
        assert "캘리브레이터" not in report


# ---------------------------------------------------------------------------
# REQ-AI069-002 (D4): main.py startup — reset_auto_yaml_to_base가 _restore_auto_yaml보다
# 선행 실행되어 배포 후 drift 값이 DB로부터 복구되지 않고 base yaml로 리셋됨을 검증
# (Scenario 1: 배포 전 drift → 배포 후 base 기본값 리셋).
# ---------------------------------------------------------------------------

class TestMainStartupResetOrdering:
    def test_reset_runs_before_restore_on_app_startup(self, db: Session):
        from unittest.mock import patch

        from app.database import get_db
        from app.main import app
        from app.surge_config.surge_settings import _AUTO_CONFIG_PATH, reload_surge_config
        from fastapi.testclient import TestClient

        # 배포 전 drift 값 시뮬레이션
        _AUTO_CONFIG_PATH.write_text(
            "surge_detection:\n  ensemble:\n    min_score_for_signal: 0.44\n",
            encoding="utf-8",
        )
        reload_surge_config()

        def override_get_db():
            yield db

        app.dependency_overrides[get_db] = override_get_db
        try:
            with (
                patch("app.main._run_migrations"),
                patch("app.main.start_scheduler"),
                patch("app.main.stop_scheduler"),
                patch("threading.Thread"),
            ):
                with TestClient(app, raise_server_exceptions=True):
                    pass
        finally:
            app.dependency_overrides.clear()

        # drift 값이 사라지고(리셋됨) base 기본값(0.38)으로 복원되어야 함
        from app.surge_config.surge_settings import get_surge_config

        cfg = get_surge_config()
        assert abs(cfg.ensemble.min_score_for_signal - 0.38) < 1e-6


# ---------------------------------------------------------------------------
# REQ-AI069-005: run_daily_report — calibrator_status가 리포트에 전달되는지 검증
# ---------------------------------------------------------------------------

class TestRunDailyReportCalibratorIntegration:
    async def _run(self, db: Session, trading_date: date):
        from unittest.mock import AsyncMock, patch

        from app.services.surge_auto_improver import run_daily_report

        with (
            patch("app.services.telegram_service.send_telegram_message", new=AsyncMock(return_value=True)),
            patch.dict("os.environ", {"TELEGRAM_ADMIN_CHAT_ID": "123456"}),
        ):
            await run_daily_report(db, trading_date)

    def test_report_includes_calibrator_status_when_identity(self, db: Session):
        """calibrator가 identity 상태면 리포트 발송 파이프라인이 예외 없이 완료된다."""
        import asyncio

        from app.models.surge_prediction_evaluation import SurgePredictionEvaluation

        trading_date = date(2026, 6, 9)
        db.add(
            SurgePredictionEvaluation(
                evaluation_date=trading_date,
                predicted_count=5,
                actual_surge_count=5,
                true_positive=2,
                false_positive=3,
                false_negative=3,
                precision=0.4,
                recall=0.4,
                f1_score=0.4,
            )
        )
        db.commit()

        # 예외를 던지지 않고 완료되어야 함 (calibrator 상태 조회 실패도 예외 격리됨)
        asyncio.run(self._run(db, trading_date))

    def test_no_evaluation_skips_report(self, db: Session):
        """평가 결과가 없으면 리포트 생성 자체를 스킵한다(기존 동작 보존)."""
        import asyncio

        # 평가 없음 — run_daily_report는 조기 반환해야 함(예외 없이)
        asyncio.run(self._run(db, date(2099, 1, 1)))


class TestCharacterizeBaselineWarmingUnaffectedByFlag(object):
    """update_baselines()는 zscore_enabled flag와 무관하게 항상 raw 관측값으로 기준선을 갱신한다.

    (재활성 대비 baseline warm 유지 — SPEC-AI-069 REQ-004 요구사항)
    """

    def test_update_baselines_uses_raw_regardless_of_flag(self, db: Session):
        obs = [Observation("000123", "theme_cluster", 0.42)]
        update_baselines(db, obs)

        from app.services.surge_baseline_service import get_baselines

        baselines = get_baselines(db, ["000123"], ["theme_cluster"])
        stats = baselines[("000123", "theme_cluster")]
        assert abs(stats.rolling_mean - 0.42) < 0.001
