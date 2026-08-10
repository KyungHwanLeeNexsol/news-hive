"""SPEC-AI-112 acceptance tests for absent actual attribution."""

from __future__ import annotations

import json
from datetime import date, datetime, time

from sqlalchemy.orm import Session

from app.models.fund_signal import FundSignal
from app.models.stock import Stock
from app.models.surge_actual_outcome import SurgeActualOutcome
from app.models.surge_prediction_evaluation import SurgePredictionEvaluation
from app.models.surge_universe_member import SurgeUniverseMember
from app.services.surge_absent_attribution_service import (
    analyze_absent_miss_attribution_by_date,
    generate_absent_miss_attribution_report,
)
from app.services.surge_trading_service import _get_prev_business_day


def _dt(day: date, hour: int = 15, minute: int = 20) -> datetime:
    return datetime.combine(day, time(hour=hour, minute=minute))


def _add_actual(
    db: Session,
    trading_date: date,
    stock: Stock,
    *,
    change_rate: float = 12.5,
) -> None:
    db.add(
        SurgeActualOutcome(
            trading_date=trading_date,
            stock_code=stock.stock_code,
            stock_name=stock.name,
            change_rate=change_rate,
            was_surge=True,
            high_change_rate=change_rate + 2.0,
            market=stock.market or "KOSPI",
        )
    )


def _add_eval(
    db: Session,
    trading_date: date,
    *,
    predicted_codes: list[str] | None,
    actual_count: int,
) -> None:
    predicted_count = len(predicted_codes or [])
    true_positive = 0
    db.add(
        SurgePredictionEvaluation(
            evaluation_date=trading_date,
            predicted_count=predicted_count,
            actual_surge_count=actual_count,
            true_positive=true_positive,
            false_positive=predicted_count,
            false_negative=actual_count,
            precision=0.0,
            recall=0.0,
            f1_score=0.0,
            predicted_codes_json=(
                json.dumps(predicted_codes, ensure_ascii=False)
                if predicted_codes is not None
                else None
            ),
        )
    )


def _add_universe_member(
    db: Session,
    trading_date: date,
    stock_code: str,
    entry_pool: str = "pool_a",
) -> None:
    db.add(
        SurgeUniverseMember(
            trading_date=trading_date,
            stock_code=stock_code,
            entry_pool=entry_pool,
        )
    )


class TestAbsentMissLedger:
    def test_returns_only_actual_codes_absent_from_prediction_and_t1_universe(
        self,
        db: Session,
        make_stock,
    ):
        trading_date = date(2026, 8, 10)
        prev_day = _get_prev_business_day(trading_date)
        predicted = make_stock(name="예측종목", stock_code="112001")
        in_universe = make_stock(name="유니버스종목", stock_code="112002")
        absent = make_stock(name="부재종목", stock_code="112003")

        for stock in (predicted, in_universe, absent):
            _add_actual(db, trading_date, stock)
        _add_eval(
            db,
            trading_date,
            predicted_codes=[predicted.stock_code],
            actual_count=3,
        )
        _add_universe_member(db, prev_day, in_universe.stock_code, "pool_a")
        db.flush()

        result = analyze_absent_miss_attribution_by_date(db, trading_date)

        assert result["sample_present"] is True
        assert [row["stock_code"] for row in result["rows"]] == [absent.stock_code]
        row = result["rows"][0]
        assert row["predicted_membership"] is False
        assert row["scan_universe_membership"] is False

    def test_snapshot_missing_fallback_reuses_standard_exclusion_rules(
        self,
        db: Session,
        make_stock,
        make_fund_signal,
    ):
        trading_date = date(2026, 8, 10)
        prev_day = _get_prev_business_day(trading_date)
        standard = make_stock(name="표준신호", stock_code="112004")
        excluded = make_stock(name="당일지평제외", stock_code="112005")

        _add_actual(db, trading_date, standard)
        _add_actual(db, trading_date, excluded)
        _add_eval(db, trading_date, predicted_codes=None, actual_count=2)
        make_fund_signal(
            stock_id=standard.id,
            signal_type="surge_candidate",
            surge_metadata=json.dumps({"surge_basis": ["volume_breakout"]}),
            created_at=_dt(prev_day),
        )
        make_fund_signal(
            stock_id=excluded.id,
            signal_type="surge_candidate",
            surge_metadata=json.dumps({"horizon": "same_day"}),
            created_at=_dt(prev_day),
        )
        db.flush()

        result = analyze_absent_miss_attribution_by_date(db, trading_date)

        assert [row["stock_code"] for row in result["rows"]] == [excluded.stock_code]
        assert result["rows"][0]["primary_bucket"] == "same_day_catalyst"
        assert "evaluation_excluded_same_day" in result["rows"][0]["secondary_tags"]


class TestReasonTaxonomy:
    def test_same_day_news_is_same_day_catalyst_and_not_t1_recoverable(
        self,
        db: Session,
        make_stock,
        make_news,
        make_news_relation,
    ):
        trading_date = date(2026, 8, 10)
        stock = make_stock(name="당일뉴스종목", stock_code="112006")
        _add_actual(db, trading_date, stock)
        _add_eval(db, trading_date, predicted_codes=[], actual_count=1)
        article = make_news(
            title="당일뉴스종목 신제품 이슈로 급등",
            summary="full summary must not be copied",
            content="full article body must not be copied",
            published_at=_dt(trading_date, hour=10, minute=5),
        )
        make_news_relation(news_id=article.id, stock_id=stock.id)
        db.flush()

        result = analyze_absent_miss_attribution_by_date(db, trading_date)
        row = result["rows"][0]

        assert row["primary_bucket"] == "same_day_catalyst"
        assert row["t1_recoverable"] is False
        assert all("content" not in item for item in row["evidence"])
        assert all("summary" not in item for item in row["evidence"])

    def test_contract_mna_keyword_before_t1_cut_counts_as_recoverable(
        self,
        db: Session,
        make_stock,
        make_disclosure,
    ):
        trading_date = date(2026, 8, 10)
        prev_day = _get_prev_business_day(trading_date)
        stock = make_stock(name="계약공시종목", stock_code="112007")
        _add_actual(db, trading_date, stock)
        _add_eval(db, trading_date, predicted_codes=[], actual_count=1)
        make_disclosure(
            stock_id=stock.id,
            stock_code=stock.stock_code,
            corp_name=stock.name,
            report_name="대규모 공급계약 체결",
            rcept_dt=prev_day.strftime("%Y%m%d"),
        )
        db.flush()

        result = analyze_absent_miss_attribution_by_date(db, trading_date)
        row = result["rows"][0]
        report = generate_absent_miss_attribution_report(db, days=1)

        assert row["primary_bucket"] == "contract_mna_keyword"
        assert row["t1_recoverable"] is True
        assert row["recovery_sources"] == ["contract_mna_source_pool"]
        assert report["source_pools"][0]["source_pool"] == "contract_mna_source_pool"
        assert report["source_pools"][0]["t1_observable_recoverable_count"] == 1

    def test_multiple_buckets_choose_one_primary_and_preserve_secondary_tags(
        self,
        db: Session,
        make_stock,
        make_disclosure,
        make_news,
        make_news_relation,
    ):
        trading_date = date(2026, 8, 10)
        prev_day = _get_prev_business_day(trading_date)
        stock = make_stock(name="복합증거종목", stock_code="112008")
        _add_actual(db, trading_date, stock)
        _add_eval(db, trading_date, predicted_codes=[], actual_count=1)
        make_disclosure(
            stock_id=stock.id,
            stock_code=stock.stock_code,
            corp_name=stock.name,
            report_name="단일판매 공급계약 체결",
            rcept_dt=prev_day.strftime("%Y%m%d"),
        )
        article = make_news(
            title="복합증거종목 장중 급등",
            published_at=_dt(trading_date, hour=9, minute=40),
        )
        make_news_relation(news_id=article.id, stock_id=stock.id)
        db.flush()

        result = analyze_absent_miss_attribution_by_date(db, trading_date)
        row = result["rows"][0]

        assert row["primary_bucket"] == "contract_mna_keyword"
        assert "same_day_evidence" in row["secondary_tags"]
        assert sum(
            1
            for key in (
                "contract_mna_keyword",
                "late_disclosure",
                "same_day_catalyst",
                "volume_spike_without_t1",
                "low_liquidity_price_move",
                "theme_peer_only",
                "source_absent_unknown",
            )
            if row["primary_bucket"] == key
        ) == 1


class TestOperatorReport:
    def test_no_eligible_days_returns_clear_status(self, db: Session):
        report = generate_absent_miss_attribution_report(db, days=20)

        assert report["status"] == "no_eligible_days"
        assert report["eligible_days"] == 0
        assert report["source_pools"] == []

    def test_report_execution_does_not_change_fundsignal_rows_or_emitted_set(
        self,
        db: Session,
        make_stock,
        make_fund_signal,
        make_disclosure,
    ):
        trading_date = date(2026, 8, 10)
        prev_day = _get_prev_business_day(trading_date)
        stock = make_stock(name="무변경검증종목", stock_code="112009")
        _add_actual(db, trading_date, stock)
        _add_eval(db, trading_date, predicted_codes=[], actual_count=1)
        make_disclosure(
            stock_id=stock.id,
            stock_code=stock.stock_code,
            corp_name=stock.name,
            report_name="공급계약 체결",
            rcept_dt=prev_day.strftime("%Y%m%d"),
        )
        make_fund_signal(
            stock_id=stock.id,
            signal_type="surge_candidate",
            surge_metadata=json.dumps({"surge_basis": ["volume_breakout"]}),
            created_at=_dt(prev_day),
        )
        db.flush()
        before_count = db.query(FundSignal).count()
        before_surge_candidate_ids = [
            row.id
            for row in db.query(FundSignal)
            .filter(FundSignal.signal_type == "surge_candidate")
            .order_by(FundSignal.id)
            .all()
        ]

        generate_absent_miss_attribution_report(db, days=1)

        after_count = db.query(FundSignal).count()
        after_surge_candidate_ids = [
            row.id
            for row in db.query(FundSignal)
            .filter(FundSignal.signal_type == "surge_candidate")
            .order_by(FundSignal.id)
            .all()
        ]
        assert after_count == before_count
        assert after_surge_candidate_ids == before_surge_candidate_ids

    def test_report_includes_required_summary_fields_and_ranked_source_pools(
        self,
        db: Session,
        make_stock,
        make_disclosure,
    ):
        trading_date = date(2026, 8, 10)
        prev_day = _get_prev_business_day(trading_date)
        stock = make_stock(name="리포트종목", stock_code="112010")
        _add_actual(db, trading_date, stock)
        _add_eval(db, trading_date, predicted_codes=[], actual_count=1)
        make_disclosure(
            stock_id=stock.id,
            stock_code=stock.stock_code,
            corp_name=stock.name,
            report_name="경영권 양수도 계약",
            rcept_dt=prev_day.strftime("%Y%m%d"),
        )
        db.flush()

        report = generate_absent_miss_attribution_report(db, days=1)
        summary = report["summary"]

        assert report["status"] == "ok"
        assert summary["total_actual_surges"] == 1
        assert summary["predicted_hits"] == 0
        assert summary["scan_universe_coverage"] == 0.0
        assert summary["absent_misses"] == 1
        assert summary["bucket_counts"]["contract_mna_keyword"] == 1
        assert summary["unknown_share"] == 0.0
        assert report["source_pools"][0]["source_pool"] == "contract_mna_source_pool"
        assert "expected_candidate_count" in report["source_pools"][0]
