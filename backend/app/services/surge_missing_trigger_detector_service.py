"""SPEC-AI-116: missing trigger detector pack, shadow-first."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from statistics import mean
from typing import Any

from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from app.models.disclosure import Disclosure
from app.models.news import NewsArticle
from app.models.news_relation import NewsStockRelation
from app.models.stock import Stock
from app.models.surge_actual_outcome import SurgeActualOutcome
from app.models.surge_missing_trigger_shadow_candidate import (
    SurgeMissingTriggerShadowCandidate,
)
from app.models.surge_prediction_evaluation import SurgePredictionEvaluation
from app.services.surge_absent_attribution_service import (
    CONTRACT_MNA_KEYWORDS,
    generate_absent_miss_attribution_report,
)
from app.services.surge_trading_service import _get_prev_business_day

logger = logging.getLogger(__name__)

FAMILY_CONTRACT_MNA = "contract_mna"
FAMILY_VOLUME_SPIKE = "volume_spike"
FAMILY_LOW_LIQUIDITY = "low_liquidity"
DETECTOR_FAMILIES: tuple[str, ...] = (
    FAMILY_CONTRACT_MNA,
    FAMILY_VOLUME_SPIKE,
    FAMILY_LOW_LIQUIDITY,
)

SOURCE_POOL_BY_FAMILY: dict[str, str] = {
    FAMILY_CONTRACT_MNA: "contract_mna_source_pool",
    FAMILY_VOLUME_SPIKE: "volume_spike_source_pool",
    FAMILY_LOW_LIQUIDITY: "low_liquidity_watchlist",
}


@dataclass(frozen=True)
class MissingTriggerShadowCandidate:
    trading_date: date
    stock_code: str
    stock_name: str
    detector_family: str
    score: float
    horizon: str
    source_pool: str
    evidence: dict[str, Any]
    risk_tags: list[str]


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _matched_keywords(text: str | None, keywords: tuple[str, ...]) -> list[str]:
    if not text:
        return []
    lower_text = text.lower()
    matches: list[str] = []
    for keyword in keywords:
        if keyword.lower() in lower_text and keyword not in matches:
            matches.append(keyword)
    return matches


def _rcept_day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:8], "%Y%m%d").date()
    except ValueError:
        return None


def _horizon_for_event(event_day: date | None, trading_date: date) -> str:
    if event_day is None:
        return "next_day"
    return "same_day" if event_day >= trading_date else "next_day"


def _score_contract_mna(impact_score: float | None, source_type: str) -> float:
    base = 0.55 if source_type == "disclosure" else 0.45
    impact_bonus = min(0.35, max(0.0, float(impact_score or 0.0)) / 250.0)
    return round(min(1.0, base + impact_bonus), 6)


def _stock_maps(db: Session, stock_codes: list[str]) -> dict[str, Stock]:
    if not stock_codes:
        return {}
    rows = db.query(Stock).filter(Stock.stock_code.in_(stock_codes)).all()
    return {row.stock_code: row for row in rows}


def _upsert_best_candidate(
    candidates: dict[tuple[str, str, str], MissingTriggerShadowCandidate],
    candidate: MissingTriggerShadowCandidate,
) -> None:
    key = (candidate.stock_code, candidate.detector_family, candidate.horizon)
    existing = candidates.get(key)
    if existing is None or candidate.score > existing.score:
        candidates[key] = candidate


def detect_contract_mna_shadow_candidates(
    db: Session,
    trading_date: date,
    *,
    stock_codes: list[str] | None = None,
) -> list[MissingTriggerShadowCandidate]:
    """Detect compact contract/M&A news/disclosure evidence in shadow mode."""
    prev_day = _get_prev_business_day(trading_date)
    wanted_dates = {prev_day.strftime("%Y%m%d"), trading_date.strftime("%Y%m%d")}
    stock_filter = set(stock_codes or [])
    result: dict[tuple[str, str, str], MissingTriggerShadowCandidate] = {}

    disclosures = (
        db.query(Disclosure)
        .filter(Disclosure.rcept_dt.in_(wanted_dates))
        .order_by(Disclosure.rcept_dt.desc(), Disclosure.id.desc())
        .all()
    )
    disclosure_stock_ids = [row.stock_id for row in disclosures if row.stock_id]
    stocks_by_id = {
        row.id: row
        for row in db.query(Stock).filter(Stock.id.in_(disclosure_stock_ids)).all()
    }
    for disclosure in disclosures:
        stock = stocks_by_id.get(disclosure.stock_id) if disclosure.stock_id else None
        stock_code = disclosure.stock_code or (stock.stock_code if stock else None)
        if not stock_code or (stock_filter and stock_code not in stock_filter):
            continue
        stock_name = stock.name if stock else disclosure.corp_name
        search_text = f"{disclosure.report_name} {disclosure.ai_summary or ''}"
        matches = _matched_keywords(search_text, CONTRACT_MNA_KEYWORDS)
        if not matches:
            continue
        event_day = _rcept_day(disclosure.rcept_dt)
        horizon = _horizon_for_event(event_day, trading_date)
        evidence = {
            "source_type": "disclosure",
            "source_id": disclosure.id,
            "rcept_no": disclosure.rcept_no,
            "rcept_dt": disclosure.rcept_dt,
            "report_name": disclosure.report_name,
            "matched_keywords": matches,
            "horizon": horizon,
            "compact": True,
        }
        _upsert_best_candidate(
            result,
            MissingTriggerShadowCandidate(
                trading_date=trading_date,
                stock_code=stock_code,
                stock_name=stock_name,
                detector_family=FAMILY_CONTRACT_MNA,
                score=_score_contract_mna(disclosure.impact_score, "disclosure"),
                horizon=horizon,
                source_pool=SOURCE_POOL_BY_FAMILY[FAMILY_CONTRACT_MNA],
                evidence=evidence,
                risk_tags=["shadow_only"],
            ),
        )

    news_rows = (
        db.query(NewsArticle, Stock)
        .join(NewsStockRelation, NewsStockRelation.news_id == NewsArticle.id)
        .join(Stock, Stock.id == NewsStockRelation.stock_id)
        .filter(
            sqlfunc.date(NewsArticle.published_at).in_([prev_day, trading_date])
        )
        .order_by(NewsArticle.published_at.desc().nullslast(), NewsArticle.id.desc())
        .limit(500)
        .all()
    )
    for article, stock in news_rows:
        if stock_filter and stock.stock_code not in stock_filter:
            continue
        search_text = f"{article.title} {article.ai_summary or ''}"
        matches = _matched_keywords(search_text, CONTRACT_MNA_KEYWORDS)
        if not matches:
            continue
        event_day = article.published_at.date() if article.published_at else None
        horizon = _horizon_for_event(event_day, trading_date)
        evidence = {
            "source_type": "news",
            "source_id": article.id,
            "title": article.title,
            "source": article.source,
            "published_at": article.published_at.isoformat()
            if article.published_at
            else None,
            "matched_keywords": matches,
            "horizon": horizon,
            "compact": True,
        }
        sentiment_bonus = 0.1 if article.sentiment in {"positive", "strong_positive"} else 0.0
        _upsert_best_candidate(
            result,
            MissingTriggerShadowCandidate(
                trading_date=trading_date,
                stock_code=stock.stock_code,
                stock_name=stock.name,
                detector_family=FAMILY_CONTRACT_MNA,
                score=round(min(1.0, _score_contract_mna(None, "news") + sentiment_bonus), 6),
                horizon=horizon,
                source_pool=SOURCE_POOL_BY_FAMILY[FAMILY_CONTRACT_MNA],
                evidence=evidence,
                risk_tags=["shadow_only"],
            ),
        )

    return sorted(result.values(), key=lambda item: item.score, reverse=True)


def _default_stock_codes(db: Session, limit: int = 300) -> list[str]:
    rows = (
        db.query(Stock.stock_code)
        .filter(Stock.stock_code.isnot(None))
        .order_by(Stock.market_cap.desc())
        .limit(limit)
        .all()
    )
    return [row.stock_code for row in rows]


def detect_volume_spike_shadow_candidates(
    db: Session,
    trading_date: date,
    *,
    stock_codes: list[str] | None = None,
    ratio_threshold: float = 3.0,
    baseline_days: int = 20,
    low_liquidity_market_cap_eok: int = 1000,
) -> list[MissingTriggerShadowCandidate]:
    """Detect abnormal volume spikes using batch price-history lookup."""
    from app.services.naver_finance import fetch_stock_price_history_batch_sync

    codes = list(dict.fromkeys(stock_codes or _default_stock_codes(db)))
    if not codes:
        return []
    stock_by_code = _stock_maps(db, codes)
    history_by_code = fetch_stock_price_history_batch_sync(codes, pages=3)

    candidates: list[MissingTriggerShadowCandidate] = []
    for code in codes:
        history = history_by_code.get(code) or []
        if len(history) < baseline_days + 1:
            continue
        current_volume = int(history[0].volume or 0)
        baseline = [int(row.volume or 0) for row in history[1:baseline_days + 1]]
        baseline = [value for value in baseline if value > 0]
        if current_volume <= 0 or len(baseline) < max(3, baseline_days // 2):
            continue
        baseline_mean = mean(baseline)
        if baseline_mean <= 0:
            continue
        ratio = current_volume / baseline_mean
        if ratio < ratio_threshold:
            continue

        stock = stock_by_code.get(code)
        market_cap = stock.market_cap if stock else None
        liquidity_guard = {
            "market_cap_eok": market_cap,
            "low_liquidity_threshold_eok": low_liquidity_market_cap_eok,
            "low_liquidity": bool(
                market_cap is not None and market_cap <= low_liquidity_market_cap_eok
            ),
        }
        risk_tags = ["shadow_only"]
        if liquidity_guard["low_liquidity"]:
            risk_tags.append("low_liquidity_guard")
        candidates.append(
            MissingTriggerShadowCandidate(
                trading_date=trading_date,
                stock_code=code,
                stock_name=stock.name if stock else code,
                detector_family=FAMILY_VOLUME_SPIKE,
                score=round(min(1.0, ratio / (ratio_threshold * 2.0)), 6),
                horizon="same_day",
                source_pool=SOURCE_POOL_BY_FAMILY[FAMILY_VOLUME_SPIKE],
                evidence={
                    "source_type": "price_history_batch",
                    "baseline_window": baseline_days,
                    "current_volume": current_volume,
                    "baseline_mean_volume": round(baseline_mean, 2),
                    "volume_ratio": round(ratio, 6),
                    "ratio_threshold": ratio_threshold,
                    "liquidity_guard": liquidity_guard,
                    "horizon": "same_day",
                },
                risk_tags=risk_tags,
            )
        )

    return sorted(candidates, key=lambda item: item.score, reverse=True)


def _liquidity_bucket(market_cap_eok: int | None) -> str:
    if market_cap_eok is None:
        return "unknown"
    if market_cap_eok <= 300:
        return "micro"
    if market_cap_eok <= 1000:
        return "small"
    return "normal"


def detect_low_liquidity_shadow_candidates(
    db: Session,
    trading_date: date,
    *,
    stock_codes: list[str] | None = None,
    market_cap_threshold_eok: int = 1000,
    min_change_rate: float = 5.0,
) -> list[MissingTriggerShadowCandidate]:
    """Classify thinly traded price moves as high-risk shadow-only candidates."""
    stock_filter = set(stock_codes or [])
    query = (
        db.query(Stock, SurgeActualOutcome)
        .join(SurgeActualOutcome, SurgeActualOutcome.stock_code == Stock.stock_code)
        .filter(
            SurgeActualOutcome.trading_date == trading_date,
            Stock.market_cap.isnot(None),
            Stock.market_cap <= market_cap_threshold_eok,
            SurgeActualOutcome.change_rate >= min_change_rate,
        )
    )
    if stock_filter:
        query = query.filter(Stock.stock_code.in_(stock_filter))

    candidates: list[MissingTriggerShadowCandidate] = []
    for stock, outcome in query.all():
        bucket = _liquidity_bucket(stock.market_cap)
        candidates.append(
            MissingTriggerShadowCandidate(
                trading_date=trading_date,
                stock_code=stock.stock_code,
                stock_name=stock.name,
                detector_family=FAMILY_LOW_LIQUIDITY,
                score=round(min(1.0, (outcome.change_rate or 0.0) / 15.0), 6),
                horizon="same_day",
                source_pool=SOURCE_POOL_BY_FAMILY[FAMILY_LOW_LIQUIDITY],
                evidence={
                    "source_type": "actual_price_move",
                    "liquidity_bucket": bucket,
                    "market_cap_eok": stock.market_cap,
                    "market_cap_threshold_eok": market_cap_threshold_eok,
                    "change_rate": outcome.change_rate,
                    "min_change_rate": min_change_rate,
                    "turnover_estimate": {
                        "available": False,
                        "reason": "no compact turnover field in current stock/outcome schema",
                    },
                    "reason": "thinly traded price move; shadow-only risk annotation",
                    "horizon": "same_day",
                },
                risk_tags=["shadow_only", "high_risk", "no_bypass"],
            )
        )

    return sorted(candidates, key=lambda item: item.score, reverse=True)


def persist_missing_trigger_shadow_candidates(
    db: Session,
    trading_date: date,
    candidates: list[MissingTriggerShadowCandidate],
    *,
    detector_families: set[str] | None = None,
) -> int:
    """Replace shadow candidates for the given date/families."""
    families = detector_families or {candidate.detector_family for candidate in candidates}
    if not families:
        return 0

    db.query(SurgeMissingTriggerShadowCandidate).filter(
        SurgeMissingTriggerShadowCandidate.trading_date == trading_date,
        SurgeMissingTriggerShadowCandidate.detector_family.in_(sorted(families)),
    ).delete(synchronize_session=False)

    rows = [
        SurgeMissingTriggerShadowCandidate(
            trading_date=candidate.trading_date,
            stock_code=candidate.stock_code,
            detector_family=candidate.detector_family,
            horizon=candidate.horizon,
            stock_name=candidate.stock_name,
            score=candidate.score,
            source_pool=candidate.source_pool,
            evidence_json=_json_dump(candidate.evidence),
            risk_tags_json=_json_dump(candidate.risk_tags),
        )
        for candidate in candidates
    ]
    if rows:
        db.add_all(rows)
    db.flush()
    db.commit()
    logger.info(
        "[missing-trigger-shadow] persisted date=%s families=%s count=%d",
        trading_date,
        sorted(families),
        len(rows),
    )
    return len(rows)


def select_missing_trigger_detector_families(
    db: Session,
    *,
    days: int = 20,
    activation_threshold: float = 0.10,
    min_eligible_days: int = 10,
) -> dict[str, Any]:
    """Select detector families for shadow measurement from SPEC-AI-112 attribution."""
    report = generate_absent_miss_attribution_report(db, days=days)
    family_status: dict[str, dict[str, Any]] = {
        family: {
            "status": "no_go",
            "reason": "insufficient_attribution_data",
            "shadow_measurement_enabled": False,
            "production_status": "no_go",
            "production_reason": "shadow_evidence_required",
            "source_pool": SOURCE_POOL_BY_FAMILY[family],
            "estimated_recall_gain": None,
        }
        for family in DETECTOR_FAMILIES
    }

    eligible_days = int(report.get("eligible_days") or 0)
    if report.get("status") != "ok" or eligible_days < min_eligible_days:
        return {
            "status": "no_go",
            "reason": "insufficient_attribution_data",
            "eligible_days": eligible_days,
            "min_eligible_days": min_eligible_days,
            "families": family_status,
            "attribution": report,
        }

    source_pools = {
        row.get("source_pool"): row
        for row in report.get("source_pools", [])
        if isinstance(row, dict)
    }
    any_shadow = False
    for family, source_pool in SOURCE_POOL_BY_FAMILY.items():
        source_row = source_pools.get(source_pool)
        if source_row is None:
            family_status[family]["reason"] = "source_pool_not_observed"
            continue
        recall_gain = source_row.get("estimated_recall_gain")
        family_status[family]["estimated_recall_gain"] = recall_gain
        family_status[family]["t1_observable_recoverable_count"] = source_row.get(
            "t1_observable_recoverable_count",
            0,
        )
        if recall_gain is not None and recall_gain >= activation_threshold:
            any_shadow = True
            family_status[family].update(
                {
                    "status": "shadow_enabled",
                    "reason": "attribution_threshold_met",
                    "shadow_measurement_enabled": True,
                }
            )
        else:
            family_status[family]["reason"] = "attribution_threshold_not_met"

    return {
        "status": "shadow_enabled" if any_shadow else "no_go",
        "reason": "attribution_threshold_met" if any_shadow else "no_family_selected",
        "eligible_days": eligible_days,
        "min_eligible_days": min_eligible_days,
        "activation_threshold": activation_threshold,
        "families": family_status,
        "attribution": report,
    }


def _explicit_config_families(config: Any) -> set[str]:
    families: set[str] = set()
    if getattr(config, "missing_trigger_contract_mna_shadow_enabled", False):
        families.add(FAMILY_CONTRACT_MNA)
    if getattr(config, "missing_trigger_volume_spike_shadow_enabled", False):
        families.add(FAMILY_VOLUME_SPIKE)
    if getattr(config, "missing_trigger_low_liquidity_shadow_enabled", False):
        families.add(FAMILY_LOW_LIQUIDITY)
    return families


def run_missing_trigger_shadow_detector_pack(
    db: Session,
    trading_date: date,
    config: Any,
    *,
    stock_codes: list[str] | None = None,
) -> dict[str, Any]:
    """Run selected missing-trigger detectors in shadow mode and persist results."""
    if not getattr(config, "missing_trigger_shadow_enabled", False):
        return {
            "status": "inactive",
            "reason": "missing_trigger_shadow_disabled",
            "trading_date": trading_date.isoformat(),
            "families": {},
            "persisted_count": 0,
        }

    selection = select_missing_trigger_detector_families(
        db,
        activation_threshold=getattr(
            config, "missing_trigger_attribution_activation_threshold", 0.10
        ),
        min_eligible_days=getattr(config, "missing_trigger_min_eligible_days", 10),
    )
    selected = _explicit_config_families(config)
    selected.update(
        family
        for family, item in selection.get("families", {}).items()
        if item.get("shadow_measurement_enabled") is True
    )
    if not selected:
        return {
            "status": "no_go",
            "reason": "no_shadow_family_selected",
            "trading_date": trading_date.isoformat(),
            "selection": selection,
            "families": {},
            "persisted_count": 0,
        }

    all_candidates: list[MissingTriggerShadowCandidate] = []
    family_counts: dict[str, int] = {}
    if FAMILY_CONTRACT_MNA in selected:
        candidates = detect_contract_mna_shadow_candidates(
            db, trading_date, stock_codes=stock_codes
        )
        all_candidates.extend(candidates)
        family_counts[FAMILY_CONTRACT_MNA] = len(candidates)
    if FAMILY_VOLUME_SPIKE in selected:
        candidates = detect_volume_spike_shadow_candidates(
            db,
            trading_date,
            stock_codes=stock_codes,
            ratio_threshold=getattr(config, "missing_trigger_volume_ratio_threshold", 3.0),
            baseline_days=getattr(config, "missing_trigger_volume_baseline_days", 20),
            low_liquidity_market_cap_eok=getattr(
                config, "missing_trigger_low_liquidity_market_cap_eok", 1000
            ),
        )
        all_candidates.extend(candidates)
        family_counts[FAMILY_VOLUME_SPIKE] = len(candidates)
    if FAMILY_LOW_LIQUIDITY in selected:
        candidates = detect_low_liquidity_shadow_candidates(
            db,
            trading_date,
            stock_codes=stock_codes,
            market_cap_threshold_eok=getattr(
                config, "missing_trigger_low_liquidity_market_cap_eok", 1000
            ),
            min_change_rate=getattr(
                config, "missing_trigger_low_liquidity_min_change_rate", 5.0
            ),
        )
        all_candidates.extend(candidates)
        family_counts[FAMILY_LOW_LIQUIDITY] = len(candidates)

    persisted = persist_missing_trigger_shadow_candidates(
        db,
        trading_date,
        all_candidates,
        detector_families=selected,
    )
    return {
        "status": "ok",
        "reason": "shadow_candidates_persisted",
        "trading_date": trading_date.isoformat(),
        "selected_families": sorted(selected),
        "families": family_counts,
        "persisted_count": persisted,
        "selection": selection,
        "production_emission": {"enabled": False, "reason": "shadow_first_guard"},
    }


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


def _shadow_lane_report(
    rows: list[SurgeMissingTriggerShadowCandidate],
    actual_positive: dict[tuple[date, str], bool],
) -> dict[str, dict[str, Any]]:
    """Summarize shadow candidates by horizon lane without touching FundSignal metrics."""
    lanes: dict[str, dict[str, Any]] = {
        "same_day": {
            "lane": "same_day",
            "shadow_candidate_count": 0,
            "expected_tp": 0,
            "expected_fp": 0,
            "production_emission": False,
            "standard_t1_predicted_set_impact": 0,
        },
        "next_day": {
            "lane": "next_day",
            "shadow_candidate_count": 0,
            "expected_tp": 0,
            "expected_fp": 0,
            "production_emission": False,
            "standard_t1_predicted_set_impact": 0,
        },
    }
    by_lane: dict[str, set[tuple[date, str]]] = {"same_day": set(), "next_day": set()}
    for row in rows:
        lane = row.horizon if row.horizon in by_lane else "next_day"
        by_lane[lane].add((row.trading_date, row.stock_code))

    for lane, pairs in by_lane.items():
        expected_tp = sum(1 for pair in pairs if actual_positive.get(pair) is True)
        lanes[lane]["shadow_candidate_count"] = len(pairs)
        lanes[lane]["expected_tp"] = expected_tp
        lanes[lane]["expected_fp"] = len(pairs) - expected_tp
    return lanes


def generate_missing_trigger_shadow_readiness_report(
    db: Session,
    *,
    days: int = 20,
    end_date: date | None = None,
    min_eligible_days: int = 10,
    max_candidate_multiplier: float = 2.0,
) -> dict[str, Any]:
    """Compute GO/NO-GO per detector family without blending families."""
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

    baseline_predicted_count = sum(int(row.predicted_count or 0) for row in evaluations)
    baseline_tp = sum(int(row.true_positive or 0) for row in evaluations)
    baseline_actual_count = sum(int(row.actual_surge_count or 0) for row in evaluations)
    baseline_precision = (
        baseline_tp / baseline_predicted_count if baseline_predicted_count else None
    )
    actual_positive = _actual_positive_map(db, evaluation_dates)

    rows = []
    if evaluation_dates:
        rows = (
            db.query(SurgeMissingTriggerShadowCandidate)
            .filter(
                SurgeMissingTriggerShadowCandidate.trading_date.in_(evaluation_dates)
            )
            .all()
        )

    by_family: dict[str, list[SurgeMissingTriggerShadowCandidate]] = {
        family: [] for family in DETECTOR_FAMILIES
    }
    for row in rows:
        by_family.setdefault(row.detector_family, []).append(row)

    family_reports: dict[str, dict[str, Any]] = {}
    for family in DETECTOR_FAMILIES:
        family_rows = by_family.get(family, [])
        shadow_days = len({row.trading_date for row in family_rows})
        added_pairs = {(row.trading_date, row.stock_code) for row in family_rows}
        added_count = len(added_pairs)
        expected_tp = sum(1 for pair in added_pairs if actual_positive.get(pair) is True)
        expected_fp = added_count - expected_tp
        added_precision = expected_tp / added_count if added_count else None
        candidate_count_multiplier = (
            (baseline_predicted_count + added_count) / baseline_predicted_count
            if baseline_predicted_count
            else None
        )
        estimated_recall_gain = (
            expected_tp / baseline_actual_count if baseline_actual_count else None
        )
        precision_gain_explicit = (
            baseline_precision is not None
            and added_precision is not None
            and added_precision > baseline_precision
        )

        status = "go"
        reason = "ready"
        if eligible_days < min_eligible_days:
            status, reason = "no_go", "insufficient_eligible_days"
        elif shadow_days < min_eligible_days:
            status, reason = "no_go", "insufficient_shadow_days"
        elif added_count == 0:
            status, reason = "no_go", "no_shadow_candidates"
        elif (
            candidate_count_multiplier is not None
            and candidate_count_multiplier > max_candidate_multiplier
            and not precision_gain_explicit
        ):
            status, reason = "no_go", "candidate_inflation_gt_2x"
        elif (
            baseline_precision is not None
            and added_precision is not None
            and added_precision < baseline_precision
        ):
            status, reason = "no_go", "precision_below_baseline"

        family_reports[family] = {
            "status": status,
            "reason": reason,
            "production_eligible": status == "go",
            "eligible_days": eligible_days,
            "shadow_days": shadow_days,
            "baseline_predicted_count": baseline_predicted_count,
            "baseline_precision": baseline_precision,
            "added_candidates": added_count,
            "expected_tp": expected_tp,
            "expected_fp": expected_fp,
            "added_precision": added_precision,
            "estimated_recall_gain": estimated_recall_gain,
            "candidate_count_multiplier": candidate_count_multiplier,
            "prediction_count_inflation": (
                added_count / baseline_predicted_count
                if baseline_predicted_count
                else None
            ),
        }

    return {
        "status": "ok" if eligible_days >= min_eligible_days else "no_go",
        "reason": "ready" if eligible_days >= min_eligible_days else "insufficient_eligible_days",
        "eligible_days": eligible_days,
        "min_eligible_days": min_eligible_days,
        "lanes": _shadow_lane_report(rows, actual_positive),
        "families": family_reports,
    }
