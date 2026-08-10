"""SPEC-AI-114 acceptance tests for surge prediction lanes."""

from __future__ import annotations

import json
from datetime import date as _date
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.fund_signal import FundSignal
from app.models.surge_actual_outcome import SurgeActualOutcome
from app.models.surge_prediction_evaluation import SurgePredictionEvaluation
from app.services.surge_evaluation_service import (
    evaluate_surge_predictions,
    restore_predicted_codes,
)
from app.services.surge_lane_metrics_service import (
    LANE_EXCLUDED_NEAR_LIMIT,
    LANE_NEXT_DAY,
    LANE_SAME_DAY,
    classify_surge_signal_lane,
    compute_same_day_lane_metrics,
)
from app.services.surge_trading_service import _get_prev_business_day


def _dt(day: _date, hour: int = 10, minute: int = 0) -> datetime:
    return datetime.combine(day, datetime.min.time()).replace(
        hour=hour,
        minute=minute,
    )


def _add_actual(
    db: Session,
    trading_date: _date,
    stock_code: str,
    stock_name: str,
    *,
    was_surge: bool = True,
) -> None:
    db.add(
        SurgeActualOutcome(
            trading_date=trading_date,
            stock_code=stock_code,
            stock_name=stock_name,
            change_rate=12.0 if was_surge else 1.0,
            was_surge=was_surge,
            market="KOSPI",
        )
    )


def _add_eval(
    db: Session,
    trading_date: _date,
    *,
    predicted_count: int = 0,
    actual_count: int = 0,
) -> None:
    db.add(
        SurgePredictionEvaluation(
            evaluation_date=trading_date,
            predicted_count=predicted_count,
            actual_surge_count=actual_count,
            true_positive=0,
            false_positive=predicted_count,
            false_negative=actual_count,
            precision=0.0,
            recall=0.0,
            f1_score=0.0,
            scannable_recall=0.0,
            coverage=0.0,
            scannable_actual_count=0,
            total_actual_count=actual_count,
        )
    )


class TestLaneClassification:
    def test_each_signal_gets_exactly_one_lane(self):
        lanes = {
            classify_surge_signal_lane(json.dumps({"surge_basis": ["volume_breakout"]})),
            classify_surge_signal_lane(json.dumps({"horizon": "same_day"})),
            classify_surge_signal_lane(
                json.dumps({"surge_basis": ["near_limit_up_carry"]})
            ),
        }

        assert lanes == {LANE_NEXT_DAY, LANE_SAME_DAY, LANE_EXCLUDED_NEAR_LIMIT}


class TestSameDayMetrics:
    def test_same_day_metrics_return_tp_fp_precision_and_denominator(
        self,
        db: Session,
        make_stock,
        make_fund_signal,
    ):
        trading_date = _date(2026, 8, 10)
        tp_stock = make_stock(name="당일적중", stock_code="114001")
        fp_stock = make_stock(name="당일오탐", stock_code="114002")
        _add_actual(db, trading_date, tp_stock.stock_code, tp_stock.name)
        make_fund_signal(
            stock_id=tp_stock.id,
            signal_type="surge_candidate",
            surge_metadata=json.dumps({"horizon": "same_day"}),
            created_at=_dt(trading_date, 10, 5),
        )
        make_fund_signal(
            stock_id=fp_stock.id,
            signal_type="surge_candidate",
            surge_metadata=json.dumps({"horizon": "same_day"}),
            created_at=_dt(trading_date, 10, 10),
        )
        db.flush()

        metrics = compute_same_day_lane_metrics(db, trading_date)

        assert metrics["predicted_count"] == 2
        assert metrics["true_positive"] == 1
        assert metrics["false_positive"] == 1
        assert metrics["precision"] == 0.5
        assert metrics["actual_coverage"] == 1.0
        assert metrics["actual_denominator"] == 1
        assert metrics["denominator_basis"] == "same_trading_date_actual_surge_count"

    def test_same_day_signal_evidence_is_compact(self, db: Session, make_stock):
        trading_date = _date(2026, 8, 10)
        stock = make_stock(name="증거종목", stock_code="114003")
        db.add(
            FundSignal(
                stock_id=stock.id,
                signal="buy",
                confidence=0.8,
                reasoning="same-day catalyst",
                signal_type="surge_candidate",
                price_at_signal=12000,
                surge_metadata=json.dumps(
                    {
                        "horizon": "same_day",
                        "surge_basis": ["immediate_disclosure"],
                        "catalyst_refs": [
                            {
                                "type": "news",
                                "source_id": 7,
                                "title": "증거종목 당일 촉매",
                                "content": "full body must not leak",
                                "summary": "full summary must not leak",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                created_at=_dt(trading_date, 9, 30),
            )
        )
        db.flush()

        metrics = compute_same_day_lane_metrics(db, trading_date)
        evidence = metrics["signals"][0]["catalyst_references"][0]

        assert evidence["title"] == "증거종목 당일 촉매"
        assert "content" not in evidence
        assert "summary" not in evidence
        assert metrics["signals"][0]["price_at_signal"] == 12000


class TestNoT1Contamination:
    def test_standard_t1_evaluation_excludes_same_day_signals(
        self,
        db: Session,
        make_stock,
        make_fund_signal,
    ):
        trading_date = _date(2026, 8, 10)
        prev_day = _get_prev_business_day(trading_date)
        next_day_stock = make_stock(name="전일예측", stock_code="114004")
        same_day_stock = make_stock(name="당일제외", stock_code="114005")
        _add_actual(db, trading_date, next_day_stock.stock_code, next_day_stock.name)
        _add_actual(db, trading_date, same_day_stock.stock_code, same_day_stock.name)
        make_fund_signal(
            stock_id=next_day_stock.id,
            signal_type="surge_candidate",
            surge_metadata=json.dumps({"surge_basis": ["volume_breakout"]}),
            created_at=_dt(prev_day, 15, 20),
        )
        make_fund_signal(
            stock_id=same_day_stock.id,
            signal_type="surge_candidate",
            surge_metadata=json.dumps({"horizon": "same_day"}),
            created_at=_dt(prev_day, 15, 20),
        )
        db.flush()

        evaluation = evaluate_surge_predictions(db, trading_date)

        assert evaluation.predicted_count == 1
        assert evaluation.true_positive == 1
        assert evaluation.false_negative == 1
        assert restore_predicted_codes(evaluation) == [next_day_stock.stock_code]


class TestLaneApiFields:
    def test_list_detail_and_history_include_lanes_without_removing_metrics(
        self,
        client,
        db: Session,
        make_stock,
    ):
        evaluation_date = _date(2026, 8, 10)
        stock = make_stock(name="API당일", stock_code="114006")
        _add_actual(db, evaluation_date, stock.stock_code, stock.name)
        _add_eval(db, evaluation_date, predicted_count=0, actual_count=1)
        db.add(
            FundSignal(
                stock_id=stock.id,
                signal="buy",
                confidence=0.8,
                reasoning="same-day API metric",
                signal_type="surge_candidate",
                price_at_signal=9000,
                surge_metadata=json.dumps(
                    {
                        "horizon": "same_day",
                        "surge_basis": ["immediate_disclosure"],
                        "catalyst_refs": [
                            {
                                "type": "disclosure",
                                "source_id": 11,
                                "report_name": "주요사항보고",
                                "body": "full disclosure text must not leak",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                created_at=_dt(evaluation_date, 10, 0),
            )
        )
        db.commit()

        list_response = client.get("/api/surge-trading/evaluation?days=1")
        detail_response = client.get("/api/surge-trading/evaluation/2026-08-10")
        history_response = client.get("/api/surge-trading/prediction-history?days=1")

        assert list_response.status_code == 200
        assert detail_response.status_code == 200
        assert history_response.status_code == 200

        list_row = list_response.json()[0]
        detail_row = detail_response.json()
        history_row = next(
            row
            for row in history_response.json()
            if row.get("target_date") == str(evaluation_date)
        )

        for row in (list_row, detail_row, history_row):
            assert row["lanes"]["next_day"]["predicted_count"] == 0
            assert row["lanes"]["same_day"]["predicted_count"] == 1
            assert row["lanes"]["same_day"]["true_positive"] == 1
            assert row["lanes"]["same_day"]["precision"] == 1.0
            assert "market_recall" in row
            assert "scannable_recall" in row
            assert "coverage" in row
            assert "recall_basis" in row
            evidence = row["lanes"]["same_day"]["signals"][0][
                "catalyst_references"
            ][0]
            assert "body" not in evidence
