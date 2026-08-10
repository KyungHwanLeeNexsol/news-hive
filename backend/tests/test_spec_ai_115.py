"""SPEC-AI-115 acceptance tests."""

from __future__ import annotations

import json
from contextlib import ExitStack, contextmanager
from datetime import date, datetime, time, timedelta
from unittest.mock import patch

from sqlalchemy.orm import Session

from app.models.fund_signal import FundSignal
from app.models.surge_actual_outcome import SurgeActualOutcome
from app.models.surge_gate_drop_observation import SurgeGateDropObservation
from app.models.surge_prediction_evaluation import SurgePredictionEvaluation
from app.services.surge_detector import (
    SurgeCandidate,
    _apply_price_fetch_truncation,
    gather_surge_candidates,
)
from app.services.surge_evaluation_service import evaluate_surge_predictions
from app.services.surge_gate_attribution_service import (
    RELAXED_REGIME_THRESHOLD_PROFILE,
    generate_gate_drop_shadow_report,
)
from app.services.surge_trading_service import _get_prev_business_day
from app.surge_config.surge_settings import get_surge_config


def _dt(day: date, hour: int = 15, minute: int = 20) -> datetime:
    return datetime.combine(day, time(hour=hour, minute=minute))


def _config_for_gate_observation():
    base = get_surge_config()
    horizon = base.ensemble.horizon_aware_thresholds.model_copy(
        update={"enabled": False, "shadow_mode_enabled": False}
    )
    ensemble = base.ensemble.model_copy(
        update={
            "min_score_for_signal": 0.45,
            "regime_thresholds": {"NEUTRAL": 0.45},
            "strong_single_bypass_threshold": 0.85,
            "immediate_disclosure_bypass_threshold": 0.85,
            "horizon_aware_thresholds": horizon,
        }
    )
    return base.model_copy(
        update={
            "ensemble": ensemble,
            "gate_drop_observation_enabled": True,
            "relaxed_gate_shadow_enabled": True,
            "relaxed_gate_shadow_threshold_delta": 0.05,
            "scan_universe_bridge_candidates_enabled": False,
            "scan_universe_bridge_shadow_enabled": False,
            "universe_gap_measurement_enabled": False,
        }
    )


def _candidate(
    stock_code: str,
    *,
    theme: float = 0.0,
    combo: float = 0.0,
    immediate: float = 0.0,
    volume_breakout: float = 0.0,
    detectors: list[str] | None = None,
) -> SurgeCandidate:
    return SurgeCandidate(
        stock_code=stock_code,
        stock_name=f"SPEC115_{stock_code}",
        theme_cluster_score=theme,
        combo_score=combo,
        immediate_disclosure_score=immediate,
        volume_breakout_score=volume_breakout,
        active_detectors=detectors or [],
    )


@contextmanager
def _patched_detector_run(
    candidates: list[SurgeCandidate],
    *,
    sector_ratio: float | None = None,
    persist_raises: bool = False,
):
    with ExitStack() as stack:
        stack.enter_context(
            patch("app.services.surge_detector.detect_theme_news_cluster", return_value=candidates)
        )
        for target in (
            "app.services.surge_detector.detect_volume_surge_news_combo",
            "app.services.surge_detector.detect_disclosure_surge_pattern",
            "app.services.surge_detector.detect_immediate_disclosure_signal",
            "app.services.surge_detector.detect_news_delayed_response",
            "app.services.surge_detector.detect_volume_breakout",
            "app.services.surge_detector.detect_momentum_continuation",
        ):
            stack.enter_context(patch(target, return_value=[]))
        stack.enter_context(
            patch(
                "app.services.surge_detector.build_scan_universe",
                return_value=([], {}, {"pool_a": 0, "pool_b": 0, "pool_c": 0}),
            )
        )
        stack.enter_context(
            patch("app.services.surge_baseline_service.get_baselines", return_value={})
        )
        stack.enter_context(
            patch("app.services.surge_baseline_service.update_baselines", return_value=None)
        )
        stack.enter_context(
            patch("app.services.naver_finance.fetch_stock_price_history_sync", return_value=[])
        )
        stack.enter_context(
            patch("app.services.surge_detector._persist_feature_snapshots", return_value=None)
        )
        if sector_ratio is not None:
            stack.enter_context(
                patch(
                    "app.services.surge_detector._compute_sector_decline_ratio",
                    return_value=sector_ratio,
                )
            )
        if persist_raises:
            stack.enter_context(
                patch(
                    "app.services.surge_detector.persist_gate_drop_observations",
                    side_effect=RuntimeError("boom"),
                )
            )
        yield


def _add_actual(
    db: Session,
    trading_date: date,
    stock_code: str,
    *,
    was_surge: bool,
) -> None:
    db.add(
        SurgeActualOutcome(
            trading_date=trading_date,
            stock_code=stock_code,
            stock_name=f"SPEC115_{stock_code}",
            change_rate=12.0 if was_surge else 1.0,
            was_surge=was_surge,
            high_change_rate=13.0 if was_surge else 2.0,
            market="KOSPI",
        )
    )


def _add_eval(
    db: Session,
    trading_date: date,
    *,
    predicted_count: int,
    true_positive: int,
    actual_surge_count: int,
) -> None:
    false_positive = max(0, predicted_count - true_positive)
    false_negative = max(0, actual_surge_count - true_positive)
    precision = true_positive / predicted_count if predicted_count else 0.0
    recall = true_positive / actual_surge_count if actual_surge_count else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall > 0
        else 0.0
    )
    db.add(
        SurgePredictionEvaluation(
            evaluation_date=trading_date,
            predicted_count=predicted_count,
            actual_surge_count=actual_surge_count,
            true_positive=true_positive,
            false_positive=false_positive,
            false_negative=false_negative,
            precision=precision,
            recall=recall,
            f1_score=f1,
        )
    )


def _add_shadow_observation(
    db: Session,
    trading_date: date,
    stock_code: str,
) -> None:
    db.add(
        SurgeGateDropObservation(
            trading_date=trading_date,
            stock_code=stock_code,
            gate_name="below_regime_threshold",
            detector_set_json=json.dumps(["theme_cluster"]),
            score_before_drop=0.43,
            reason_metadata_json=json.dumps({"threshold": 0.45}),
            market_regime="NEUTRAL",
            shadow_profile=RELAXED_REGIME_THRESHOLD_PROFILE,
            shadow_candidate=True,
        )
    )


class TestGateDropObservation:
    def test_price_fetch_truncation_reports_dropped_existing_candidates(self):
        candidates = {
            f"115{i:03d}": _candidate(f"115{i:03d}", theme=i / 100)
            for i in range(55)
        }
        observed: list[tuple[str, str, float, dict]] = []

        result = _apply_price_fetch_truncation(
            candidates,
            on_drop=lambda gate, cand, score, meta: observed.append(
                (gate, cand.stock_code, score, meta)
            ),
        )

        assert len(result) == 50
        assert len(observed) == 5
        assert {row[0] for row in observed} == {"price_fetch_truncation"}
        assert {row[1] for row in observed} == {
            "115000",
            "115001",
            "115002",
            "115003",
            "115004",
        }
        assert all(row[3]["max_price_fetch_candidates"] == 50 for row in observed)

    def test_gather_records_major_drop_gates_without_changing_output(
        self,
        db: Session,
        make_stock,
    ):
        cfg = _config_for_gate_observation()
        candidates = [
            _candidate(
                "115101",
                theme=0.8,
                combo=0.8,
                volume_breakout=0.7,
                detectors=["theme_cluster", "volume_news_combo", "volume_breakout"],
            ),
            _candidate(
                "115102",
                theme=0.7,
                combo=0.75,
                volume_breakout=0.1,
                detectors=["theme_cluster", "volume_news_combo", "volume_breakout"],
            ),
            _candidate("115103", theme=0.3, combo=0.3, detectors=["theme_cluster"]),
            _candidate("115104", combo=0.9, detectors=["volume_news_combo"]),
            _candidate("115105", immediate=0.8, detectors=["immediate_disclosure"]),
            _candidate("115106", theme=0.9, detectors=["theme_cluster"]),
        ]
        for candidate in candidates:
            make_stock(name=candidate.stock_name, stock_code=candidate.stock_code)

        with _patched_detector_run(candidates):
            result = gather_surge_candidates(db, [], cfg, [], market_regime="NEUTRAL")

        assert [candidate.stock_code for candidate in result] == ["115101"]

        rows = db.query(SurgeGateDropObservation).all()
        gates = {row.gate_name for row in rows}
        assert {
            "below_regime_threshold",
            "combo_chase_guard",
            "immediate_bypass_failed",
            "strong_bypass_failed",
        } <= gates
        shadow_rows = [
            row
            for row in rows
            if row.shadow_profile == RELAXED_REGIME_THRESHOLD_PROFILE
        ]
        assert [(row.stock_code, row.shadow_candidate) for row in shadow_rows] == [
            ("115102", True)
        ]

    def test_sector_contagion_drop_is_observed(self, db: Session, make_stock):
        cfg = _config_for_gate_observation()
        candidate = _candidate(
            "115201",
            theme=0.8,
            combo=0.8,
            volume_breakout=0.7,
            detectors=["theme_cluster", "volume_news_combo", "volume_breakout"],
        )
        make_stock(name=candidate.stock_name, stock_code=candidate.stock_code)

        with _patched_detector_run([candidate], sector_ratio=0.8):
            result = gather_surge_candidates(db, [], cfg, [], market_regime="NEUTRAL")

        assert result == []
        row = db.query(SurgeGateDropObservation).one()
        assert row.gate_name == "sector_contagion_gate"
        assert row.stock_code == "115201"

    def test_observation_persistence_failure_is_fail_open(self, db: Session, make_stock):
        cfg = _config_for_gate_observation()
        qualified = _candidate(
            "115301",
            theme=0.8,
            combo=0.8,
            volume_breakout=0.7,
            detectors=["theme_cluster", "volume_news_combo", "volume_breakout"],
        )
        dropped = _candidate("115302", theme=0.2, detectors=["theme_cluster"])
        for candidate in (qualified, dropped):
            make_stock(name=candidate.stock_name, stock_code=candidate.stock_code)

        with _patched_detector_run([qualified, dropped], persist_raises=True):
            result = gather_surge_candidates(db, [], cfg, [], market_regime="NEUTRAL")

        assert [candidate.stock_code for candidate in result] == ["115301"]


class TestEvaluationExclusionObservation:
    def test_evaluation_exclusions_are_recorded_without_predicted_set_change(
        self,
        db: Session,
        make_stock,
    ):
        cfg = _config_for_gate_observation()
        trading_date = date(2026, 8, 10)
        signal_date = _get_prev_business_day(trading_date)
        near_stock = make_stock(name="SPEC115_NEAR", stock_code="115401")
        same_day_stock = make_stock(name="SPEC115_SAME", stock_code="115402")
        db.add_all(
            [
                FundSignal(
                    stock_id=near_stock.id,
                    signal="buy",
                    confidence=0.6,
                    reasoning="near limit carry",
                    signal_type="surge_candidate",
                    surge_metadata=json.dumps(
                        {
                            "surge_basis": ["near_limit_up_carry"],
                            "near_limit_up_carry": True,
                            "surge_probability_score": 0.42,
                        },
                        ensure_ascii=False,
                    ),
                    created_at=_dt(signal_date),
                ),
                FundSignal(
                    stock_id=same_day_stock.id,
                    signal="buy",
                    confidence=0.9,
                    reasoning="same day event",
                    signal_type="surge_candidate",
                    surge_metadata=json.dumps(
                        {
                            "surge_basis": ["immediate_disclosure"],
                            "horizon": "same_day",
                            "surge_probability_score": 0.9,
                        },
                        ensure_ascii=False,
                    ),
                    created_at=_dt(signal_date),
                ),
            ]
        )
        _add_actual(db, trading_date, near_stock.stock_code, was_surge=True)
        _add_actual(db, trading_date, same_day_stock.stock_code, was_surge=True)
        db.flush()

        with (
            patch("app.surge_config.surge_settings.get_surge_config", return_value=cfg),
            patch(
                "app.services.surge_evaluation_service._persist_signal_forward_outcomes",
                return_value=set(),
            ),
        ):
            evaluation = evaluate_surge_predictions(db, trading_date)

        assert evaluation.predicted_count == 0
        assert evaluation.true_positive == 0
        assert evaluation.false_negative == 2
        gates = {
            row.gate_name
            for row in db.query(SurgeGateDropObservation).order_by(
                SurgeGateDropObservation.gate_name
            )
        }
        assert gates == {
            "evaluation_excluded_near_limit_carry",
            "evaluation_excluded_same_day",
        }


class TestGateShadowReport:
    def test_report_ranks_relaxed_profile_when_guardrails_pass(self, db: Session):
        base_day = date(2026, 7, 20)
        for idx in range(10):
            trading_date = base_day + timedelta(days=idx)
            code = f"1155{idx:02d}"
            _add_eval(
                db,
                trading_date,
                predicted_count=2,
                true_positive=1,
                actual_surge_count=2,
            )
            _add_shadow_observation(db, trading_date, code)
            _add_actual(db, trading_date, code, was_surge=idx < 5)
        db.flush()

        report = generate_gate_drop_shadow_report(db, days=10)

        assert report["status"] == "go"
        assert report["recommended_profile"] == RELAXED_REGIME_THRESHOLD_PROFILE
        profile = report["profiles"][0]
        assert profile["added_candidates"] == 10
        assert profile["expected_tp"] == 5
        assert profile["expected_fp"] == 5
        assert profile["candidate_count_multiplier"] == 1.5
        assert profile["guardrail_status"] == "go"

    def test_report_rejects_candidate_inflation_without_precision_gain(
        self,
        db: Session,
    ):
        base_day = date(2026, 7, 20)
        for idx in range(10):
            trading_date = base_day + timedelta(days=idx)
            _add_eval(
                db,
                trading_date,
                predicted_count=1,
                true_positive=0,
                actual_surge_count=1,
            )
            for suffix in ("A", "B"):
                code = f"1156{idx:02d}{suffix}"
                _add_shadow_observation(db, trading_date, code)
                _add_actual(db, trading_date, code, was_surge=False)
        db.flush()

        report = generate_gate_drop_shadow_report(db, days=10)

        assert report["status"] == "no_go"
        assert report["reason"] == "candidate_inflation_gt_2x"
        profile = report["profiles"][0]
        assert profile["candidate_count_multiplier"] == 3.0
        assert profile["guardrail_status"] == "no_go"
