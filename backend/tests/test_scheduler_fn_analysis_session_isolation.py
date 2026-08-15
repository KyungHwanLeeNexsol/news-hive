"""Regression test for the silent miss_analysis_json failure in
_run_surge_verify_predictions()'s FN 분석 block.

Reproduces the exact production symptom: SurgePredictionEvaluation rows
persisted correctly (precision/recall/f1/false_negative) while
miss_analysis_json stays NULL for evaluation_date 2026-08-11..14.

Root cause: scheduler.py's `diagnose_non_scannable_causes` and
`check_horizon_transition_readiness` blocks (running between the core
evaluation commit and the FN 분석 block) do NOT call db.rollback() in their
except handlers, unlike every other isolated block in the same function
(gate-attribution, SPEC-AI-116 shadow detector pack, and the FN 분석 block
itself all correctly call db.rollback()). If either block hits a genuine
DB-level error (a flush failure, or on PostgreSQL specifically any aborted
statement), the session is left requiring rollback() before reuse. The very
next thing to run — the FN 분석 block — then fails on its first query,
gets caught by ITS OWN (correct) except handler, and silently swallows the
failure, leaving miss_analysis_json NULL even though it never got a chance
to run its real logic.

This test uses a NOT NULL constraint violation (dialect-independent —
enforced identically by SQLite and PostgreSQL at flush time) rather than a
raw "table does not exist" error, so it reproduces deterministically without
a live PostgreSQL instance.
"""

from __future__ import annotations

import logging
from datetime import date
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.sector import Sector
from app.models.stock import Stock
from app.models.surge_actual_outcome import SurgeActualOutcome
from app.models.surge_prediction_evaluation import SurgePredictionEvaluation


def _make_production_shaped_session() -> Session:
    """Mirrors app.database.SessionLocal (sessionmaker bound to an Engine,
    each session owning its own connection/transaction lifecycle) instead of
    this repo's `db` fixture, which binds a session directly to a
    pre-opened connection-level transaction — a pattern that has its own
    commit/rollback quirks unrelated to the production bug under test here."""
    from tests.conftest import _patch_array_for_sqlite

    _patch_array_for_sqlite()
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)()


def _make_stock(db: Session, code: str) -> Stock:
    sector = Sector(name=f"FNREPRO4_{code}", is_custom=False)
    db.add(sector)
    db.flush()
    stock = Stock(stock_code=code, name=f"FNREPRO4_{code}", sector_id=sector.id, market="KOSPI")
    db.add(stock)
    db.flush()
    return stock


def _poison_session_then_raise(db: Session):
    """Simulates a genuine DB-level failure inside a sibling block: a NOT
    NULL violation at flush time, mirroring what a real query/write bug (or,
    on PostgreSQL, any aborted statement) would leave behind."""
    try:
        db.add(Stock(stock_code="POISON", name="poison", sector_id=None))
        db.flush()
    except Exception:
        pass  # the sibling block's own internal handling, if any
    raise RuntimeError("boom (readiness check failed)")


class TestFnAnalysisSurvivesSiblingBlockDbError:
    def test_miss_analysis_json_is_still_populated(self, monkeypatch, caplog) -> None:
        import app.services.scheduler as scheduler_module

        db = _make_production_shaped_session()
        today = date.today()
        stock = _make_stock(db, "900101")
        db.add(
            SurgeActualOutcome(
                trading_date=today,
                stock_code=stock.stock_code,
                stock_name=stock.name,
                change_rate=12.0,
                was_surge=True,
                high_change_rate=13.0,
                market="KOSPI",
            )
        )
        db.commit()

        monkeypatch.setattr(scheduler_module, "SessionLocal", lambda: db)
        monkeypatch.setattr(scheduler_module, "_is_kr_market_open", lambda: True)

        with (
            patch(
                "app.services.surge_horizon_readiness_service."
                "check_horizon_transition_readiness",
                side_effect=lambda db_: _poison_session_then_raise(db_),
            ),
            patch(
                "app.services.surge_evaluation_service.analyze_misses_with_llm",
                return_value="STUB_ANALYSIS_RESULT",
            ),
            caplog.at_level(logging.WARNING, logger="app.services.scheduler"),
        ):
            scheduler_module._run_surge_verify_predictions()

        row = (
            db.query(SurgePredictionEvaluation)
            .filter(SurgePredictionEvaluation.evaluation_date == today)
            .first()
        )
        assert row is not None
        assert row.false_negative == 1

        fn_failure_logs = [
            r for r in caplog.records if "FN 분석 실패" in r.message
        ]
        assert not fn_failure_logs, (
            "FN 분석 block should not fail just because an unrelated sibling "
            "block hit a DB error — this is exactly the production symptom "
            "(miss_analysis_json stays NULL for 2026-08-11..14)."
        )
        assert row.miss_analysis_json == "STUB_ANALYSIS_RESULT"
