"""SPEC-AI-106: 지평 인식 임계값 섀도우 전환 게이트 가시성 확립 — 일일 평가 잡 통합 테스트.

AC-106-001: 일일 평가 잡이 readiness 로그 1줄을 기록한다.
AC-106-002: 로그에 4개 필드가 모두 포함된다.
AC-106-003: readiness 예외가 핵심 평가 결과 커밋을 방해하지 않는다.
AC-106-004: 배포 전후 enabled/shadow_mode_enabled 값이 불변이다.
AC-106-008: 호출이 잡 사이클당 1회로 제한되고 기존 회귀 스위트가 전량 통과한다
            (호출 카운트만 이 파일에서 검증 — 회귀 스위트 자체는
            test_spec_ai_100.py/test_spec_ai_101.py 별도 실행으로 확인).
"""

from __future__ import annotations

import logging
from datetime import date
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session

from app.models.sector import Sector
from app.models.stock import Stock
from app.models.surge_actual_outcome import SurgeActualOutcome
from app.models.surge_horizon_shadow_observation import (  # noqa: F401 — Base.metadata 테이블 등록
    SurgeHorizonShadowObservation,
)
from app.models.surge_prediction_evaluation import SurgePredictionEvaluation


def _make_stock(db: Session, code: str) -> Stock:
    sector = Sector(name=f"테스트섹터_{code}", is_custom=False)
    db.add(sector)
    db.flush()
    stock = Stock(stock_code=code, name=f"주식{code}", sector_id=sector.id, market="KOSPI")
    db.add(stock)
    db.flush()
    return stock


def _seed_minimal_actual_outcome(db: Session, trading_date: date) -> None:
    """평가 잡(evaluate_surge_predictions)이 오류 없이 실행되도록 최소 fixture를 시딩한다.

    predicted_set/actual_set이 비어 있어도 evaluate_surge_predictions는 정상 동작하므로
    (test_spec_ai_101.py TestEvaluateSurgePredictionsForwardIntegration 선례), 실제급등주
    1건만 시딩해 정상 실행 경로를 재현한다.
    """
    _make_stock(db, "999999")
    db.add(
        SurgeActualOutcome(
            trading_date=trading_date,
            stock_code="999999",
            stock_name="주식999999",
            change_rate=1.0,
            was_surge=False,
            market="KOSPI",
        )
    )
    db.commit()


# ---------------------------------------------------------------------------
# AC-106-001/002: readiness 로그 1줄 + 4개 필드 포함
# ---------------------------------------------------------------------------


class TestReadinessLogIntegration:
    def test_readiness_log_line_recorded_with_all_fields(
        self, db: Session, monkeypatch, caplog
    ) -> None:
        """정상 실행 시 [지평임계값전환게이트] INFO 로그 1줄이 4개 필드를 모두 포함한다."""
        import app.services.scheduler as scheduler_module

        today = date.today()
        _seed_minimal_actual_outcome(db, today)

        monkeypatch.setattr(scheduler_module, "SessionLocal", lambda: db)
        monkeypatch.setattr(scheduler_module, "_is_kr_market_open", lambda: True)

        with caplog.at_level(logging.INFO, logger="app.services.scheduler"):
            scheduler_module._run_surge_verify_predictions()

        readiness_logs = [
            r for r in caplog.records if "[지평임계값전환게이트]" in r.message
        ]
        assert len(readiness_logs) == 1
        assert readiness_logs[0].levelno == logging.INFO

        message = readiness_logs[0].message
        assert "observed_trading_days=" in message
        assert "regimes=" in message
        assert "max_change_pct=" in message
        assert "all_criteria_met=" in message


# ---------------------------------------------------------------------------
# AC-106-003: readiness 예외 격리 — 핵심 평가 결과 커밋 무영향
# ---------------------------------------------------------------------------


class TestReadinessExceptionIsolation:
    def test_readiness_exception_does_not_block_core_commit(
        self, db: Session, monkeypatch, caplog
    ) -> None:
        """readiness 조회가 예외를 던져도 SurgePredictionEvaluation은 정상 커밋되고,
        경고 로그 1줄만 남으며 INFO 레벨 게이트 로그는 기록되지 않는다."""
        import app.services.scheduler as scheduler_module

        today = date.today()
        _seed_minimal_actual_outcome(db, today)

        monkeypatch.setattr(scheduler_module, "SessionLocal", lambda: db)
        monkeypatch.setattr(scheduler_module, "_is_kr_market_open", lambda: True)

        with (
            patch(
                "app.services.surge_horizon_readiness_service."
                "check_horizon_transition_readiness",
                side_effect=RuntimeError("boom"),
            ),
            caplog.at_level(logging.WARNING, logger="app.services.scheduler"),
        ):
            scheduler_module._run_surge_verify_predictions()

        # 핵심 평가 결과는 정상 커밋된다 (REQ-AI106-004 무영향 확인).
        row = (
            db.query(SurgePredictionEvaluation)
            .filter(SurgePredictionEvaluation.evaluation_date == today)
            .first()
        )
        assert row is not None

        warn_logs = [r for r in caplog.records if "readiness 조회 실패" in r.message]
        assert len(warn_logs) == 1
        assert warn_logs[0].levelno == logging.WARNING

        info_gate_logs = [
            r
            for r in caplog.records
            if "[지평임계값전환게이트]" in r.message and r.levelno == logging.INFO
        ]
        assert info_gate_logs == []


# ---------------------------------------------------------------------------
# AC-106-004: enabled / shadow_mode_enabled 값 불변
# ---------------------------------------------------------------------------


class TestConfigValuesUnchanged:
    def test_enabled_and_shadow_mode_enabled_values_unchanged(self) -> None:
        """본 SPEC의 wiring 변경은 horizon_aware_thresholds.enabled=false,
        .shadow_mode_enabled=true 실제 값을 전혀 건드리지 않는다(SPEC-AI-101이 남긴
        상태 그대로)."""
        from app.surge_config.surge_settings import get_surge_config

        config = get_surge_config()
        horizon_cfg = config.ensemble.horizon_aware_thresholds
        assert horizon_cfg.enabled is False
        assert horizon_cfg.shadow_mode_enabled is True


# ---------------------------------------------------------------------------
# AC-106-008: 호출 카운트 — 잡 1회 실행당 정확히 1회
# ---------------------------------------------------------------------------


class TestReadinessCallCount:
    def test_readiness_called_exactly_once_per_job_cycle(
        self, db: Session, monkeypatch
    ) -> None:
        """check_horizon_transition_readiness가 _run_surge_verify_predictions() 1회
        실행당 정확히 1회만 호출된다 — 매 스코어링 사이클마다 반복 호출되지 않는다."""
        import app.services.scheduler as scheduler_module

        today = date.today()
        _seed_minimal_actual_outcome(db, today)

        monkeypatch.setattr(scheduler_module, "SessionLocal", lambda: db)
        monkeypatch.setattr(scheduler_module, "_is_kr_market_open", lambda: True)

        mock_readiness = MagicMock(
            return_value={
                "observed_trading_days": 3,
                "regimes_observed": {"BULL"},
                "max_change_pct": 5.0,
                "all_criteria_met": False,
            }
        )
        with patch(
            "app.services.surge_horizon_readiness_service."
            "check_horizon_transition_readiness",
            mock_readiness,
        ):
            scheduler_module._run_surge_verify_predictions()

        assert mock_readiness.call_count == 1
