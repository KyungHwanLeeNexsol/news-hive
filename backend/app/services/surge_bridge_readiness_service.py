"""SPEC-AI-113: Pool A bridge readiness runner and rollback guardrails."""

from __future__ import annotations

from statistics import mean
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.surge_prediction_evaluation import SurgePredictionEvaluation
from app.services.surge_universe_gap_service import (
    evaluate_bridge_activation_readiness,
)

POOL_A_CANARY_CONFIG_PATCH: dict[str, Any] = {
    "scan_universe_bridge_candidates_enabled": True,
    "scan_universe_bridge_pool_b_enabled": False,
    "scan_universe_bridge_max_candidates": 5,
    "scan_universe_bridge_pool_limits": {
        "pool_a": 5,
        "pool_b": 0,
        "pool_c": 0,
    },
    "scan_universe_bridge_shadow_enabled": True,
}


def describe_database_url(database_url: str | None = None) -> dict[str, Any]:
    """Return a non-secret data source identity for operator reports."""
    raw_url = database_url or settings.DATABASE_URL
    parsed = urlsplit(raw_url)
    if parsed.scheme.startswith("sqlite"):
        return {
            "scheme": parsed.scheme,
            "database": parsed.path or parsed.netloc or ":memory:",
        }
    return {
        "scheme": parsed.scheme,
        "host": parsed.hostname,
        "port": parsed.port,
        "database": parsed.path.lstrip("/") or None,
    }


def build_pool_a_bridge_readiness_result(
    db: Session,
    *,
    data_source: dict[str, Any] | None = None,
    min_trading_days: int = 10,
    min_precision_floor: float = 0.05,
    max_zero_precision_streak: int = 4,
) -> dict[str, Any]:
    """Run the existing readiness gate and normalize the operator response."""
    readiness = evaluate_bridge_activation_readiness(
        db,
        target_pool="pool_a",
        min_trading_days=min_trading_days,
        min_precision_floor=min_precision_floor,
        max_zero_precision_streak=max_zero_precision_streak,
    )
    status = "go" if readiness.get("ready") is True else "no_go"
    return {
        "status": status,
        "reason": "ready" if status == "go" else readiness.get("reason"),
        "target_pool": "pool_a",
        "data_source": data_source or describe_database_url(),
        "eligible_days": readiness.get("eligible_days", 0),
        "pool_a_candidate_count": readiness.get("pool_total", 0),
        "pool_a_surge_count": readiness.get("pool_surge_count", 0),
        "pool_a_precision": readiness.get("pool_precision"),
        "baseline_precision": readiness.get("baseline_precision"),
        "precision_threshold": readiness.get("precision_threshold"),
        "zero_precision_streak": readiness.get("zero_precision_streak", 0),
        "readiness": readiness,
        "config_application": {
            "applied": False,
            "reason": "not_applied_by_runner",
        },
    }


def run_pool_a_bridge_readiness(
    *,
    session_factory=None,
    close_session: bool = True,
    database_url: str | None = None,
) -> dict[str, Any]:
    """Open the configured DB and run Pool A readiness with DB failure isolation."""
    from app.database import SessionLocal

    factory = session_factory or SessionLocal
    data_source = describe_database_url(database_url)
    db: Session | None = None
    try:
        db = factory()
        return build_pool_a_bridge_readiness_result(db, data_source=data_source)
    except SQLAlchemyError as exc:
        return {
            "status": "no_go",
            "reason": "database_unavailable",
            "target_pool": "pool_a",
            "data_source": data_source,
            "error_type": exc.__class__.__name__,
            "message": str(exc).splitlines()[0],
            "actionable_context": (
                "Start the configured database or set DATABASE_URL to a "
                "production-equivalent source before applying the Pool A canary."
            ),
            "config_application": {
                "applied": False,
                "reason": "readiness_not_go",
            },
        }
    finally:
        if close_session and db is not None:
            db.close()


def build_pool_a_canary_config(base_config, readiness_result: dict[str, Any], *, approved: bool):
    """Return a Pool A-only config copy only when readiness is GO and approved."""
    if readiness_result.get("status") != "go":
        return base_config
    if not approved:
        return base_config
    return base_config.model_copy(update=POOL_A_CANARY_CONFIG_PATCH)


def _prediction_count_guardrail(
    db: Session,
    *,
    lookback_days: int,
    multiplier: float,
) -> dict[str, Any]:
    rows = (
        db.query(SurgePredictionEvaluation)
        .order_by(SurgePredictionEvaluation.evaluation_date.desc())
        .limit(lookback_days + 1)
        .all()
    )
    if len(rows) < 2:
        return {
            "triggered": False,
            "reason": "insufficient_history",
            "current_predicted_count": rows[0].predicted_count if rows else None,
            "baseline_average": None,
            "threshold": None,
        }

    current = int(rows[0].predicted_count or 0)
    baseline_values = [int(row.predicted_count or 0) for row in rows[1:]]
    baseline = mean(baseline_values) if baseline_values else None
    threshold = (baseline * multiplier) if baseline is not None else None
    triggered = bool(threshold is not None and current > threshold)
    return {
        "triggered": triggered,
        "current_predicted_count": current,
        "baseline_average": baseline,
        "threshold": threshold,
        "lookback_days": len(baseline_values),
        "multiplier": multiplier,
    }


def evaluate_pool_a_bridge_rollback_guardrails(
    db: Session,
    config,
    *,
    min_trading_days: int = 10,
    max_zero_precision_streak: int = 5,
    prediction_count_lookback_days: int = 14,
    prediction_count_multiplier: float = 3.0,
    pool_b_bridge_fetch_count: int = 0,
    runtime_current_sec: float | None = None,
    runtime_baseline_sec: float | None = None,
    runtime_regression_multiplier: float = 1.5,
) -> dict[str, Any]:
    """Compute Pool A canary rollback guardrails without changing config."""
    if not config.scan_universe_bridge_candidates_enabled:
        return {
            "status": "inactive",
            "recommend_rollback": False,
            "reason": "bridge_candidates_disabled",
            "triggers": [],
        }

    readiness = evaluate_bridge_activation_readiness(
        db,
        target_pool="pool_a",
        min_trading_days=min_trading_days,
        max_zero_precision_streak=max_zero_precision_streak - 1,
    )

    current_zero_streak = 0
    for day in readiness.get("daily", []):
        precision = day["pools"]["pool_a"]["precision"]
        if precision == 0.0:
            current_zero_streak += 1
        else:
            break

    triggers: list[str] = []
    precision = readiness.get("pool_precision")
    threshold = readiness.get("precision_threshold")
    if precision is not None and threshold is not None and precision < threshold:
        triggers.append("pool_a_precision_below_threshold")
    if current_zero_streak >= max_zero_precision_streak:
        triggers.append("pool_a_zero_precision_streak")
    if pool_b_bridge_fetch_count > 0:
        triggers.append("pool_b_bridge_fetch_detected")

    prediction_guardrail = _prediction_count_guardrail(
        db,
        lookback_days=prediction_count_lookback_days,
        multiplier=prediction_count_multiplier,
    )
    if prediction_guardrail["triggered"]:
        triggers.append("prediction_count_spike")

    runtime_guardrail = {
        "triggered": False,
        "current_sec": runtime_current_sec,
        "baseline_sec": runtime_baseline_sec,
        "threshold_sec": None,
        "multiplier": runtime_regression_multiplier,
    }
    if runtime_current_sec is not None and runtime_baseline_sec:
        runtime_guardrail["threshold_sec"] = (
            runtime_baseline_sec * runtime_regression_multiplier
        )
        if runtime_current_sec > runtime_guardrail["threshold_sec"]:
            runtime_guardrail["triggered"] = True
            triggers.append("scheduler_runtime_regression")

    return {
        "status": "rollback_recommended" if triggers else "ok",
        "recommend_rollback": bool(triggers),
        "triggers": triggers,
        "target_pool": "pool_a",
        "pool_a_precision": precision,
        "precision_threshold": threshold,
        "current_zero_precision_streak": current_zero_streak,
        "prediction_count_guardrail": prediction_guardrail,
        "runtime_guardrail": runtime_guardrail,
        "pool_b_bridge_fetch_count": pool_b_bridge_fetch_count,
        "readiness": readiness,
        "rollback_config": {"scan_universe_bridge_candidates_enabled": False},
    }
