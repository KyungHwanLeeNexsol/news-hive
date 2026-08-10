"""SPEC-AI-114: lane-specific surge prediction metrics."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from app.models.fund_signal import FundSignal
from app.models.stock import Stock
from app.models.surge_actual_outcome import SurgeActualOutcome
from app.models.surge_prediction_evaluation import SurgePredictionEvaluation
from app.services.surge_evaluation_service import (
    _is_near_limit_up_carry_signal,
    _is_same_day_event_horizon_signal,
)

LANE_NEXT_DAY = "next_day"
LANE_SAME_DAY = "same_day"
LANE_EXCLUDED_NEAR_LIMIT = "excluded_near_limit_carry"


def classify_surge_signal_lane(surge_metadata_json: str | None) -> str:
    """Classify a surge_candidate signal into exactly one evaluation lane."""
    if _is_near_limit_up_carry_signal(surge_metadata_json):
        return LANE_EXCLUDED_NEAR_LIMIT
    if _is_same_day_event_horizon_signal(surge_metadata_json):
        return LANE_SAME_DAY
    return LANE_NEXT_DAY


def _metadata_dict(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _compact_catalyst_references(
    metadata: dict[str, Any],
    signal: FundSignal,
) -> list[dict[str, Any]]:
    allowed = {
        "type",
        "source_id",
        "news_id",
        "disclosure_id",
        "rcept_no",
        "title",
        "report_name",
        "published_at",
        "created_at",
        "matched_keywords",
        "detector",
    }
    refs: list[dict[str, Any]] = []
    if signal.disclosure_id is not None:
        refs.append({"type": "disclosure", "source_id": signal.disclosure_id})

    raw_refs = metadata.get("catalyst_refs") or metadata.get("evidence") or []
    if isinstance(raw_refs, dict):
        raw_refs = [raw_refs]
    if not isinstance(raw_refs, list):
        return refs

    for ref in raw_refs[:5]:
        if not isinstance(ref, dict):
            continue
        compact = {key: ref[key] for key in allowed if key in ref}
        if compact:
            refs.append(compact)
    return refs


def _same_day_signal_rows(db: Session, trading_date: date) -> list[tuple[FundSignal, Stock]]:
    rows = (
        db.query(FundSignal, Stock)
        .join(Stock, FundSignal.stock_id == Stock.id)
        .filter(
            FundSignal.signal_type == "surge_candidate",
            FundSignal.surge_metadata.isnot(None),
            sqlfunc.date(FundSignal.created_at) == trading_date,
        )
        .order_by(FundSignal.created_at.asc(), FundSignal.id.asc())
        .all()
    )
    return [
        (signal, stock)
        for signal, stock in rows
        if classify_surge_signal_lane(signal.surge_metadata) == LANE_SAME_DAY
    ]


def compute_same_day_lane_metrics(
    db: Session,
    trading_date: date,
) -> dict[str, Any]:
    """Compute same-day catalyst lane metrics for one trading date."""
    signal_rows = _same_day_signal_rows(db, trading_date)
    predicted_codes = {stock.stock_code for _signal, stock in signal_rows}

    actual_rows = (
        db.query(SurgeActualOutcome.stock_code)
        .filter(
            SurgeActualOutcome.trading_date == trading_date,
            SurgeActualOutcome.was_surge.is_(True),
        )
        .all()
    )
    actual_codes = {row.stock_code for row in actual_rows}
    actual_denominator = len(actual_codes) if actual_rows else None

    true_positive_codes = predicted_codes & actual_codes
    false_positive_codes = predicted_codes - actual_codes
    predicted_count = len(predicted_codes)
    true_positive = len(true_positive_codes)
    false_positive = len(false_positive_codes)

    signals: list[dict[str, Any]] = []
    seen_signal_ids: set[int] = set()
    for signal, stock in signal_rows:
        if signal.id in seen_signal_ids:
            continue
        seen_signal_ids.add(signal.id)
        metadata = _metadata_dict(signal.surge_metadata)
        basis = metadata.get("surge_basis")
        detector_names = [str(x) for x in basis] if isinstance(basis, list) else []
        signals.append(
            {
                "signal_id": signal.id,
                "stock_code": stock.stock_code,
                "stock_name": stock.name,
                "lane": LANE_SAME_DAY,
                "detector_names": detector_names,
                "created_at": signal.created_at.isoformat()
                if signal.created_at
                else None,
                "price_at_signal": signal.price_at_signal,
                "catalyst_references": _compact_catalyst_references(
                    metadata, signal
                ),
            }
        )

    return {
        "lane": LANE_SAME_DAY,
        "predicted_count": predicted_count,
        "true_positive": true_positive,
        "false_positive": false_positive,
        "precision": (
            true_positive / predicted_count if predicted_count > 0 else None
        ),
        "actual_coverage": (
            true_positive / actual_denominator
            if actual_denominator and actual_denominator > 0
            else None
        ),
        "actual_denominator": actual_denominator,
        "denominator_basis": (
            "same_trading_date_actual_surge_count"
            if actual_denominator is not None
            else None
        ),
        "true_positive_codes": sorted(true_positive_codes),
        "false_positive_codes": sorted(false_positive_codes),
        "signals": signals,
    }


def build_surge_lane_metrics(
    db: Session,
    evaluation: SurgePredictionEvaluation,
) -> dict[str, Any]:
    """Build next-day and same-day lane DTOs for API/report responses."""
    same_day = compute_same_day_lane_metrics(db, evaluation.evaluation_date)
    return {
        LANE_NEXT_DAY: {
            "lane": LANE_NEXT_DAY,
            "predicted_count": evaluation.predicted_count,
            "true_positive": evaluation.true_positive,
            "false_positive": evaluation.false_positive,
            "false_negative": evaluation.false_negative,
            "precision": evaluation.precision,
            "recall": evaluation.recall,
            "recall_basis": (
                "scannable"
                if evaluation.scannable_recall is not None
                else "market"
            ),
        },
        LANE_SAME_DAY: same_day,
    }
