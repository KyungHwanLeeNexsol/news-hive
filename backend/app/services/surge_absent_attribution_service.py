"""SPEC-AI-112: absent actual attribution and source-pool discovery.

This module is read-only by design. It explains actual surge rows that were
absent from both the standard T-1 prediction set and the T-1 scan universe, then
summarizes which source pools would be worth building next.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import func as sqlfunc, or_
from sqlalchemy.orm import Session

from app.models.disclosure import Disclosure
from app.models.fund_signal import FundSignal
from app.models.news import NewsArticle
from app.models.news_relation import NewsStockRelation
from app.models.stock import Stock
from app.models.surge_actual_outcome import SurgeActualOutcome
from app.models.surge_prediction_evaluation import SurgePredictionEvaluation
from app.models.surge_universe_member import SurgeUniverseMember
from app.services.surge_evaluation_service import (
    _is_near_limit_up_carry_signal,
    _is_same_day_event_horizon_signal,
    restore_predicted_codes,
)
from app.services.surge_trading_service import _get_prev_business_day

PRIMARY_BUCKET_ORDER: tuple[str, ...] = (
    "contract_mna_keyword",
    "late_disclosure",
    "same_day_catalyst",
    "volume_spike_without_t1",
    "low_liquidity_price_move",
    "theme_peer_only",
    "source_absent_unknown",
)

CONTRACT_MNA_KEYWORDS: tuple[str, ...] = (
    "공급계약",
    "단일판매",
    "수주",
    "계약",
    "m&a",
    "M&A",
    "인수",
    "합병",
    "양수도",
    "경영권",
)

VOLUME_KEYWORDS: tuple[str, ...] = ("거래량", "대량거래", "상한가", "급등")
LOW_MARKET_CAP_EOK = 1000

SOURCE_POOL_PROFILES: dict[str, dict[str, str]] = {
    "contract_mna_source_pool": {
        "primary_bucket": "contract_mna_keyword",
        "data_dependency": "DART disclosure title/report metadata before the T-1 prediction cut",
        "activation_risk": "medium: broad contract keywords need issuer and materiality guards",
    },
    "same_day_disclosure_monitor": {
        "primary_bucket": "late_disclosure",
        "data_dependency": "same-day DART disclosure stream",
        "activation_risk": "high: not T-1 recall; must be routed to intraday detection",
    },
    "same_day_news_monitor": {
        "primary_bucket": "same_day_catalyst",
        "data_dependency": "same-day news-stock relation stream",
        "activation_risk": "high: not T-1 recall; requires separate horizon labeling",
    },
    "volume_spike_source_pool": {
        "primary_bucket": "volume_spike_without_t1",
        "data_dependency": "volume anomaly signals or compact volume features",
        "activation_risk": "medium-high: volume spikes are noisy without price/news context",
    },
    "low_liquidity_watchlist": {
        "primary_bucket": "low_liquidity_price_move",
        "data_dependency": "stock master market-cap/liquidity features available before T-1",
        "activation_risk": "medium-high: small caps can inflate candidate count sharply",
    },
    "theme_peer_expansion_pool": {
        "primary_bucket": "theme_peer_only",
        "data_dependency": "sector/theme peer relations and propagated theme signals",
        "activation_risk": "medium: peer propagation needs strict fan-out limits",
    },
}

T1_RECOVERABLE_POOLS: set[str] = {
    "contract_mna_source_pool",
    "volume_spike_source_pool",
    "low_liquidity_watchlist",
    "theme_peer_expansion_pool",
}


def _iso(value: datetime | date | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _to_day(value: datetime | None) -> date | None:
    if value is None:
        return None
    return value.date()


def _disclosure_day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:8], "%Y%m%d").date()
    except ValueError:
        return None


def _timing_for_day(day: date | None, trading_date: date) -> str:
    if day is None:
        return "unknown"
    if day >= trading_date:
        return "same_day"
    return "t1_observable"


def _matched_keywords(text: str | None, keywords: tuple[str, ...]) -> list[str]:
    if not text:
        return []
    lower_text = text.lower()
    matches: list[str] = []
    for keyword in keywords:
        if keyword.lower() in lower_text and keyword not in matches:
            matches.append(keyword)
    return matches


def _standard_predicted_codes(
    db: Session,
    trading_date: date,
    evaluation: SurgePredictionEvaluation,
) -> set[str]:
    restored = restore_predicted_codes(evaluation)
    if restored is not None:
        return {str(code) for code in restored}

    prev_business_day = _get_prev_business_day(trading_date)
    rows = (
        db.query(Stock.stock_code, FundSignal.surge_metadata)
        .join(FundSignal, FundSignal.stock_id == Stock.id)
        .filter(
            FundSignal.signal_type == "surge_candidate",
            FundSignal.surge_metadata.isnot(None),
            sqlfunc.date(FundSignal.created_at) == prev_business_day,
        )
        .all()
    )

    predicted_set: set[str] = set()
    for row in rows:
        if _is_near_limit_up_carry_signal(row.surge_metadata):
            continue
        if _is_same_day_event_horizon_signal(row.surge_metadata):
            continue
        predicted_set.add(row.stock_code)
    return predicted_set


def _universe_members_by_code(db: Session, prev_business_day: date) -> dict[str, str]:
    rows = (
        db.query(SurgeUniverseMember.stock_code, SurgeUniverseMember.entry_pool)
        .filter(SurgeUniverseMember.trading_date == prev_business_day)
        .all()
    )
    return {row.stock_code: row.entry_pool for row in rows}


def _stock_by_code(db: Session, stock_code: str) -> Stock | None:
    return db.query(Stock).filter(Stock.stock_code == stock_code).one_or_none()


def _news_evidence(
    db: Session,
    stock: Stock | None,
    trading_date: date,
) -> list[dict[str, Any]]:
    if stock is None:
        return []

    prev_business_day = _get_prev_business_day(trading_date)
    rows = (
        db.query(NewsArticle)
        .join(NewsStockRelation, NewsStockRelation.news_id == NewsArticle.id)
        .filter(
            NewsStockRelation.stock_id == stock.id,
            sqlfunc.date(NewsArticle.published_at).in_(
                [prev_business_day, trading_date]
            ),
        )
        .order_by(NewsArticle.published_at.desc().nullslast(), NewsArticle.id.desc())
        .limit(5)
        .all()
    )

    evidence: list[dict[str, Any]] = []
    for article in rows:
        day = _to_day(article.published_at)
        contract_matches = _matched_keywords(article.title, CONTRACT_MNA_KEYWORDS)
        volume_matches = _matched_keywords(article.title, VOLUME_KEYWORDS)
        tags: list[str] = []
        if contract_matches:
            tags.append("contract_mna_keyword")
        if volume_matches:
            tags.append("volume_keyword")
        if day == trading_date:
            tags.append("same_day_evidence")
        evidence.append(
            {
                "type": "news",
                "source_id": article.id,
                "title": article.title,
                "source": article.source,
                "published_at": _iso(article.published_at),
                "timing": _timing_for_day(day, trading_date),
                "matched_keywords": contract_matches + volume_matches,
                "tags": tags,
            }
        )
    return evidence


def _disclosure_evidence(
    db: Session,
    stock_code: str,
    stock: Stock | None,
    trading_date: date,
) -> list[dict[str, Any]]:
    prev_business_day = _get_prev_business_day(trading_date)
    wanted_dates = {
        prev_business_day.strftime("%Y%m%d"),
        trading_date.strftime("%Y%m%d"),
    }
    identity_filters = [Disclosure.stock_code == stock_code]
    if stock is not None:
        identity_filters.append(Disclosure.stock_id == stock.id)

    rows = (
        db.query(Disclosure)
        .filter(
            or_(*identity_filters),
            Disclosure.rcept_dt.in_(wanted_dates),
        )
        .order_by(Disclosure.rcept_dt.desc(), Disclosure.id.desc())
        .limit(5)
        .all()
    )

    evidence: list[dict[str, Any]] = []
    for disclosure in rows:
        day = _disclosure_day(disclosure.rcept_dt)
        matches = _matched_keywords(disclosure.report_name, CONTRACT_MNA_KEYWORDS)
        tags: list[str] = ["disclosure"]
        if matches:
            tags.append("contract_mna_keyword")
        if day == trading_date:
            tags.append("same_day_evidence")
        evidence.append(
            {
                "type": "disclosure",
                "source_id": disclosure.id,
                "rcept_no": disclosure.rcept_no,
                "report_name": disclosure.report_name,
                "rcept_dt": disclosure.rcept_dt,
                "impact_score": disclosure.impact_score,
                "timing": _timing_for_day(day, trading_date),
                "matched_keywords": matches,
                "tags": tags,
            }
        )
    return evidence


def _fund_signal_evidence(
    db: Session,
    stock: Stock | None,
    trading_date: date,
) -> list[dict[str, Any]]:
    if stock is None:
        return []

    prev_business_day = _get_prev_business_day(trading_date)
    rows = (
        db.query(FundSignal)
        .filter(
            FundSignal.stock_id == stock.id,
            FundSignal.signal_type.in_(
                [
                    "surge_candidate",
                    "volume_anomaly",
                    "sector_ripple",
                    "theme_propagation",
                    "disclosure_impact",
                    "preday_disclosure",
                ]
            ),
            sqlfunc.date(FundSignal.created_at).in_(
                [prev_business_day, trading_date]
            ),
        )
        .order_by(FundSignal.created_at.desc(), FundSignal.id.desc())
        .limit(8)
        .all()
    )

    evidence: list[dict[str, Any]] = []
    for signal in rows:
        created_day = _to_day(signal.created_at)
        tags: list[str] = []
        if signal.signal_type == "volume_anomaly":
            tags.append("volume_spike_without_t1")
        if signal.signal_type in {"sector_ripple", "theme_propagation"}:
            tags.append("theme_peer_only")
        if _is_near_limit_up_carry_signal(signal.surge_metadata):
            tags.append("evaluation_excluded_near_limit_up_carry")
        if _is_same_day_event_horizon_signal(signal.surge_metadata):
            tags.append("evaluation_excluded_same_day")
            tags.append("same_day_evidence")
        evidence.append(
            {
                "type": "fund_signal",
                "source_id": signal.id,
                "signal_type": signal.signal_type,
                "confidence": signal.confidence,
                "created_at": _iso(signal.created_at),
                "timing": _timing_for_day(created_day, trading_date),
                "tags": tags,
            }
        )
    return evidence


def _liquidity_evidence(stock: Stock | None) -> list[dict[str, Any]]:
    if stock is None or stock.market_cap is None:
        return []
    if stock.market_cap > LOW_MARKET_CAP_EOK:
        return []
    return [
        {
            "type": "liquidity",
            "market_cap_eok": stock.market_cap,
            "threshold_eok": LOW_MARKET_CAP_EOK,
            "timing": "t1_observable",
            "tags": ["low_liquidity_price_move"],
        }
    ]


def _theme_evidence(stock: Stock | None) -> list[dict[str, Any]]:
    if stock is None or not stock.keywords:
        return []
    return [
        {
            "type": "theme",
            "keywords": list(stock.keywords)[:5],
            "timing": "t1_observable",
            "tags": ["theme_peer_only"],
        }
    ]


def _collect_evidence(
    db: Session,
    stock_code: str,
    trading_date: date,
) -> tuple[Stock | None, list[dict[str, Any]]]:
    stock = _stock_by_code(db, stock_code)
    evidence: list[dict[str, Any]] = []
    evidence.extend(_disclosure_evidence(db, stock_code, stock, trading_date))
    evidence.extend(_news_evidence(db, stock, trading_date))
    evidence.extend(_fund_signal_evidence(db, stock, trading_date))
    evidence.extend(_liquidity_evidence(stock))
    evidence.extend(_theme_evidence(stock))
    return stock, evidence


def _classify_evidence(evidence: list[dict[str, Any]]) -> dict[str, Any]:
    candidate_buckets: set[str] = set()
    secondary_tags: list[str] = []
    recovery_sources: set[str] = set()

    for item in evidence:
        item_type = item.get("type")
        timing = item.get("timing")
        tags = set(item.get("tags") or [])
        for tag in tags:
            if tag not in secondary_tags:
                secondary_tags.append(tag)

        if item_type == "disclosure" and timing == "same_day":
            candidate_buckets.add("late_disclosure")

        if (
            (
                timing == "same_day"
                and item_type in {"news", "fund_signal"}
                and "evaluation_excluded_near_limit_up_carry" not in tags
            )
            or "evaluation_excluded_same_day" in tags
        ):
            candidate_buckets.add("same_day_catalyst")

        if "contract_mna_keyword" in tags and timing == "t1_observable":
            candidate_buckets.add("contract_mna_keyword")
            recovery_sources.add("contract_mna_source_pool")

        if "volume_spike_without_t1" in tags:
            candidate_buckets.add("volume_spike_without_t1")
            if timing == "t1_observable":
                recovery_sources.add("volume_spike_source_pool")

        if "low_liquidity_price_move" in tags:
            candidate_buckets.add("low_liquidity_price_move")
            recovery_sources.add("low_liquidity_watchlist")

        if "theme_peer_only" in tags:
            candidate_buckets.add("theme_peer_only")
            if timing == "t1_observable":
                recovery_sources.add("theme_peer_expansion_pool")

    primary_bucket = "source_absent_unknown"
    for bucket in PRIMARY_BUCKET_ORDER:
        if bucket in candidate_buckets:
            primary_bucket = bucket
            break

    if primary_bucket != "source_absent_unknown":
        secondary_tags = [
            tag for tag in secondary_tags if tag != primary_bucket
        ]
    secondary_tags = sorted(dict.fromkeys(secondary_tags))

    hindsight_sources = {
        SOURCE_POOL_PROFILES[pool]["primary_bucket"]: pool
        for pool in SOURCE_POOL_PROFILES
    }
    primary_source = hindsight_sources.get(primary_bucket)

    return {
        "primary_bucket": primary_bucket,
        "secondary_tags": secondary_tags,
        "t1_recoverable": bool(recovery_sources & T1_RECOVERABLE_POOLS),
        "recovery_sources": sorted(recovery_sources),
        "hindsight_source_pool": primary_source,
    }


def _empty_bucket_counts() -> dict[str, int]:
    return {bucket: 0 for bucket in PRIMARY_BUCKET_ORDER}


def analyze_absent_miss_attribution_by_date(
    db: Session,
    trading_date: date,
) -> dict[str, Any]:
    """Return absent actual miss attribution for one evaluation date.

    An absent miss is an actual surge code missing from both the standard T-1
    predicted set and the persisted T-1 scan universe.
    """
    evaluation = (
        db.query(SurgePredictionEvaluation)
        .filter(SurgePredictionEvaluation.evaluation_date == trading_date)
        .one_or_none()
    )
    if evaluation is None:
        return {
            "trading_date": trading_date.isoformat(),
            "sample_present": False,
            "reason": "missing_evaluation",
            "summary": {},
            "rows": [],
        }

    actual_rows = (
        db.query(SurgeActualOutcome)
        .filter(
            SurgeActualOutcome.trading_date == trading_date,
            SurgeActualOutcome.was_surge.is_(True),
        )
        .order_by(SurgeActualOutcome.change_rate.desc(), SurgeActualOutcome.stock_code)
        .all()
    )
    if not actual_rows:
        return {
            "trading_date": trading_date.isoformat(),
            "sample_present": False,
            "reason": "missing_actual_surge_rows",
            "summary": {
                "total_actual_surges": 0,
                "predicted_hits": 0,
                "scan_universe_covered_actuals": 0,
                "scan_universe_coverage": None,
                "absent_misses": 0,
                "bucket_counts": _empty_bucket_counts(),
                "unknown_share": None,
            },
            "rows": [],
        }

    prev_business_day = _get_prev_business_day(trading_date)
    predicted_set = _standard_predicted_codes(db, trading_date, evaluation)
    universe_by_code = _universe_members_by_code(db, prev_business_day)
    universe_set = set(universe_by_code)
    actual_codes = {row.stock_code for row in actual_rows}

    rows: list[dict[str, Any]] = []
    bucket_counts = _empty_bucket_counts()
    for actual in actual_rows:
        predicted_membership = actual.stock_code in predicted_set
        scan_universe_membership = actual.stock_code in universe_set
        if predicted_membership or scan_universe_membership:
            continue

        try:
            stock, evidence = _collect_evidence(db, actual.stock_code, trading_date)
            classification = _classify_evidence(evidence)
            stock_name = stock.name if stock is not None else actual.stock_name
            market_cap = stock.market_cap if stock is not None else None
        except Exception as exc:  # pragma: no cover - defensive isolation
            evidence = [
                {
                    "type": "attribution_error",
                    "error_type": exc.__class__.__name__,
                    "timing": "unknown",
                    "tags": ["attribution_error"],
                }
            ]
            classification = {
                "primary_bucket": "source_absent_unknown",
                "secondary_tags": ["attribution_error"],
                "t1_recoverable": False,
                "recovery_sources": [],
                "hindsight_source_pool": None,
            }
            stock_name = actual.stock_name
            market_cap = None

        primary_bucket = classification["primary_bucket"]
        bucket_counts[primary_bucket] = bucket_counts.get(primary_bucket, 0) + 1
        rows.append(
            {
                "trading_date": trading_date.isoformat(),
                "prev_business_day": prev_business_day.isoformat(),
                "stock_code": actual.stock_code,
                "stock_name": stock_name,
                "market": actual.market,
                "market_cap_eok": market_cap,
                "actual_change_rate": actual.change_rate,
                "high_change_rate": actual.high_change_rate,
                "predicted_membership": predicted_membership,
                "scan_universe_membership": scan_universe_membership,
                "entry_pool": universe_by_code.get(actual.stock_code),
                "primary_bucket": primary_bucket,
                "secondary_tags": classification["secondary_tags"],
                "t1_recoverable": classification["t1_recoverable"],
                "recovery_sources": classification["recovery_sources"],
                "hindsight_source_pool": classification["hindsight_source_pool"],
                "evidence": evidence,
            }
        )

    absent_misses = len(rows)
    predicted_hits = len(predicted_set & actual_codes)
    scan_universe_covered_actuals = len(universe_set & actual_codes)
    unknown_count = bucket_counts.get("source_absent_unknown", 0)

    return {
        "trading_date": trading_date.isoformat(),
        "prev_business_day": prev_business_day.isoformat(),
        "sample_present": True,
        "reason": "ok",
        "summary": {
            "total_actual_surges": len(actual_codes),
            "predicted_hits": predicted_hits,
            "predicted_count": len(predicted_set),
            "scan_universe_covered_actuals": scan_universe_covered_actuals,
            "scan_universe_coverage": (
                scan_universe_covered_actuals / len(actual_codes)
                if actual_codes
                else None
            ),
            "absent_misses": absent_misses,
            "bucket_counts": bucket_counts,
            "unknown_share": (
                unknown_count / absent_misses if absent_misses > 0 else None
            ),
        },
        "rows": rows,
    }


def _rank_source_pools(
    rows: list[dict[str, Any]],
    total_actual_surges: int,
) -> list[dict[str, Any]]:
    aggregate: dict[str, dict[str, Any]] = {}

    for row in rows:
        hindsight_pool = row.get("hindsight_source_pool")
        if hindsight_pool in SOURCE_POOL_PROFILES:
            item = aggregate.setdefault(
                hindsight_pool,
                {
                    "source_pool": hindsight_pool,
                    "hindsight_miss_count": 0,
                    "t1_observable_recoverable_count": 0,
                    "sample_codes": [],
                },
            )
            item["hindsight_miss_count"] += 1
            if row["stock_code"] not in item["sample_codes"]:
                item["sample_codes"].append(row["stock_code"])

        for pool in row.get("recovery_sources") or []:
            if pool not in SOURCE_POOL_PROFILES:
                continue
            item = aggregate.setdefault(
                pool,
                {
                    "source_pool": pool,
                    "hindsight_miss_count": 0,
                    "t1_observable_recoverable_count": 0,
                    "sample_codes": [],
                },
            )
            item["t1_observable_recoverable_count"] += 1
            if row["stock_code"] not in item["sample_codes"]:
                item["sample_codes"].append(row["stock_code"])

    ranked: list[dict[str, Any]] = []
    for source_pool, item in aggregate.items():
        profile = SOURCE_POOL_PROFILES[source_pool]
        t1_count = item["t1_observable_recoverable_count"]
        item.update(profile)
        item["estimated_recall_gain"] = (
            t1_count / total_actual_surges if total_actual_surges else None
        )
        item["expected_candidate_count"] = None
        item["expected_candidate_count_basis"] = (
            "not measured by SPEC-AI-112; requires a standalone source-pool "
            "candidate denominator before activation"
        )
        item["sample_codes"] = item["sample_codes"][:10]
        ranked.append(item)

    return sorted(
        ranked,
        key=lambda item: (
            -item["t1_observable_recoverable_count"],
            -item["hindsight_miss_count"],
            item["source_pool"],
        ),
    )


def generate_absent_miss_attribution_report(
    db: Session,
    *,
    days: int = 20,
    end_date: date | None = None,
) -> dict[str, Any]:
    """Generate the operator-facing SPEC-AI-112 attribution report."""
    if days <= 0:
        raise ValueError("days must be positive")

    query = db.query(SurgePredictionEvaluation.evaluation_date).order_by(
        SurgePredictionEvaluation.evaluation_date.desc()
    )
    if end_date is not None:
        query = query.filter(SurgePredictionEvaluation.evaluation_date <= end_date)

    candidate_dates = [row.evaluation_date for row in query.limit(days * 5 + 20).all()]
    daily: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []
    for candidate_date in candidate_dates:
        result = analyze_absent_miss_attribution_by_date(db, candidate_date)
        if not result["sample_present"]:
            continue
        daily.append(result)
        all_rows.extend(result["rows"])
        if len(daily) >= days:
            break

    if not daily:
        return {
            "status": "no_eligible_days",
            "requested_days": days,
            "eligible_days": 0,
            "daily": [],
            "summary": {
                "total_actual_surges": 0,
                "predicted_hits": 0,
                "scan_universe_covered_actuals": 0,
                "scan_universe_coverage": None,
                "absent_misses": 0,
                "bucket_counts": _empty_bucket_counts(),
                "unknown_share": None,
            },
            "source_pools": [],
        }

    total_actual = sum(day["summary"]["total_actual_surges"] for day in daily)
    predicted_hits = sum(day["summary"]["predicted_hits"] for day in daily)
    universe_hits = sum(
        day["summary"]["scan_universe_covered_actuals"] for day in daily
    )
    absent_misses = sum(day["summary"]["absent_misses"] for day in daily)
    bucket_counts = _empty_bucket_counts()
    for day in daily:
        for bucket, count in day["summary"]["bucket_counts"].items():
            bucket_counts[bucket] = bucket_counts.get(bucket, 0) + count

    unknown_count = bucket_counts.get("source_absent_unknown", 0)
    return {
        "status": "ok",
        "requested_days": days,
        "eligible_days": len(daily),
        "date_range": {
            "start": daily[-1]["trading_date"],
            "end": daily[0]["trading_date"],
        },
        "summary": {
            "total_actual_surges": total_actual,
            "predicted_hits": predicted_hits,
            "scan_universe_covered_actuals": universe_hits,
            "scan_universe_coverage": (
                universe_hits / total_actual if total_actual else None
            ),
            "absent_misses": absent_misses,
            "bucket_counts": bucket_counts,
            "unknown_share": (
                unknown_count / absent_misses if absent_misses > 0 else None
            ),
        },
        "source_pools": _rank_source_pools(all_rows, total_actual),
        "daily": daily,
    }
