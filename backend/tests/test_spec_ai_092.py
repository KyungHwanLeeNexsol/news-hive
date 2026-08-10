"""SPEC-AI-092: 급등 예측 재현율 회복 — TASK-002~006 테스트.

AC-092-002: 평가 predicted set 스냅샷 복원
AC-092-003: bridge flag OFF 무회귀
AC-092-004: Pool C bridge 후보 생성 (+ 시나리오 8 상한 적용)
AC-092-005: bridge 후보화 시 신규 외부 fetch 금지
AC-092-006: adaptive threshold 연결성(execution-only 명시)
AC-092-007: 운영 평가 누락 감지
AC-092-008: same-day 후보 predicted set 배제(bridge 경로 포함)
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from app.models.fund_signal import FundSignal
from app.models.stock import Stock
from app.models.surge_actual_outcome import SurgeActualOutcome
from app.models.surge_prediction_evaluation import SurgePredictionEvaluation
from app.models.surge_threshold_history import SurgeThresholdHistory
from app.surge_config.surge_settings import SurgeDetectionConfig, get_surge_config
from app.services.surge_detector import (
    SurgeCandidate,
    generate_scan_universe_bridge_candidates,
    surge_candidate_to_signal_metadata,
)
from app.services.surge_evaluation_service import (
    _is_near_limit_up_carry_signal,
    _is_same_day_event_horizon_signal,
    check_and_alert_missing_evaluation,
    detect_missing_evaluation_records,
    evaluate_surge_predictions,
    repair_missing_surge_evaluation,
    restore_predicted_codes,
)


@pytest.fixture
def surge_config() -> SurgeDetectionConfig:
    """테스트용 SurgeDetectionConfig (기본 설정 파일 기준)."""
    return get_surge_config()


@pytest.fixture
def bridge_config(surge_config: SurgeDetectionConfig) -> SurgeDetectionConfig:
    """bridge 후보화 활성화 + 낮은 상한(테스트 관측 용이)."""
    return surge_config.model_copy(
        update={
            "scan_universe_bridge_candidates_enabled": True,
            "scan_universe_bridge_max_candidates": 20,
            "scan_universe_bridge_pool_limits": {"pool_a": 10, "pool_c": 10},
        }
    )


# ---------------------------------------------------------------------------
# AC-092-002: 평가 predicted set 스냅샷 복원
# ---------------------------------------------------------------------------

class TestPredictedCodesSnapshot:
    def test_evaluate_surge_predictions_saves_predicted_codes_json(
        self, db: Session, make_stock
    ):
        """evaluate_surge_predictions()가 공식 predicted set을 스냅샷으로 저장한다."""
        from app.services.surge_trading_service import _get_prev_business_day

        trading_date = date(2026, 6, 10)
        signal_date = _get_prev_business_day(trading_date)
        stock = make_stock(name="스냅샷종목", stock_code="911001")

        db.add(FundSignal(
            stock_id=stock.id,
            signal="buy",
            confidence=0.8,
            reasoning="테스트",
            signal_type="surge_candidate",
            surge_metadata='{"surge_basis": ["theme_cluster"]}',
            created_at=datetime.combine(signal_date, datetime.min.time()).replace(
                hour=15, minute=20
            ),
        ))
        db.commit()

        evaluation = evaluate_surge_predictions(db, trading_date)

        assert evaluation.predicted_codes_json is not None
        codes = json.loads(evaluation.predicted_codes_json)
        assert codes == ["911001"]

    def test_restore_predicted_codes_survives_created_at_drift(
        self, db: Session, make_stock
    ):
        """AC-092-002 시나리오 2: 평가 저장 후 FundSignal.created_at이 후일로 이동해도
        snapshot 기반 predicted set 복원 결과는 변하지 않아야 한다."""
        from app.services.surge_trading_service import _get_prev_business_day

        trading_date = date(2026, 6, 11)
        signal_date = _get_prev_business_day(trading_date)
        stock_a = make_stock(name="A종목", stock_code="911002")
        stock_b = make_stock(name="B종목", stock_code="911003")
        stock_c = make_stock(name="C종목", stock_code="911004")

        for stock in (stock_a, stock_b, stock_c):
            db.add(FundSignal(
                stock_id=stock.id,
                signal="buy",
                confidence=0.8,
                reasoning="테스트",
                signal_type="surge_candidate",
                surge_metadata='{"surge_basis": ["theme_cluster"]}',
                created_at=datetime.combine(signal_date, datetime.min.time()).replace(
                    hour=15, minute=20
                ),
            ))
        db.commit()

        evaluation = evaluate_surge_predictions(db, trading_date)
        assert evaluation.predicted_count == 3

        # B종목의 FundSignal.created_at을 다음 날로 이동(carry-over 시뮬레이션)
        b_signal = (
            db.query(FundSignal)
            .join(Stock, FundSignal.stock_id == Stock.id)
            .filter(Stock.stock_code == "911003")
            .first()
        )
        b_signal.created_at = datetime.combine(
            trading_date, datetime.min.time()
        ).replace(hour=10, minute=0)
        db.commit()

        restored = restore_predicted_codes(evaluation)
        assert restored is not None
        assert sorted(restored) == ["911002", "911003", "911004"]

    def test_restore_predicted_codes_none_for_legacy_row(self, db: Session):
        """스냅샷 도입 이전 row(predicted_codes_json=None)는 None을 반환한다(fail-open)."""
        ev = SurgePredictionEvaluation(
            evaluation_date=date(2026, 6, 12),
            predicted_count=5,
            actual_surge_count=3,
            true_positive=2,
            false_positive=3,
            false_negative=1,
            precision=0.4,
            recall=0.667,
            f1_score=0.5,
        )
        db.add(ev)
        db.commit()

        assert restore_predicted_codes(ev) is None

    def test_evaluation_endpoint_exposes_predicted_codes(self, client, db: Session):
        """GET /evaluation/{date} 응답에 predicted_codes 필드가 포함된다(하위호환 추가 필드)."""
        ev = SurgePredictionEvaluation(
            evaluation_date=date(2026, 6, 13),
            predicted_count=2,
            actual_surge_count=1,
            true_positive=1,
            false_positive=1,
            false_negative=0,
            precision=0.5,
            recall=1.0,
            f1_score=0.667,
            predicted_codes_json=json.dumps(["911005", "911006"]),
        )
        db.add(ev)
        db.commit()

        response = client.get("/api/surge-trading/evaluation/2026-06-13")
        assert response.status_code == 200
        data = response.json()
        assert data["predicted_codes"] == ["911005", "911006"]
        # 기존 필드는 하위호환 유지
        assert data["predicted_count"] == 2


# ---------------------------------------------------------------------------
# AC-092-003 / AC-092-005: bridge flag OFF 무회귀 + 신규 외부 fetch 금지
# ---------------------------------------------------------------------------

class TestBridgeFlagOff:
    def test_bridge_disabled_by_default(self, surge_config: SurgeDetectionConfig):
        assert surge_config.scan_universe_bridge_candidates_enabled is False

    def test_generate_bridge_candidates_returns_empty_when_disabled(
        self, db: Session, surge_config: SurgeDetectionConfig
    ):
        assert surge_config.scan_universe_bridge_candidates_enabled is False
        result = generate_scan_universe_bridge_candidates(
            db,
            surge_config,
            universe_codes=["911007"],
            entry_pool_map={"911007": "pool_c"},
            merged={},
        )
        assert result == []

    def test_generate_bridge_candidates_no_new_external_fetch(
        self, db: Session, bridge_config: SurgeDetectionConfig
    ):
        """AC-092-005: bridge 후보화 실행 시 Naver/DART fetch 함수가 호출되지 않는다."""
        with patch(
            "app.services.naver_finance.fetch_volume_leaders_sync"
        ) as mock_volume, patch(
            "app.services.naver_finance.fetch_stock_price_history_sync"
        ) as mock_price, patch(
            "app.services.dart_crawler.fetch_dart_disclosures"
        ) as mock_dart:
            generate_scan_universe_bridge_candidates(
                db,
                bridge_config,
                universe_codes=["911008"],
                entry_pool_map={"911008": "pool_c"},
                merged={},
            )
            mock_volume.assert_not_called()
            mock_price.assert_not_called()
            mock_dart.assert_not_called()


# ---------------------------------------------------------------------------
# AC-092-004: Pool C bridge 후보 생성 (+ 시나리오 8: 상한 적용)
# ---------------------------------------------------------------------------

class TestBridgeCandidateGeneration:
    def test_pool_c_bridge_candidate_generated(
        self, db: Session, bridge_config: SurgeDetectionConfig, make_stock
    ):
        make_stock(name="브리지종목", stock_code="911009")
        prev_day = date.today() - timedelta(days=1)
        db.add(SurgeActualOutcome(
            trading_date=prev_day,
            stock_code="911009",
            stock_name="브리지종목",
            change_rate=10.0,
            was_surge=False,
            market="KOSPI",
        ))
        db.commit()

        result = generate_scan_universe_bridge_candidates(
            db,
            bridge_config,
            universe_codes=["911009"],
            entry_pool_map={"911009": "pool_c"},
            merged={},
        )

        assert len(result) == 1
        candidate = result[0]
        assert candidate.stock_code == "911009"
        assert candidate.entry_pool == "pool_c"
        assert candidate.bridge_score > 0
        assert candidate.bypass_composite_score == candidate.bridge_score
        assert "scan_universe_bridge" in candidate.active_detectors
        assert "pool_c" in candidate.active_detectors

        # AC-092-004: surge_metadata.surge_basis에 scan_universe_bridge + pool_c 근거 기록
        metadata = surge_candidate_to_signal_metadata(candidate, bridge_config)
        assert "scan_universe_bridge" in metadata["surge_basis"]
        assert "pool_c" in metadata["surge_basis"]

    def test_pool_c_candidate_excluded_below_min_score(
        self, db: Session, bridge_config: SurgeDetectionConfig, make_stock
    ):
        make_stock(name="저점수종목", stock_code="911010")
        prev_day = date.today() - timedelta(days=1)
        db.add(SurgeActualOutcome(
            trading_date=prev_day,
            stock_code="911010",
            stock_name="저점수종목",
            change_rate=3.0,  # 3/15=0.2 < _BRIDGE_MIN_SCORE(0.3)
            was_surge=False,
            market="KOSPI",
        ))
        db.commit()

        result = generate_scan_universe_bridge_candidates(
            db,
            bridge_config,
            universe_codes=["911010"],
            entry_pool_map={"911010": "pool_c"},
            merged={},
        )
        assert result == []

    def test_codes_already_in_merged_are_excluded(
        self, db: Session, bridge_config: SurgeDetectionConfig, make_stock
    ):
        """merged에 이미 있는 종목은 bridge 후보 대상에서 제외된다."""
        make_stock(name="이미탐지종목", stock_code="911011")
        prev_day = date.today() - timedelta(days=1)
        db.add(SurgeActualOutcome(
            trading_date=prev_day,
            stock_code="911011",
            stock_name="이미탐지종목",
            change_rate=10.0,
            was_surge=False,
            market="KOSPI",
        ))
        db.commit()

        merged = {"911011": SurgeCandidate(stock_code="911011", stock_name="이미탐지종목")}
        result = generate_scan_universe_bridge_candidates(
            db,
            bridge_config,
            universe_codes=["911011"],
            entry_pool_map={"911011": "pool_c"},
            merged=merged,
        )
        assert result == []

    def test_pool_and_overall_limits_applied(
        self, db: Session, make_stock
    ):
        """시나리오 8: pool별 상한 및 전체 상한을 초과하지 않는다."""
        prev_day = date.today() - timedelta(days=1)
        codes = [f"92{i:04d}" for i in range(15)]
        for i, code in enumerate(codes):
            make_stock(name=f"종목{i}", stock_code=code)
            db.add(SurgeActualOutcome(
                trading_date=prev_day,
                stock_code=code,
                stock_name=f"종목{i}",
                # 점수 차등: 15.0(최고) ~ 8.0 사이, 전부 min_score 이상
                change_rate=15.0 - i * 0.5,
                was_surge=False,
                market="KOSPI",
            ))
        db.commit()

        config = get_surge_config().model_copy(
            update={
                "scan_universe_bridge_candidates_enabled": True,
                "scan_universe_bridge_max_candidates": 20,
                "scan_universe_bridge_pool_limits": {"pool_c": 10},
            }
        )

        result = generate_scan_universe_bridge_candidates(
            db,
            config,
            universe_codes=codes,
            entry_pool_map={code: "pool_c" for code in codes},
            merged={},
        )

        assert len(result) == 10  # pool_c 상한
        assert len(result) <= config.scan_universe_bridge_max_candidates
        # 상위 점수(변화율 높은 종목) 우선 채택 검증
        selected_codes = {c.stock_code for c in result}
        assert "920000" in selected_codes  # change_rate=15.0, 최고점수


# ---------------------------------------------------------------------------
# AC-092-008: same-day 후보는 bridge 경로에서도 배제된다
# ---------------------------------------------------------------------------

class TestBridgeSameDayExclusion:
    def test_bridge_candidate_metadata_never_marks_same_day(
        self, bridge_config: SurgeDetectionConfig
    ):
        candidate = SurgeCandidate(
            stock_code="911012",
            stock_name="브리지종목",
            entry_pool="pool_c",
            bridge_score=0.5,
            bypass_composite_score=0.5,
            active_detectors=["scan_universe_bridge", "pool_c"],
        )
        metadata = surge_candidate_to_signal_metadata(candidate, bridge_config)
        metadata_json = json.dumps(metadata, ensure_ascii=False)

        assert _is_same_day_event_horizon_signal(metadata_json) is False
        assert _is_near_limit_up_carry_signal(metadata_json) is False

    def test_bridge_candidate_with_injected_same_day_horizon_is_excluded(
        self, bridge_config: SurgeDetectionConfig
    ):
        """bridge 후보라도 horizon=same_day가 주입되면(SPEC-AI-083 인트라데이 태깅과 동일
        경로) 표준 predicted set 판별 함수가 이를 배제해야 한다."""
        candidate = SurgeCandidate(
            stock_code="911013",
            stock_name="브리지종목",
            entry_pool="pool_c",
            bridge_score=0.5,
            bypass_composite_score=0.5,
            active_detectors=["scan_universe_bridge", "pool_c"],
        )
        metadata = surge_candidate_to_signal_metadata(candidate, bridge_config)
        metadata["horizon"] = "same_day"
        metadata_json = json.dumps(metadata, ensure_ascii=False)

        assert _is_same_day_event_horizon_signal(metadata_json) is True


# ---------------------------------------------------------------------------
# AC-092-006: adaptive threshold 연결성 (execution-only 명시)
# ---------------------------------------------------------------------------

class TestAdaptiveThresholdConnectivity:
    def test_generation_gate_source_does_not_import_adaptive_threshold(self):
        """예측 생성 gate(surge_detector.py)는 surge_threshold_service를 import/호출하지
        않는다 — 두 게이트가 코드 수준에서 완전히 분리되어 있음을 확인한다(주석의 설명
        문구는 예외로 하고, 실제 import/함수호출/쿼리 배선만 검사한다)."""
        import inspect

        from app.services import surge_detector

        source = inspect.getsource(surge_detector)
        assert "import surge_threshold_service" not in source
        assert "get_today_threshold(" not in source
        assert "compute_adaptive_threshold(" not in source
        assert "db.query(SurgeThresholdHistory)" not in source

    def test_get_today_threshold_reflects_stored_value(
        self, db: Session, surge_config: SurgeDetectionConfig
    ):
        """매수 실행 gate(get_today_threshold)는 저장된 값을 그대로 읽는다 —
        0.30과 0.70 fixture에서 반환값 차이가 관찰되어야 한다."""
        from app.services.surge_threshold_service import get_today_threshold

        today = date.today()

        db.add(SurgeThresholdHistory(date=today, threshold=0.30))
        db.commit()
        assert get_today_threshold(db, surge_config) == pytest.approx(0.30)

        row = db.query(SurgeThresholdHistory).filter(
            SurgeThresholdHistory.date == today
        ).first()
        row.threshold = 0.70
        db.commit()
        assert get_today_threshold(db, surge_config) == pytest.approx(0.70)

    def test_get_today_threshold_fallback_when_missing(
        self, db: Session, surge_config: SurgeDetectionConfig
    ):
        """당일 threshold 레코드가 없으면 min_score_for_signal로 fallback한다."""
        from app.services.surge_threshold_service import get_today_threshold

        assert get_today_threshold(db, surge_config) == pytest.approx(
            surge_config.ensemble.min_score_for_signal
        )


# ---------------------------------------------------------------------------
# AC-092-007: 운영 평가 누락 감지
# ---------------------------------------------------------------------------

class TestMissingEvaluationMonitor:
    def test_detect_missing_both(self, db: Session):
        trading_date = date(2026, 6, 20)
        status = detect_missing_evaluation_records(db, trading_date)
        assert status["actual_outcome_missing"] is True
        assert status["evaluation_missing"] is True

    def test_detect_missing_none(self, db: Session):
        trading_date = date(2026, 6, 21)
        db.add(SurgeActualOutcome(
            trading_date=trading_date,
            stock_code="911014",
            stock_name="테스트",
            change_rate=1.0,
            was_surge=False,
            market="KOSPI",
        ))
        db.add(SurgePredictionEvaluation(
            evaluation_date=trading_date,
            predicted_count=1,
            actual_surge_count=0,
            true_positive=0,
            false_positive=1,
            false_negative=0,
            precision=0.0,
            recall=0.0,
            f1_score=0.0,
        ))
        db.commit()

        status = detect_missing_evaluation_records(db, trading_date)
        assert status["actual_outcome_missing"] is False
        assert status["evaluation_missing"] is False

    def test_detect_missing_is_idempotent(self, db: Session):
        trading_date = date(2026, 6, 22)
        first = detect_missing_evaluation_records(db, trading_date)
        second = detect_missing_evaluation_records(db, trading_date)
        assert first == second

    def test_check_and_alert_fail_open_without_telegram_env(
        self, db: Session, monkeypatch
    ):
        """TELEGRAM_ADMIN_CHAT_ID 미설정 시 예외 없이 warning log로 fail-open한다."""
        monkeypatch.delenv("TELEGRAM_ADMIN_CHAT_ID", raising=False)
        trading_date = date(2026, 6, 23)

        status = check_and_alert_missing_evaluation(db, trading_date)
        assert status["actual_outcome_missing"] is True
        assert status["evaluation_missing"] is True

    def test_repair_collects_missing_actual_then_evaluates(self, db: Session):
        trading_date = date(2026, 8, 4)

        async def fake_collect(session: Session, target_date: date) -> int:
            session.add(SurgeActualOutcome(
                trading_date=target_date,
                stock_code="911091",
                stock_name="복구테스트",
                change_rate=1.0,
                was_surge=False,
                market="KOSPI",
            ))
            session.flush()
            return 1

        def fake_evaluate(session: Session, target_date: date, **kwargs):
            ev = SurgePredictionEvaluation(
                evaluation_date=target_date,
                predicted_count=0,
                actual_surge_count=0,
                true_positive=0,
                false_positive=0,
                false_negative=0,
                precision=None,
                recall=None,
                f1_score=None,
            )
            session.add(ev)
            session.flush()
            return ev

        with (
            patch(
                "app.services.surge_actual_outcome_service.collect_daily_surge_outcomes",
                side_effect=fake_collect,
            ),
            patch(
                "app.services.surge_evaluation_service.evaluate_surge_predictions",
                side_effect=fake_evaluate,
            ) as mock_evaluate,
        ):
            result = repair_missing_surge_evaluation(
                db,
                trading_date,
                allow_historical_actual_collection=True,
            )

        assert result["status"] == "repaired"
        assert result["actual_collect_attempted"] is True
        assert result["actual_collected_count"] == 1
        assert result["evaluation_attempted"] is True
        assert result["before"]["actual_outcome_missing"] is True
        assert result["after"]["actual_outcome_missing"] is False
        assert result["after"]["evaluation_missing"] is False
        mock_evaluate.assert_called_once()

    def test_repair_skips_evaluation_when_actual_collection_still_empty(
        self, db: Session
    ):
        trading_date = date(2026, 8, 5)

        async def fake_collect(session: Session, target_date: date) -> int:
            return 0

        with (
            patch(
                "app.services.surge_actual_outcome_service.collect_daily_surge_outcomes",
                side_effect=fake_collect,
            ),
            patch(
                "app.services.surge_evaluation_service.evaluate_surge_predictions"
            ) as mock_evaluate,
        ):
            result = repair_missing_surge_evaluation(
                db,
                trading_date,
                allow_historical_actual_collection=True,
            )

        assert result["status"] == "skipped_actual_outcome_missing"
        assert result["actual_collect_attempted"] is True
        assert result["actual_collected_count"] == 0
        assert result["evaluation_attempted"] is False
        mock_evaluate.assert_not_called()

    def test_repair_skips_historical_actual_collection_by_default(
        self, db: Session
    ):
        trading_date = date(2026, 1, 5)

        with (
            patch(
                "app.services.surge_actual_outcome_service.collect_daily_surge_outcomes"
            ) as mock_collect,
            patch(
                "app.services.surge_evaluation_service.evaluate_surge_predictions"
            ) as mock_evaluate,
        ):
            result = repair_missing_surge_evaluation(db, trading_date)

        assert result["status"] == "skipped_historical_actual_collection_unavailable"
        assert result["actual_collect_attempted"] is False
        assert result["evaluation_attempted"] is False
        mock_collect.assert_not_called()
        mock_evaluate.assert_not_called()

    def test_repair_noops_when_records_already_complete(self, db: Session):
        trading_date = date(2026, 8, 6)
        db.add(SurgeActualOutcome(
            trading_date=trading_date,
            stock_code="911092",
            stock_name="완료테스트",
            change_rate=0.5,
            was_surge=False,
            market="KOSPI",
        ))
        db.add(SurgePredictionEvaluation(
            evaluation_date=trading_date,
            predicted_count=0,
            actual_surge_count=0,
            true_positive=0,
            false_positive=0,
            false_negative=0,
            precision=None,
            recall=None,
            f1_score=None,
        ))
        db.commit()

        with (
            patch(
                "app.services.surge_actual_outcome_service.collect_daily_surge_outcomes"
            ) as mock_collect,
            patch(
                "app.services.surge_evaluation_service.evaluate_surge_predictions"
            ) as mock_evaluate,
        ):
            result = repair_missing_surge_evaluation(db, trading_date)

        assert result["status"] == "already_complete"
        assert result["actual_collect_attempted"] is False
        assert result["evaluation_attempted"] is False
        mock_collect.assert_not_called()
        mock_evaluate.assert_not_called()

    def test_scheduler_missing_monitor_attempts_repair(self, monkeypatch):
        import app.services.scheduler as scheduler_module

        fake_db = MagicMock(name="db")
        monkeypatch.setattr(scheduler_module, "_is_kr_market_open", lambda: True)

        with (
            patch.object(scheduler_module, "SessionLocal", return_value=fake_db),
            patch(
                "app.services.surge_evaluation_service.check_and_alert_missing_evaluation",
                return_value={
                    "trading_date": "2026-08-07",
                    "actual_outcome_missing": True,
                    "evaluation_missing": True,
                },
            ),
            patch(
                "app.services.surge_evaluation_service.repair_missing_surge_evaluation",
                return_value={"status": "repaired"},
            ) as mock_repair,
        ):
            scheduler_module._run_surge_missing_evaluation_check()

        mock_repair.assert_called_once_with(fake_db)
        fake_db.close.assert_called_once()
