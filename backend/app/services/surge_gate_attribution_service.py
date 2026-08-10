"""SPEC-AI-115: gate/drop attribution observations and shadow reports."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.models.surge_actual_outcome import SurgeActualOutcome
from app.models.surge_gate_drop_observation import SurgeGateDropObservation
from app.models.surge_prediction_evaluation import SurgePredictionEvaluation

logger = logging.getLogger(__name__)

RELAXED_REGIME_THRESHOLD_PROFILE = "regime_threshold_minus_0_05"


@dataclass(frozen=True)
class GateDropObservation:
    trading_date: date
    stock_code: str
    gate_name: str
    detector_set: list[str]
    score_before_drop: float | None
    reason_metadata: dict[str, Any]
    market_regime: str | None = None
    shadow_profile: str | None = None
    shadow_candidate: bool = False


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _round_score(score: float | None) -> float | None:
    if score is None:
        return None
    try:
        return round(float(score), 6)
    except (TypeError, ValueError):
        return None


def _dedupe_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value is None:
            continue
        text = str(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def detector_set_from_candidate(candidate: Any) -> list[str]:
    """Return a compact detector set from a SurgeCandidate-like object."""
    detectors = list(getattr(candidate, "active_detectors", []) or [])
    score_fields = (
        ("theme_cluster_score", "theme_cluster"),
        ("combo_score", "volume_news_combo"),
        ("pattern_score", "disclosure_pattern"),
        ("legacy_score", "legacy"),
        ("immediate_disclosure_score", "immediate_disclosure"),
        ("news_delayed_score", "news_delayed"),
        ("volume_breakout_score", "volume_breakout"),
        ("momentum_continuation_score", "momentum_continuation"),
        ("bridge_score", "scan_universe_bridge"),
    )
    for attr, detector_name in score_fields:
        try:
            if float(getattr(candidate, attr, 0.0) or 0.0) > 0.0:
                detectors.append(detector_name)
        except (TypeError, ValueError):
            continue
    return _dedupe_strings(detectors)


def build_gate_drop_observation(
    candidate: Any,
    *,
    trading_date: date,
    gate_name: str,
    score_before_drop: float | None,
    reason_metadata: dict[str, Any] | None = None,
    market_regime: str | None = None,
    shadow_profile: str | None = None,
    shadow_candidate: bool = False,
) -> GateDropObservation:
    """Build a drop observation from a SurgeCandidate-like object."""
    return GateDropObservation(
        trading_date=trading_date,
        stock_code=str(getattr(candidate, "stock_code")),
        gate_name=gate_name,
        detector_set=detector_set_from_candidate(candidate),
        score_before_drop=_round_score(score_before_drop),
        reason_metadata=dict(reason_metadata or {}),
        market_regime=market_regime,
        shadow_profile=shadow_profile,
        shadow_candidate=shadow_candidate,
    )


def build_evaluation_exclusion_observation(
    *,
    trading_date: date,
    stock_code: str,
    gate_name: str,
    surge_metadata_json: str | None,
) -> GateDropObservation:
    """Build an observation for an evaluation-only exclusion."""
    metadata: dict[str, Any] = {}
    try:
        parsed = json.loads(surge_metadata_json) if surge_metadata_json else {}
        if isinstance(parsed, dict):
            metadata = parsed
    except (TypeError, ValueError):
        metadata = {"metadata_parse_error": True}

    raw_basis = metadata.get("surge_basis")
    detector_set = _dedupe_strings(raw_basis if isinstance(raw_basis, list) else [])
    score = _round_score(metadata.get("surge_probability_score"))
    reason = {
        "source": "evaluate_surge_predictions",
        "metadata_horizon": metadata.get("horizon"),
        "near_limit_up_carry": bool(metadata.get("near_limit_up_carry")),
        "surge_basis": detector_set,
    }
    return GateDropObservation(
        trading_date=trading_date,
        stock_code=stock_code,
        gate_name=gate_name,
        detector_set=detector_set,
        score_before_drop=score,
        reason_metadata=reason,
    )


def persist_gate_drop_observations(
    db: Session,
    observations: list[GateDropObservation],
) -> int:
    """Append gate/drop observations.

    Callers wrap this function in fail-open blocks because observations must not
    change signal generation or evaluation outcomes.
    """
    if not observations:
        return 0

    rows = [
        SurgeGateDropObservation(
            trading_date=obs.trading_date,
            stock_code=obs.stock_code,
            gate_name=obs.gate_name,
            detector_set_json=_json_dump(obs.detector_set),
            score_before_drop=obs.score_before_drop,
            reason_metadata_json=_json_dump(obs.reason_metadata),
            market_regime=obs.market_regime,
            shadow_profile=obs.shadow_profile,
            shadow_candidate=obs.shadow_candidate,
        )
        for obs in observations
    ]
    db.add_all(rows)
    db.flush()
    db.commit()
    logger.info("[gate-attribution] drop observations persisted: count=%d", len(rows))
    return len(rows)


def _safe_precision(tp: int, count: int) -> float | None:
    if count <= 0:
        return None
    return tp / count


def _actual_positive_map(
    db: Session,
    evaluation_dates: list[date],
) -> dict[tuple[date, str], bool]:
    if not evaluation_dates:
        return {}
    rows = (
        db.query(
            SurgeActualOutcome.trading_date,
            SurgeActualOutcome.stock_code,
            SurgeActualOutcome.was_surge,
        )
        .filter(SurgeActualOutcome.trading_date.in_(evaluation_dates))
        .all()
    )
    return {
        (row.trading_date, row.stock_code): bool(row.was_surge)
        for row in rows
    }


def _classify_profile_guardrail(
    *,
    added_count: int,
    candidate_count_multiplier: float | None,
    max_candidate_multiplier: float,
    baseline_precision: float | None,
    added_precision: float | None,
) -> tuple[str, str]:
    if added_count <= 0:
        return "no_go", "no_added_candidates"
    precision_gain_explicit = (
        baseline_precision is not None
        and added_precision is not None
        and added_precision > baseline_precision
    )
    if (
        candidate_count_multiplier is not None
        and candidate_count_multiplier > max_candidate_multiplier
        and not precision_gain_explicit
    ):
        return "no_go", "candidate_inflation_gt_2x"
    return "go", "ready"


def generate_gate_drop_shadow_report(
    db: Session,
    *,
    days: int = 20,
    end_date: date | None = None,
    min_eligible_days: int = 10,
    max_candidate_multiplier: float = 2.0,
) -> dict[str, Any]:
    """Rank relaxed-gate profiles by estimated recall gain per added FP."""
    query = db.query(SurgePredictionEvaluation)
    if end_date is not None:
        query = query.filter(SurgePredictionEvaluation.evaluation_date <= end_date)
    evaluations = (
        query.order_by(SurgePredictionEvaluation.evaluation_date.desc())
        .limit(days)
        .all()
    )
    evaluations = sorted(evaluations, key=lambda row: row.evaluation_date)
    evaluation_dates = [row.evaluation_date for row in evaluations]
    eligible_days = len(evaluation_dates)

    if eligible_days < min_eligible_days:
        return {
            "status": "no_go",
            "reason": "insufficient_eligible_days",
            "eligible_days": eligible_days,
            "min_eligible_days": min_eligible_days,
            "profiles": [],
        }

    observations = (
        db.query(SurgeGateDropObservation)
        .filter(
            SurgeGateDropObservation.trading_date.in_(evaluation_dates),
            SurgeGateDropObservation.shadow_candidate.is_(True),
            SurgeGateDropObservation.shadow_profile.isnot(None),
        )
        .all()
    )
    if not observations:
        return {
            "status": "no_go",
            "reason": "no_shadow_candidates",
            "eligible_days": eligible_days,
            "min_eligible_days": min_eligible_days,
            "profiles": [],
        }

    evaluation_by_date = {row.evaluation_date: row for row in evaluations}
    baseline_predicted_count = sum(int(row.predicted_count or 0) for row in evaluations)
    baseline_tp = sum(int(row.true_positive or 0) for row in evaluations)
    baseline_actual_count = sum(int(row.actual_surge_count or 0) for row in evaluations)
    baseline_precision = _safe_precision(baseline_tp, baseline_predicted_count)
    actual_positive = _actual_positive_map(db, evaluation_dates)

    by_profile: dict[str, set[tuple[date, str]]] = {}
    gates_by_profile: dict[str, set[str]] = {}
    for obs in observations:
        profile = obs.shadow_profile
        if not profile:
            continue
        if obs.trading_date not in evaluation_by_date:
            continue
        by_profile.setdefault(profile, set()).add((obs.trading_date, obs.stock_code))
        gates_by_profile.setdefault(profile, set()).add(obs.gate_name)

    profiles: list[dict[str, Any]] = []
    for profile, added_pairs in by_profile.items():
        added_count = len(added_pairs)
        expected_tp = sum(1 for pair in added_pairs if actual_positive.get(pair) is True)
        expected_fp = added_count - expected_tp
        added_precision = _safe_precision(expected_tp, added_count)
        candidate_count_multiplier = (
            (baseline_predicted_count + added_count) / baseline_predicted_count
            if baseline_predicted_count > 0
            else None
        )
        estimated_recall_gain = (
            expected_tp / baseline_actual_count
            if baseline_actual_count > 0
            else None
        )
        recall_gain_per_added_fp = (
            expected_tp / expected_fp
            if expected_fp > 0
            else (float(expected_tp) if expected_tp > 0 else 0.0)
        )
        guardrail_status, reason = _classify_profile_guardrail(
            added_count=added_count,
            candidate_count_multiplier=candidate_count_multiplier,
            max_candidate_multiplier=max_candidate_multiplier,
            baseline_precision=baseline_precision,
            added_precision=added_precision,
        )
        profiles.append(
            {
                "profile": profile,
                "gate_names": sorted(gates_by_profile.get(profile, set())),
                "eligible_days": eligible_days,
                "baseline_predicted_count": baseline_predicted_count,
                "baseline_precision": baseline_precision,
                "added_candidates": added_count,
                "removed_candidates": 0,
                "expected_tp": expected_tp,
                "expected_fp": expected_fp,
                "added_precision": added_precision,
                "estimated_recall_gain": estimated_recall_gain,
                "recall_gain_per_added_fp": recall_gain_per_added_fp,
                "candidate_count_multiplier": candidate_count_multiplier,
                "prediction_count_inflation": (
                    added_count / baseline_predicted_count
                    if baseline_predicted_count > 0
                    else None
                ),
                "guardrail_status": guardrail_status,
                "reason": reason,
            }
        )

    profiles.sort(
        key=lambda row: (
            row["guardrail_status"] == "go",
            row["recall_gain_per_added_fp"],
            row["estimated_recall_gain"] or 0.0,
            row["expected_tp"],
        ),
        reverse=True,
    )
    recommendation = next(
        (profile for profile in profiles if profile["guardrail_status"] == "go"),
        None,
    )
    return {
        "status": "go" if recommendation is not None else "no_go",
        "reason": "ready" if recommendation is not None else profiles[0]["reason"],
        "eligible_days": eligible_days,
        "min_eligible_days": min_eligible_days,
        "recommended_profile": recommendation["profile"] if recommendation else None,
        "profiles": profiles,
    }
