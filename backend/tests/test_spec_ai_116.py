"""SPEC-AI-116 acceptance tests."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from unittest.mock import patch

from sqlalchemy.orm import Session

from app.models.fund_signal import FundSignal
from app.models.surge_actual_outcome import SurgeActualOutcome
from app.models.surge_missing_trigger_shadow_candidate import (
    SurgeMissingTriggerShadowCandidate,
)
from app.models.surge_prediction_evaluation import SurgePredictionEvaluation
from app.services.naver_finance import PriceRecord
from app.services.surge_evaluation_service import evaluate_surge_predictions
from app.services.surge_missing_trigger_detector_service import (
    FAMILY_CONTRACT_MNA,
    FAMILY_LOW_LIQUIDITY,
    FAMILY_VOLUME_SPIKE,
    detect_contract_mna_shadow_candidates,
    detect_low_liquidity_shadow_candidates,
    detect_volume_spike_shadow_candidates,
    generate_missing_trigger_shadow_readiness_report,
    persist_missing_trigger_shadow_candidates,
    select_missing_trigger_detector_families,
)
from app.services.surge_trading_service import _get_prev_business_day
from app.surge_config.surge_settings import get_surge_config


def _history(current_volume: int, baseline_volume: int, count: int = 21):
    return [
        PriceRecord(date=f"2026.08.{idx + 1:02d}", close=1000, volume=(
            current_volume if idx == 0 else baseline_volume
        ))
        for idx in range(count)
    ]


def _add_actual(
    db: Session,
    trading_date: date,
    stock_code: str,
    *,
    was_surge: bool,
    change_rate: float | None = None,
) -> None:
    db.add(
        SurgeActualOutcome(
            trading_date=trading_date,
            stock_code=stock_code,
            stock_name=f"SPEC116_{stock_code}",
            change_rate=change_rate if change_rate is not None else (12.0 if was_surge else 1.0),
            was_surge=was_surge,
            high_change_rate=13.0 if was_surge else 2.0,
            market="KOSPI",
        )
    )


def _add_eval(
    db: Session,
    trading_date: date,
    *,
    predicted_count: int = 2,
    true_positive: int = 1,
    actual_surge_count: int = 2,
) -> None:
    precision = true_positive / predicted_count if predicted_count else 0.0
    recall = true_positive / actual_surge_count if actual_surge_count else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall > 0
        else 0.0
    )
    db.add(
        SurgePredictionEvaluation(
            evaluation_date=trading_date,
            predicted_count=predicted_count,
            actual_surge_count=actual_surge_count,
            true_positive=true_positive,
            false_positive=max(0, predicted_count - true_positive),
            false_negative=max(0, actual_surge_count - true_positive),
            precision=precision,
            recall=recall,
            f1_score=f1,
        )
    )


def _add_shadow_row(
    db: Session,
    trading_date: date,
    stock_code: str,
    family: str,
    *,
    horizon: str = "same_day",
) -> None:
    db.add(
        SurgeMissingTriggerShadowCandidate(
            trading_date=trading_date,
            stock_code=stock_code,
            detector_family=family,
            horizon=horizon,
            stock_name=f"SPEC116_{stock_code}",
            score=0.7,
            source_pool=f"{family}_source_pool",
            evidence_json=json.dumps({"horizon": horizon}),
            risk_tags_json=json.dumps(["shadow_only"]),
        )
    )


class TestAttributionSelection:
    def test_insufficient_attribution_data_keeps_all_families_no_go(self, db: Session):
        result = select_missing_trigger_detector_families(db, days=20)

        assert result["status"] == "no_go"
        assert result["reason"] == "insufficient_attribution_data"
        assert all(
            item["production_status"] == "no_go"
            for item in result["families"].values()
        )
        assert all(
            item["shadow_measurement_enabled"] is False
            for item in result["families"].values()
        )


class TestContractMnaShadowDetector:
    def test_contract_mna_disclosure_records_compact_shadow_candidate(
        self,
        db: Session,
        make_stock,
        make_disclosure,
    ):
        trading_date = date(2026, 8, 10)
        prev_day = _get_prev_business_day(trading_date)
        stock = make_stock(name="SPEC116_CONTRACT", stock_code="116001")
        make_disclosure(
            stock_id=stock.id,
            stock_code=stock.stock_code,
            corp_name=stock.name,
            report_name="단일판매 공급계약 체결",
            rcept_no="11600100000001",
            rcept_dt=prev_day.strftime("%Y%m%d"),
            impact_score=80.0,
        )
        before_signals = db.query(FundSignal).count()

        candidates = detect_contract_mna_shadow_candidates(
            db,
            trading_date,
            stock_codes=[stock.stock_code],
        )
        persisted = persist_missing_trigger_shadow_candidates(
            db,
            trading_date,
            candidates,
            detector_families={FAMILY_CONTRACT_MNA},
        )

        assert persisted == 1
        assert db.query(FundSignal).count() == before_signals
        row = db.query(SurgeMissingTriggerShadowCandidate).one()
        evidence = json.loads(row.evidence_json)
        assert row.detector_family == FAMILY_CONTRACT_MNA
        assert row.horizon == "next_day"
        assert "공급계약" in evidence["matched_keywords"]
        assert evidence["rcept_no"] == "11600100000001"
        assert "content" not in evidence

    def test_same_day_contract_candidate_is_tagged_same_day(
        self,
        db: Session,
        make_stock,
        make_disclosure,
    ):
        trading_date = date(2026, 8, 10)
        stock = make_stock(name="SPEC116_SAMEDAY", stock_code="116002")
        make_disclosure(
            stock_id=stock.id,
            stock_code=stock.stock_code,
            corp_name=stock.name,
            report_name="경영권 인수 계약",
            rcept_no="11600200000001",
            rcept_dt=trading_date.strftime("%Y%m%d"),
            impact_score=70.0,
        )

        candidates = detect_contract_mna_shadow_candidates(
            db,
            trading_date,
            stock_codes=[stock.stock_code],
        )

        assert len(candidates) == 1
        assert candidates[0].horizon == "same_day"
        assert candidates[0].risk_tags == ["shadow_only"]


class TestVolumeSpikeShadowDetector:
    def test_volume_spike_uses_batch_lookup_and_records_ratio(self, db: Session, make_stock):
        trading_date = date(2026, 8, 10)
        stock_a = make_stock(name="SPEC116_VOL_A", stock_code="116101", market_cap=2000)
        stock_b = make_stock(name="SPEC116_VOL_B", stock_code="116102", market_cap=2000)
        stock_missing = make_stock(
            name="SPEC116_VOL_MISS", stock_code="116103", market_cap=2000
        )
        histories = {
            stock_a.stock_code: _history(5000, 1000),
            stock_b.stock_code: _history(2000, 1000),
            stock_missing.stock_code: [],
        }

        with patch(
            "app.services.naver_finance.fetch_stock_price_history_batch_sync",
            return_value=histories,
        ) as batch_mock:
            candidates = detect_volume_spike_shadow_candidates(
                db,
                trading_date,
                stock_codes=[
                    stock_a.stock_code,
                    stock_b.stock_code,
                    stock_missing.stock_code,
                ],
                ratio_threshold=3.0,
                baseline_days=20,
            )

        batch_mock.assert_called_once()
        assert batch_mock.call_args.args[0] == [
            stock_a.stock_code,
            stock_b.stock_code,
            stock_missing.stock_code,
        ]
        assert [candidate.stock_code for candidate in candidates] == [stock_a.stock_code]
        evidence = candidates[0].evidence
        assert evidence["source_type"] == "price_history_batch"
        assert evidence["baseline_window"] == 20
        assert evidence["volume_ratio"] == 5.0


class TestLowLiquidityShadowDetector:
    def test_low_liquidity_price_move_is_shadow_only_high_risk(
        self,
        db: Session,
        make_stock,
    ):
        trading_date = date(2026, 8, 10)
        stock = make_stock(name="SPEC116_LOWLIQ", stock_code="116201", market_cap=500)
        _add_actual(db, trading_date, stock.stock_code, was_surge=False, change_rate=8.0)
        db.flush()

        candidates = detect_low_liquidity_shadow_candidates(
            db,
            trading_date,
            stock_codes=[stock.stock_code],
        )

        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.detector_family == FAMILY_LOW_LIQUIDITY
        assert candidate.risk_tags == ["shadow_only", "high_risk", "no_bypass"]
        assert candidate.evidence["liquidity_bucket"] == "small"
        assert "turnover_estimate" in candidate.evidence


class TestReadinessReport:
    def test_readiness_is_computed_per_family_without_blending(self, db: Session):
        base_day = date(2026, 7, 20)
        for idx in range(10):
            trading_date = base_day + timedelta(days=idx)
            _add_eval(db, trading_date)

            contract_code = f"1163{idx:02d}"
            _add_shadow_row(db, trading_date, contract_code, FAMILY_CONTRACT_MNA)
            _add_actual(db, trading_date, contract_code, was_surge=idx < 6)

            volume_code = f"1164{idx:02d}"
            _add_shadow_row(db, trading_date, volume_code, FAMILY_VOLUME_SPIKE)
            _add_actual(db, trading_date, volume_code, was_surge=False)
        db.flush()

        report = generate_missing_trigger_shadow_readiness_report(db, days=10)

        assert report["status"] == "ok"
        families = report["families"]
        assert families[FAMILY_CONTRACT_MNA]["status"] == "go"
        assert families[FAMILY_CONTRACT_MNA]["added_precision"] == 0.6
        assert families[FAMILY_VOLUME_SPIKE]["status"] == "no_go"
        assert families[FAMILY_VOLUME_SPIKE]["reason"] == "precision_below_baseline"
        assert families[FAMILY_LOW_LIQUIDITY]["status"] == "no_go"
        assert families[FAMILY_LOW_LIQUIDITY]["reason"] == "insufficient_shadow_days"

    def test_same_day_shadow_candidate_has_separate_lane_and_no_t1_impact(
        self,
        db: Session,
    ):
        trading_date = date(2026, 8, 10)
        _add_eval(db, trading_date, predicted_count=2, true_positive=1)
        _add_shadow_row(
            db,
            trading_date,
            "116501",
            FAMILY_CONTRACT_MNA,
            horizon="same_day",
        )
        _add_actual(db, trading_date, "116501", was_surge=True)
        _add_shadow_row(
            db,
            trading_date,
            "116502",
            FAMILY_CONTRACT_MNA,
            horizon="next_day",
        )
        _add_actual(db, trading_date, "116502", was_surge=False)
        db.flush()

        report = generate_missing_trigger_shadow_readiness_report(
            db,
            days=1,
            min_eligible_days=1,
        )

        assert report["lanes"]["same_day"]["shadow_candidate_count"] == 1
        assert report["lanes"]["same_day"]["expected_tp"] == 1
        assert report["lanes"]["same_day"]["standard_t1_predicted_set_impact"] == 0
        assert report["lanes"]["next_day"]["shadow_candidate_count"] == 1
        assert report["families"][FAMILY_CONTRACT_MNA]["baseline_predicted_count"] == 2


_MISSING_TRIGGER_PACK_TARGET = (
    "app.services.surge_missing_trigger_detector_service."
    "run_missing_trigger_shadow_detector_pack"
)


class TestMissingTriggerWiring:
    """evaluate_surge_predictions()가 FN(미탐지) 종목에 대해 미탐지 트리거 shadow 탐지기
    팩을 호출하도록 배선되었는지 검증한다 (SPEC-AI-116 후속 수정)."""

    def test_invokes_pack_when_fn_nonempty_and_enabled(self, db: Session, make_stock):
        trading_date = date(2026, 8, 10)
        stock = make_stock(name="SPEC116_WIRE_FN", stock_code="116601")
        _add_actual(db, trading_date, stock.stock_code, was_surge=True)
        db.flush()

        cfg = get_surge_config().model_copy(
            update={"missing_trigger_shadow_enabled": True}
        )

        with (
            patch(
                "app.surge_config.surge_settings.get_surge_config",
                return_value=cfg,
            ),
            patch(
                "app.services.surge_evaluation_service._persist_signal_forward_outcomes",
                return_value=set(),
            ),
            patch(
                _MISSING_TRIGGER_PACK_TARGET,
                return_value={"status": "ok", "persisted_count": 1},
            ) as pack_mock,
        ):
            evaluation = evaluate_surge_predictions(db, trading_date)

        assert evaluation.false_negative == 1
        pack_mock.assert_called_once()
        assert pack_mock.call_args.args[1] == trading_date
        assert pack_mock.call_args.kwargs["stock_codes"] == [stock.stock_code]

    def test_skips_pack_when_fn_empty(self, db: Session, make_stock):
        trading_date = date(2026, 8, 10)
        signal_date = _get_prev_business_day(trading_date)
        stock = make_stock(name="SPEC116_WIRE_NOFN", stock_code="116602")
        db.add(
            FundSignal(
                stock_id=stock.id,
                signal="buy",
                confidence=0.8,
                reasoning="predicted correctly",
                signal_type="surge_candidate",
                surge_metadata=json.dumps(
                    {"surge_probability_score": 0.8}, ensure_ascii=False
                ),
                created_at=datetime.combine(signal_date, time(hour=15, minute=20)),
            )
        )
        _add_actual(db, trading_date, stock.stock_code, was_surge=True)
        db.flush()

        cfg = get_surge_config().model_copy(
            update={"missing_trigger_shadow_enabled": True}
        )

        with (
            patch(
                "app.surge_config.surge_settings.get_surge_config",
                return_value=cfg,
            ),
            patch(
                "app.services.surge_evaluation_service._persist_signal_forward_outcomes",
                return_value=set(),
            ),
            patch(_MISSING_TRIGGER_PACK_TARGET) as pack_mock,
        ):
            evaluation = evaluate_surge_predictions(db, trading_date)

        assert evaluation.false_negative == 0
        pack_mock.assert_not_called()

    def test_skips_pack_when_flag_disabled(self, db: Session, make_stock):
        trading_date = date(2026, 8, 10)
        stock = make_stock(name="SPEC116_WIRE_DISABLED", stock_code="116603")
        _add_actual(db, trading_date, stock.stock_code, was_surge=True)
        db.flush()

        cfg = get_surge_config().model_copy(
            update={"missing_trigger_shadow_enabled": False}
        )

        with (
            patch(
                "app.surge_config.surge_settings.get_surge_config",
                return_value=cfg,
            ),
            patch(
                "app.services.surge_evaluation_service._persist_signal_forward_outcomes",
                return_value=set(),
            ),
            patch(_MISSING_TRIGGER_PACK_TARGET) as pack_mock,
        ):
            evaluation = evaluate_surge_predictions(db, trading_date)

        assert evaluation.false_negative == 1
        pack_mock.assert_not_called()

    def test_pack_exception_does_not_propagate(self, db: Session, make_stock):
        trading_date = date(2026, 8, 10)
        stock = make_stock(name="SPEC116_WIRE_ERR", stock_code="116604")
        _add_actual(db, trading_date, stock.stock_code, was_surge=True)
        db.flush()

        cfg = get_surge_config().model_copy(
            update={"missing_trigger_shadow_enabled": True}
        )

        with (
            patch(
                "app.surge_config.surge_settings.get_surge_config",
                return_value=cfg,
            ),
            patch(
                "app.services.surge_evaluation_service._persist_signal_forward_outcomes",
                return_value=set(),
            ),
            patch(
                _MISSING_TRIGGER_PACK_TARGET,
                side_effect=RuntimeError("boom"),
            ) as pack_mock,
        ):
            # 탐지기 팩 내부 예외가 evaluate_surge_predictions() 밖으로 전파되지 않아야 한다
            # (shadow-only 안전 보장). 예외 없이 정상 반환되는 것 자체가 핵심 검증이므로,
            # 반환된 evaluation 객체의 속성은 재조회하지 않는다 — commit 이후 세션에 대한
            # rollback()은(테스트 픽스처가 외부 트랜잭션에 join된 상태이므로) 이미 커밋된
            # evaluation row 자체에는 영향을 주지 않지만(운영 환경 세션에서는 안전), 이
            # 테스트 하네스의 savepoint-join 특성상 만료된 ORM 속성 재조회가 무관한
            # SQLAlchemy 예외를 유발할 수 있어 회피한다.
            evaluate_surge_predictions(db, trading_date)

        pack_mock.assert_called_once()
