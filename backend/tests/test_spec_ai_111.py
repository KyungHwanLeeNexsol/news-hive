"""SPEC-AI-111 acceptance tests.

- Readiness gate: Pool A shadow precision is compared to same-period non-null
  SurgePredictionEvaluation.precision, with Pool C kept separate.
- Bridge canary: Pool A-only limits keep Pool C/B/D out and preserve attribution.
- Metric compatibility: SPEC-AI-110 market/scannable recall fields remain split.
"""

from __future__ import annotations

import contextlib
import json
import logging
from datetime import date as _date
from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy.orm import Session

from app.models.disclosure import Disclosure
from app.models.fund_signal import FundSignal
from app.models.surge_actual_outcome import SurgeActualOutcome
from app.models.surge_bridge_shadow_candidate import SurgeBridgeShadowCandidate
from app.models.surge_horizon_shadow_observation import (  # noqa: F401
    SurgeHorizonShadowObservation,
)
from app.models.surge_prediction_evaluation import SurgePredictionEvaluation
from app.services.surge_detector import (
    gather_surge_candidates,
    generate_scan_universe_bridge_candidates,
    surge_candidate_to_signal_metadata,
)
from app.services.surge_universe_gap_service import evaluate_bridge_activation_readiness
from app.surge_config.surge_settings import get_surge_config


_DETECTOR_NAMES: tuple[str, ...] = (
    "detect_theme_news_cluster",
    "detect_volume_surge_news_combo",
    "detect_disclosure_surge_pattern",
    "detect_immediate_disclosure_signal",
    "detect_news_delayed_response",
    "detect_volume_breakout",
    "detect_momentum_continuation",
)


def _add_shadow_candidate(
    db: Session,
    trading_date: _date,
    stock_code: str,
    entry_pool: str,
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
            stock_name=f"SPEC111_{stock_code}",
            change_rate=12.0 if was_surge else 1.0,
            was_surge=was_surge,
            market="KOSPI",
        )
    )


def _add_evaluation(
    db: Session,
    trading_date: _date,
    *,
    precision: float | None,
) -> None:
    db.add(
        SurgePredictionEvaluation(
            evaluation_date=trading_date,
            predicted_count=10,
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
    pool_c_surge: bool = False,
    baseline_precision: float | None = 0.2,
    include_baseline: bool = True,
) -> None:
    pool_a_code = f"111{idx:03d}"
    pool_c_code = f"222{idx:03d}"
    _add_shadow_candidate(db, trading_date, pool_a_code, "pool_a", bridge_score=0.8)
    _add_shadow_candidate(db, trading_date, pool_c_code, "pool_c", bridge_score=0.4)
    _add_actual_outcome(db, trading_date, pool_a_code, was_surge=pool_a_surge)
    _add_actual_outcome(db, trading_date, pool_c_code, was_surge=pool_c_surge)
    if include_baseline:
        _add_evaluation(db, trading_date, precision=baseline_precision)


def _pool_a_canary_config():
    return get_surge_config().model_copy(
        update={
            "scan_universe_bridge_candidates_enabled": True,
            "scan_universe_bridge_pool_b_enabled": False,
            "scan_universe_bridge_max_candidates": 5,
            "scan_universe_bridge_pool_limits": {
                "pool_a": 5,
                "pool_b": 0,
                "pool_c": 0,
            },
        }
    )


def _add_pool_a_disclosures(
    db: Session,
    make_stock,
    count: int,
    *,
    prefix: str = "331",
    impact_score: float = 80.0,
) -> list[str]:
    today_str = _date.today().strftime("%Y%m%d")
    codes = [f"{prefix}{idx:03d}" for idx in range(count)]
    for idx, code in enumerate(codes):
        make_stock(name=f"SPEC111_POOL_A_{idx}", stock_code=code)
        db.add(
            Disclosure(
                corp_code=f"AI111A{idx:03d}",
                corp_name=f"SPEC111_A_{idx}",
                stock_code=code,
                report_name="SPEC-AI-111 Pool A test disclosure",
                rcept_no=f"AI111A{idx:012d}",
                rcept_dt=today_str,
                url=f"https://dart.fss.or.kr/spec111/a/{idx}",
                impact_score=impact_score,
            )
        )
    db.flush()
    return codes


def _add_pool_c_outcomes(db: Session, make_stock, count: int, *, prefix: str = "332") -> list[str]:
    trading_date = _date.today() - timedelta(days=1)
    codes = [f"{prefix}{idx:03d}" for idx in range(count)]
    for idx, code in enumerate(codes):
        make_stock(name=f"SPEC111_POOL_C_{idx}", stock_code=code)
        db.add(
            SurgeActualOutcome(
                trading_date=trading_date,
                stock_code=code,
                stock_name=f"SPEC111_POOL_C_{idx}",
                change_rate=10.0,
                was_surge=True,
                market="KOSPI",
            )
        )
    db.flush()
    return codes


class TestBridgeActivationReadiness:
    def test_blocks_when_shadow_outcome_days_are_insufficient(self, db: Session):
        base = _date(2026, 8, 1)
        for idx in range(9):
            _seed_readiness_day(
                db,
                base + timedelta(days=idx),
                idx,
                pool_a_surge=True,
                baseline_precision=0.2,
            )
        db.flush()

        result = evaluate_bridge_activation_readiness(db, target_pool="pool_a")

        assert result["ready"] is False
        assert result["reason"] == "insufficient_shadow_days"
        assert result["shadow_outcome_days"] == 9

    def test_passes_pool_a_without_blending_pool_c(self, db: Session):
        base = _date(2026, 8, 1)
        for idx in range(10):
            _seed_readiness_day(
                db,
                base + timedelta(days=idx),
                idx,
                pool_a_surge=True,
                pool_c_surge=False,
                baseline_precision=0.2,
            )
        db.flush()

        result = evaluate_bridge_activation_readiness(db, target_pool="pool_a")

        assert result["ready"] is True
        assert result["reason"] == "ready"
        assert result["eligible_days"] == 10
        assert result["pool_precision"] == 1.0
        assert result["baseline_precision"] == 0.2
        first_day = result["daily"][0]
        assert set(first_day["pools"].keys()) == {"pool_a", "pool_c"}

    def test_fails_low_pool_a_even_when_pool_c_is_high(self, db: Session):
        base = _date(2026, 8, 1)
        for idx in range(10):
            _seed_readiness_day(
                db,
                base + timedelta(days=idx),
                idx,
                pool_a_surge=idx in {0, 5},
                pool_c_surge=True,
                baseline_precision=0.6,
            )
        db.flush()

        result = evaluate_bridge_activation_readiness(db, target_pool="pool_a")

        assert result["ready"] is False
        assert result["reason"] == "low_precision"
        assert result["pool_precision"] == 0.2

    def test_missing_baseline_precision_blocks_go(self, db: Session):
        base = _date(2026, 8, 1)
        for idx in range(10):
            _seed_readiness_day(
                db,
                base + timedelta(days=idx),
                idx,
                pool_a_surge=True,
                include_baseline=idx < 9,
            )
        db.flush()

        result = evaluate_bridge_activation_readiness(db, target_pool="pool_a")

        assert result["ready"] is False
        assert result["reason"] == "insufficient_baseline_days"
        assert result["eligible_days"] == 9


class TestPoolAOnlyBridgeCanary:
    def test_flag_off_keeps_pool_a_bridge_out_of_qualified(self, db: Session, make_stock):
        pool_a_codes = _add_pool_a_disclosures(db, make_stock, 1, prefix="333")
        cfg = get_surge_config().model_copy(
            update={
                "scan_universe_bridge_candidates_enabled": False,
                "scan_universe_bridge_shadow_enabled": False,
            }
        )

        with contextlib.ExitStack() as stack:
            stack.enter_context(
                patch("app.services.naver_finance.fetch_volume_leaders_sync", return_value=[])
            )
            for name in _DETECTOR_NAMES:
                stack.enter_context(patch(f"app.services.surge_detector.{name}", return_value=[]))
            candidates = gather_surge_candidates(db, [], cfg, [])

        assert set(pool_a_codes).isdisjoint({c.stock_code for c in candidates})

    def test_pool_a_only_config_emits_pool_a_and_blocks_pool_c(
        self, db: Session, make_stock
    ):
        pool_a_codes = _add_pool_a_disclosures(db, make_stock, 7, prefix="334")
        pool_c_codes = _add_pool_c_outcomes(db, make_stock, 3, prefix="335")
        cfg = _pool_a_canary_config()

        result = generate_scan_universe_bridge_candidates(
            db,
            cfg,
            universe_codes=pool_a_codes + pool_c_codes,
            entry_pool_map={
                **{code: "pool_a" for code in pool_a_codes},
                **{code: "pool_c" for code in pool_c_codes},
            },
            merged={},
        )

        assert len(result) == 5
        assert {candidate.entry_pool for candidate in result} == {"pool_a"}
        candidate = result[0]
        assert candidate.bridge_score is not None
        assert candidate.bypass_composite_score == candidate.bridge_score
        assert "scan_universe_bridge" in candidate.active_detectors
        assert "pool_a" in candidate.active_detectors
        metadata = surge_candidate_to_signal_metadata(candidate, cfg)
        assert "scan_universe_bridge" in metadata["surge_basis"]
        assert "pool_a" in metadata["surge_basis"]

    def test_pool_b_disabled_does_not_fetch_and_pool_d_is_excluded(self, db: Session):
        cfg = _pool_a_canary_config()
        universe_codes = ["336001", "337001"]
        entry_pool_map = {"336001": "pool_b", "337001": "pool_d"}

        with patch(
            "app.services.naver_finance.fetch_stock_price_history_batch_sync"
        ) as batch_mock:
            result = generate_scan_universe_bridge_candidates(
                db,
                cfg,
                universe_codes=universe_codes,
                entry_pool_map=entry_pool_map,
                merged={},
            )

        assert result == []
        batch_mock.assert_not_called()

    def test_pool_a_bridge_logs_total_and_pool_counts(
        self, db: Session, make_stock, caplog
    ):
        pool_a_codes = _add_pool_a_disclosures(db, make_stock, 1, prefix="338")
        cfg = _pool_a_canary_config()

        with caplog.at_level(logging.INFO, logger="app.services.surge_detector"):
            result = generate_scan_universe_bridge_candidates(
                db,
                cfg,
                universe_codes=pool_a_codes,
                entry_pool_map={pool_a_codes[0]: "pool_a"},
                merged={},
            )

        assert len(result) == 1
        assert any(
            "생성: 1개" in record.getMessage()
            and "pool_a=1" in record.getMessage()
            and "pool_b=0" in record.getMessage()
            and "pool_c=0" in record.getMessage()
            for record in caplog.records
        )


class TestSpecAi111MetricCompatibility:
    def test_evaluation_endpoint_keeps_market_and_scannable_recall_with_bridge_signal(
        self, client, db: Session, make_stock
    ):
        stock = make_stock(name="SPEC111_METRIC", stock_code="339001")
        signal_date = _date(2026, 8, 9)
        db.add(
            FundSignal(
                stock_id=stock.id,
                signal="buy",
                confidence=0.8,
                reasoning="SPEC-AI-111 bridge prediction",
                signal_type="surge_candidate",
                surge_metadata=json.dumps(
                    {"surge_basis": ["scan_universe_bridge", "pool_a"]},
                    ensure_ascii=False,
                ),
                created_at=datetime.combine(signal_date, datetime.min.time()).replace(
                    hour=15, minute=20
                ),
            )
        )
        db.add(
            SurgePredictionEvaluation(
                evaluation_date=_date(2026, 8, 10),
                predicted_count=4,
                actual_surge_count=8,
                true_positive=2,
                false_positive=2,
                false_negative=6,
                precision=0.5,
                recall=0.75,
                f1_score=0.333,
                scannable_recall=0.75,
                coverage=0.25,
                scannable_actual_count=2,
                total_actual_count=8,
            )
        )
        db.commit()

        response = client.get("/api/surge-trading/evaluation")

        assert response.status_code == 200
        row = response.json()[0]
        assert row["recall"] == 0.75
        assert row["market_recall"] == 0.25
        assert row["scannable_recall"] == 0.75
        assert row["recall_basis"] == "scannable"
