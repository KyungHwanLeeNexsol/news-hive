"""SPEC-AI-113 acceptance tests."""

from __future__ import annotations

import json
from datetime import date as _date
from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models.disclosure import Disclosure
from app.models.fund_signal import FundSignal
from app.models.surge_actual_outcome import SurgeActualOutcome
from app.models.surge_bridge_shadow_candidate import SurgeBridgeShadowCandidate
from app.models.surge_prediction_evaluation import SurgePredictionEvaluation
from app.services.surge_bridge_readiness_service import (
    build_pool_a_bridge_readiness_result,
    build_pool_a_canary_config,
    describe_database_url,
    evaluate_pool_a_bridge_rollback_guardrails,
    run_pool_a_bridge_readiness,
)
from app.services.surge_detector import generate_scan_universe_bridge_candidates
from app.services.surge_trading_service import _get_prev_business_day
from app.surge_config.surge_settings import get_surge_config


def _add_shadow_candidate(
    db: Session,
    trading_date: _date,
    stock_code: str,
    entry_pool: str = "pool_a",
    bridge_score: float = 0.8,
) -> None:
    db.add(
        SurgeBridgeShadowCandidate(
            trading_date=trading_date,
            stock_code=stock_code,
            entry_pool=entry_pool,
            bridge_score=bridge_score,
        )
    )


def _add_actual_outcome(
    db: Session,
    trading_date: _date,
    stock_code: str,
    *,
    was_surge: bool,
) -> None:
    db.add(
        SurgeActualOutcome(
            trading_date=trading_date,
            stock_code=stock_code,
            stock_name=f"SPEC113_{stock_code}",
            change_rate=12.0 if was_surge else 1.0,
            was_surge=was_surge,
            market="KOSPI",
        )
    )


def _add_evaluation(
    db: Session,
    trading_date: _date,
    *,
    precision: float | None = 0.2,
    predicted_count: int = 10,
) -> None:
    db.add(
        SurgePredictionEvaluation(
            evaluation_date=trading_date,
            predicted_count=predicted_count,
            actual_surge_count=5,
            true_positive=2,
            false_positive=8,
            false_negative=3,
            precision=precision,
            recall=0.4,
            f1_score=0.2667,
        )
    )


def _seed_readiness_day(
    db: Session,
    trading_date: _date,
    idx: int,
    *,
    pool_a_surge: bool,
    baseline_precision: float = 0.2,
    predicted_count: int = 10,
) -> None:
    pool_a_code = f"113{idx:03d}"
    _add_shadow_candidate(db, trading_date, pool_a_code, "pool_a")
    _add_actual_outcome(db, trading_date, pool_a_code, was_surge=pool_a_surge)
    _add_evaluation(
        db,
        trading_date,
        precision=baseline_precision,
        predicted_count=predicted_count,
    )


class TestReadinessRunner:
    def test_database_url_identity_hides_credentials(self):
        identity = describe_database_url(
            "postgresql://user:secret@prod.example.com:5432/news_hive?sslmode=require"
        )

        rendered = json.dumps(identity)
        assert identity == {
            "scheme": "postgresql",
            "host": "prod.example.com",
            "port": 5432,
            "database": "news_hive",
        }
        assert "secret" not in rendered
        assert "user" not in rendered

    def test_database_unavailable_returns_no_go_without_config_change(self):
        def _broken_factory():
            raise OperationalError("select 1", {}, Exception("connection refused"))

        result = run_pool_a_bridge_readiness(
            session_factory=_broken_factory,
            database_url="postgresql://postgres:secret@localhost:5432/news_hive",
        )
        cfg = get_surge_config()

        assert result["status"] == "no_go"
        assert result["reason"] == "database_unavailable"
        assert result["config_application"]["applied"] is False
        assert cfg.scan_universe_bridge_candidates_enabled is False

    def test_go_result_includes_required_readiness_fields(self, db: Session):
        base = _date(2026, 8, 1)
        for idx in range(10):
            _seed_readiness_day(
                db,
                base + timedelta(days=idx),
                idx,
                pool_a_surge=True,
                baseline_precision=0.2,
            )
        db.flush()

        result = build_pool_a_bridge_readiness_result(
            db,
            data_source={"scheme": "sqlite", "database": ":memory:"},
        )

        assert result["status"] == "go"
        assert result["eligible_days"] == 10
        assert result["pool_a_candidate_count"] == 10
        assert result["pool_a_precision"] == 1.0
        assert result["baseline_precision"] == 0.2
        assert result["zero_precision_streak"] == 0


class TestPoolAOnlyConfig:
    def test_no_go_readiness_does_not_enable_bridge_even_when_approved(self):
        base = get_surge_config().model_copy(
            update={"scan_universe_bridge_candidates_enabled": False}
        )

        cfg = build_pool_a_canary_config(
            base,
            {"status": "no_go", "reason": "database_unavailable"},
            approved=True,
        )

        assert cfg.scan_universe_bridge_candidates_enabled is False

    def test_go_and_approval_builds_pool_a_only_config(self):
        base = get_surge_config().model_copy(
            update={"scan_universe_bridge_candidates_enabled": False}
        )

        cfg = build_pool_a_canary_config(base, {"status": "go"}, approved=True)

        assert cfg.scan_universe_bridge_candidates_enabled is True
        assert cfg.scan_universe_bridge_pool_b_enabled is False
        assert cfg.scan_universe_bridge_max_candidates == 5
        assert cfg.scan_universe_bridge_pool_limits == {
            "pool_a": 5,
            "pool_b": 0,
            "pool_c": 0,
        }
        assert cfg.scan_universe_bridge_shadow_enabled is True

    def test_pool_a_only_config_blocks_pool_b_pool_c_and_pool_d(
        self,
        db: Session,
        make_stock,
    ):
        cfg = build_pool_a_canary_config(
            get_surge_config(),
            {"status": "go"},
            approved=True,
        )
        pool_a_code = "113900"
        make_stock(name="SPEC113_POOL_A", stock_code=pool_a_code)
        db.add(
            Disclosure(
                corp_code="AI113A01",
                corp_name="SPEC113_POOL_A",
                stock_code=pool_a_code,
                report_name="SPEC-AI-113 Pool A disclosure",
                rcept_no="AI113A000000001",
                rcept_dt=_date.today().strftime("%Y%m%d"),
                url="https://dart.fss.or.kr/spec113/a",
                impact_score=90.0,
            )
        )
        db.flush()

        with patch(
            "app.services.naver_finance.fetch_stock_price_history_batch_sync"
        ) as batch_mock:
            result = generate_scan_universe_bridge_candidates(
                db,
                cfg,
                universe_codes=[pool_a_code, "113901", "113902", "113903"],
                entry_pool_map={
                    pool_a_code: "pool_a",
                    "113901": "pool_b",
                    "113902": "pool_c",
                    "113903": "pool_d",
                },
                merged={},
            )

        assert [candidate.stock_code for candidate in result] == [pool_a_code]
        assert {candidate.entry_pool for candidate in result} == {"pool_a"}
        batch_mock.assert_not_called()


class TestRollbackMonitor:
    def test_five_zero_precision_days_recommend_rollback(self, db: Session):
        base = _date(2026, 8, 1)
        for idx in range(5):
            _seed_readiness_day(
                db,
                base + timedelta(days=idx),
                idx,
                pool_a_surge=False,
                baseline_precision=0.2,
                predicted_count=5,
            )
        db.flush()
        cfg = get_surge_config().model_copy(
            update={"scan_universe_bridge_candidates_enabled": True}
        )

        result = evaluate_pool_a_bridge_rollback_guardrails(
            db,
            cfg,
            min_trading_days=5,
            max_zero_precision_streak=5,
        )

        assert result["recommend_rollback"] is True
        assert result["status"] == "rollback_recommended"
        assert "pool_a_zero_precision_streak" in result["triggers"]
        assert result["rollback_config"] == {
            "scan_universe_bridge_candidates_enabled": False
        }


class TestBridgeCountObservability:
    def test_evaluation_and_history_include_bridge_candidate_counts(
        self,
        client,
        db: Session,
        make_stock,
    ):
        evaluation_date = _date(2026, 8, 10)
        signal_date = _get_prev_business_day(evaluation_date)
        stock = make_stock(name="SPEC113_BRIDGE", stock_code="113990")
        db.add(
            FundSignal(
                stock_id=stock.id,
                signal="buy",
                confidence=0.8,
                reasoning="SPEC-AI-113 bridge count",
                signal_type="surge_candidate",
                surge_metadata=json.dumps(
                    {"surge_basis": ["scan_universe_bridge", "pool_a"]},
                    ensure_ascii=False,
                ),
                created_at=datetime.combine(signal_date, datetime.min.time()).replace(
                    hour=15,
                    minute=20,
                ),
            )
        )
        _add_evaluation(db, evaluation_date, precision=0.5, predicted_count=1)
        db.commit()

        evaluation_response = client.get("/api/surge-trading/evaluation?days=1")
        history_response = client.get("/api/surge-trading/prediction-history?days=1")

        assert evaluation_response.status_code == 200
        evaluation_row = evaluation_response.json()[0]
        assert evaluation_row["bridge_candidate_count"] == 1
        assert evaluation_row["bridge_pool_a_candidate_count"] == 1
        assert evaluation_row["bridge_candidate_count_by_pool"]["pool_a"] == 1
        assert evaluation_row["market_recall"] is not None
        assert "scannable_recall" in evaluation_row
        assert "coverage" in evaluation_row
        assert "recall_basis" in evaluation_row

        assert history_response.status_code == 200
        history_row = history_response.json()[0]
        assert history_row["bridge_candidate_count"] == 1
        assert history_row["bridge_pool_a_candidate_count"] == 1
        assert history_row["bridge_candidate_count_by_pool"]["pool_a"] == 1
        assert "market_recall" in history_row
        assert "scannable_recall" in history_row
        assert "coverage" in history_row
        assert "recall_basis" in history_row
