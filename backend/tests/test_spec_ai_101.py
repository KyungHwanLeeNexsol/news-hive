"""SPEC-AI-101: 급등예측 정답 라벨 재정의(신호가 대비 EOD 최대수익률) +
SPEC-AI-100 섀도우 전환 게이트 실행 테스트.

AC-101-001: 신호가 기준 EOD 최대수익률 계산 정확성
AC-101-002: 평가 잡 재실행 멱등성(upsert)
AC-101-003: price_at_signal NULL / T-1 종가 조회 실패 시 NULL 안전 처리
AC-101-004: 신호가 기준 병렬 recall/precision 산출
AC-101-005: 표준 T-1→T recall/precision/coverage 산출 로직 완전 무변경(characterization)
AC-101-006: 섀도우 비교 결과가 변화 없는 사이클에도 1행 적재
AC-101-007: 섀도우 영속화 실패가 기존 시그널 생성 흐름을 막지 않음
AC-101-010: 전환 게이트 3요건 판정 함수 정확성
AC-101-011: 어떤 코드도 horizon_aware_thresholds.enabled를 자동으로 전환하지 않음
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.models.fund_signal import FundSignal
from app.models.sector import Sector
from app.models.stock import Stock
from app.models.surge_actual_outcome import SurgeActualOutcome
from app.models.surge_horizon_shadow_observation import SurgeHorizonShadowObservation
from app.models.surge_signal_forward_outcome import SurgeSignalForwardOutcome
from app.services.naver_finance import PriceRecord
from app.services.surge_evaluation_service import (
    _compute_forward_max_return,
    _persist_signal_forward_outcomes,
    evaluate_surge_predictions,
)
from app.services.surge_horizon_readiness_service import check_horizon_transition_readiness


def _make_stock(db: Session, code: str) -> Stock:
    sector = Sector(name=f"테스트섹터_{code}", is_custom=False)
    db.add(sector)
    db.flush()
    stock = Stock(stock_code=code, name=f"주식{code}", sector_id=sector.id, market="KOSPI")
    db.add(stock)
    db.flush()
    return stock


# ---------------------------------------------------------------------------
# AC-101-001: 신호가 기준 EOD 최대수익률 계산 정확성 (순수 함수)
# ---------------------------------------------------------------------------


class TestComputeForwardMaxReturn:
    def test_known_values_match_design_formula(self):
        """day_high_price = prev_close × (1 + high_change_rate/100),
        forward_max_return_pct = (day_high_price − price_at_signal) / price_at_signal × 100
        (design.md §B.1)."""
        day_high_price, forward_max_return_pct = _compute_forward_max_return(
            price_at_signal=1050, high_change_rate=20.0, prev_close_price=1000.0
        )
        assert day_high_price == 1200
        assert forward_max_return_pct == pytest.approx(14.2857, abs=1e-3)

    def test_price_at_signal_none_returns_none_none(self):
        assert _compute_forward_max_return(None, 10.0, 1000.0) == (None, None)

    def test_price_at_signal_zero_returns_none_none(self):
        assert _compute_forward_max_return(0, 10.0, 1000.0) == (None, None)

    def test_high_change_rate_none_returns_none_none(self):
        assert _compute_forward_max_return(1000, None, 1000.0) == (None, None)

    def test_prev_close_price_none_returns_none_none(self):
        assert _compute_forward_max_return(1000, 10.0, None) == (None, None)

    def test_prev_close_price_zero_returns_none_none(self):
        assert _compute_forward_max_return(1000, 10.0, 0.0) == (None, None)


# ---------------------------------------------------------------------------
# AC-101-002/003: upsert 멱등성 + NULL 안전 처리 (_persist_signal_forward_outcomes)
# ---------------------------------------------------------------------------


class TestPersistSignalForwardOutcomes:
    def test_upsert_is_idempotent_on_rerun(self, db: Session):
        """동일 (trading_date, fund_signal_id)에 대해 두 번 실행해도 1행만 남는다."""
        stock = _make_stock(db, "111111")
        trading_date = date(2026, 6, 9)
        t_minus_1 = date(2026, 6, 8)

        signal = FundSignal(
            stock_id=stock.id,
            signal="buy",
            signal_type="surge_candidate",
            confidence=0.7,
            reasoning="테스트",
            price_at_signal=1000,
        )
        db.add(signal)
        db.flush()

        db.add(
            SurgeActualOutcome(
                trading_date=trading_date,
                stock_code="111111",
                stock_name="주식111111",
                change_rate=8.0,
                was_surge=False,
                high_change_rate=15.0,
                market="KOSPI",
            )
        )
        db.commit()

        row = SimpleNamespace(
            stock_code="111111", fund_signal_id=signal.id, price_at_signal=1000
        )

        records = [PriceRecord(date="2026.06.08", close=1000)]
        with patch(
            "app.services.naver_finance.fetch_stock_price_history_sync",
            return_value=records,
        ):
            _persist_signal_forward_outcomes(db, trading_date, t_minus_1, [row])
            _persist_signal_forward_outcomes(db, trading_date, t_minus_1, [row])

        count = (
            db.query(SurgeSignalForwardOutcome)
            .filter(
                SurgeSignalForwardOutcome.trading_date == trading_date,
                SurgeSignalForwardOutcome.fund_signal_id == signal.id,
            )
            .count()
        )
        assert count == 1

        saved = (
            db.query(SurgeSignalForwardOutcome)
            .filter(SurgeSignalForwardOutcome.fund_signal_id == signal.id)
            .one()
        )
        assert saved.forward_max_return_pct == pytest.approx(15.0, abs=1e-3)

    def test_price_at_signal_none_persists_null_derived_fields(self, db: Session):
        """price_at_signal이 NULL이면 파생값도 NULL로 저장되고 예외가 발생하지 않는다."""
        stock = _make_stock(db, "222222")
        trading_date = date(2026, 6, 9)
        t_minus_1 = date(2026, 6, 8)

        signal = FundSignal(
            stock_id=stock.id,
            signal="buy",
            signal_type="surge_candidate",
            confidence=0.7,
            reasoning="테스트",
            price_at_signal=None,
        )
        db.add(signal)
        db.flush()
        db.commit()

        row = SimpleNamespace(
            stock_code="222222", fund_signal_id=signal.id, price_at_signal=None
        )

        forward_actual_codes = _persist_signal_forward_outcomes(
            db, trading_date, t_minus_1, [row]
        )

        assert forward_actual_codes == set()
        saved = (
            db.query(SurgeSignalForwardOutcome)
            .filter(SurgeSignalForwardOutcome.fund_signal_id == signal.id)
            .one()
        )
        assert saved.price_at_signal is None
        assert saved.day_high_price is None
        assert saved.forward_max_return_pct is None

    def test_t1_close_lookup_failure_persists_null_without_raising(self, db: Session):
        """T-1 종가 조회 실패(빈 이력) 시 forward_max_return_pct가 NULL로 저장된다."""
        stock = _make_stock(db, "333333")
        trading_date = date(2026, 6, 9)
        t_minus_1 = date(2026, 6, 8)

        signal = FundSignal(
            stock_id=stock.id,
            signal="buy",
            signal_type="surge_candidate",
            confidence=0.7,
            reasoning="테스트",
            price_at_signal=1000,
        )
        db.add(signal)
        db.flush()
        db.commit()

        row = SimpleNamespace(
            stock_code="333333", fund_signal_id=signal.id, price_at_signal=1000
        )

        with patch(
            "app.services.naver_finance.fetch_stock_price_history_sync",
            return_value=[],
        ):
            _persist_signal_forward_outcomes(db, trading_date, t_minus_1, [row])

        saved = (
            db.query(SurgeSignalForwardOutcome)
            .filter(SurgeSignalForwardOutcome.fund_signal_id == signal.id)
            .one()
        )
        assert saved.prev_close_price is None
        assert saved.forward_max_return_pct is None


# ---------------------------------------------------------------------------
# AC-101-004/005: evaluate_surge_predictions 통합 — 병렬 지표 + 표준 지표 무변경
# ---------------------------------------------------------------------------


class TestEvaluateSurgePredictionsForwardIntegration:
    def test_close_based_miss_but_forward_based_hit_reclassified_in_parallel_metric(
        self, db: Session
    ):
        """종가 기준 was_surge=False(FN)이나 신호가 기준 forward_max_return_pct>=10인
        신호가 신규 병렬 지표에서는 TP로 재분류된다(시나리오 1, AC-101-004).
        표준 legacy_recall은 이 신호를 여전히 FN으로 계산한다(AC-101-005, 무변경)."""
        stock = _make_stock(db, "444444")
        trading_date = date(2026, 6, 9)
        t_minus_1 = date(2026, 6, 8)

        signal = FundSignal(
            stock_id=stock.id,
            signal="buy",
            signal_type="surge_candidate",
            confidence=0.7,
            reasoning="테스트",
            surge_metadata='{"surge_basis": ["theme_cluster"], "theme_cluster_score": 0.8}',
            price_at_signal=1050,
            created_at=datetime(
                t_minus_1.year, t_minus_1.month, t_minus_1.day, 15, 20, tzinfo=timezone.utc
            ),
        )
        db.add(signal)

        # 종가 기준 change_rate=7.0 → was_surge=False (legacy FN 유지).
        # 고가 기준 high_change_rate=20.0 → day_high=1000*1.2=1200,
        # forward_max_return_pct=(1200-1050)/1050*100≈14.29% >= 10.0 → forward TP.
        db.add(
            SurgeActualOutcome(
                trading_date=trading_date,
                stock_code="444444",
                stock_name="주식444444",
                change_rate=7.0,
                was_surge=False,
                high_change_rate=20.0,
                market="KOSPI",
            )
        )
        db.commit()

        records = [PriceRecord(date="2026.06.08", close=1000)]
        with patch(
            "app.services.naver_finance.fetch_stock_price_history_sync",
            return_value=records,
        ):
            eval_result = evaluate_surge_predictions(db, trading_date)

        # AC-101-005: 표준 지표는 무변경 — 종가 기준으로 실제급등 0건이므로 FN=0, TP=0.
        assert eval_result.true_positive == 0
        assert eval_result.false_negative == 0

        # AC-101-004: 신규 병렬 지표는 이 신호를 TP로 잡아 recall/precision > 0.
        assert eval_result.forward_based_recall == pytest.approx(1.0, abs=1e-6)
        assert eval_result.forward_based_precision == pytest.approx(1.0, abs=1e-6)

    def test_standard_tp_fp_fn_unchanged_when_no_price_at_signal(self, db: Session):
        """price_at_signal 미설정(기존 컨벤션)인 기존 characterization 시나리오는
        표준 TP/FP/FN이 SPEC-AI-101 적용 이전과 완전히 동일하다(AC-101-005)."""
        trading_date = date(2026, 6, 9)
        predicted_codes = ["555555", "666666", "777777"]
        actual_codes = ["666666", "777777", "888888"]
        t_minus_1 = date(2026, 6, 8)

        all_codes = sorted(set(predicted_codes + actual_codes))
        stocks = {code: _make_stock(db, code) for code in all_codes}

        for code in predicted_codes:
            db.add(
                FundSignal(
                    stock_id=stocks[code].id,
                    signal="buy",
                    signal_type="surge_candidate",
                    confidence=0.7,
                    reasoning="테스트",
                    surge_metadata='{"surge_basis": ["theme_cluster"]}',
                    created_at=datetime(
                        t_minus_1.year, t_minus_1.month, t_minus_1.day, 15, 20,
                        tzinfo=timezone.utc,
                    ),
                )
            )

        for code in actual_codes:
            db.add(
                SurgeActualOutcome(
                    trading_date=trading_date,
                    stock_code=code,
                    stock_name=f"주식{code}",
                    change_rate=12.0,
                    was_surge=True,
                    market="KOSPI",
                )
            )
        db.commit()

        eval_result = evaluate_surge_predictions(db, trading_date)

        assert eval_result.true_positive == 2
        assert eval_result.false_positive == 1
        assert eval_result.false_negative == 1
        # price_at_signal이 전부 NULL이므로 forward_actual_set은 항상 공집합 —
        # precision=0.0(측정 가능, 분모>0), recall은 분모 0으로 NULL 유지.
        assert eval_result.forward_based_precision == pytest.approx(0.0, abs=1e-6)
        assert eval_result.forward_based_recall is None


# ---------------------------------------------------------------------------
# AC-101-006/007: 섀도우 비교 영속화 — 무변화 사이클도 1행, 실패 격리
# ---------------------------------------------------------------------------


class TestShadowComparisonPersistence:
    def test_no_change_cycle_still_persists_one_row(self, db: Session):
        """added/removed가 모두 빈 사이클에도 SurgeHorizonShadowObservation에 1행이
        적재된다(D3, AC-101-006) — 기존 logger.info는 변화가 있을 때만 찍힌다."""
        from app.services.surge_detector import run_horizon_shadow_comparison
        from app.surge_config.surge_settings import get_surge_config

        config = get_surge_config()
        horizon_cfg = config.ensemble.horizon_aware_thresholds
        config = config.model_copy(
            update={
                "ensemble": config.ensemble.model_copy(
                    update={
                        "horizon_aware_thresholds": horizon_cfg.model_copy(
                            update={"enabled": False, "shadow_mode_enabled": True}
                        )
                    }
                )
            }
        )

        run_horizon_shadow_comparison(
            merged={}, qualified_codes=set(), market_regime="BULL", config=config, db=db
        )

        rows = db.query(SurgeHorizonShadowObservation).all()
        assert len(rows) == 1
        assert rows[0].market_regime == "BULL"
        assert rows[0].existing_qualified_count == 0
        assert rows[0].shadow_qualified_count == 0
        assert rows[0].change_pct == 0.0

    def test_persistence_failure_does_not_raise(self, db: Session):
        """영속화(db.add/commit) 실패는 예외를 밖으로 전파하지 않는다(AC-101-007,
        REQ-AI100-007 예외 격리 원칙 재사용)."""
        from app.services.surge_detector import run_horizon_shadow_comparison
        from app.surge_config.surge_settings import get_surge_config

        config = get_surge_config()
        horizon_cfg = config.ensemble.horizon_aware_thresholds
        config = config.model_copy(
            update={
                "ensemble": config.ensemble.model_copy(
                    update={
                        "horizon_aware_thresholds": horizon_cfg.model_copy(
                            update={"enabled": False, "shadow_mode_enabled": True}
                        )
                    }
                )
            }
        )

        with patch.object(db, "commit", side_effect=RuntimeError("boom")):
            # 예외를 던지지 않고 정상 반환해야 한다.
            run_horizon_shadow_comparison(
                merged={}, qualified_codes=set(), market_regime="BULL", config=config, db=db
            )


# ---------------------------------------------------------------------------
# AC-101-010: 전환 게이트 3요건 판정 함수 정확성
# ---------------------------------------------------------------------------


class TestCheckHorizonTransitionReadiness:
    def test_aggregates_days_regimes_and_max_change_pct(self, db: Session):
        """BULL 5일 + SIDEWAYS 3일 + BEAR 2일 관측 fixture로 3요건이 정확히 집계된다.

        10개 서로 다른 달력일(day 1~10)에 1건씩 배정한다 — day_offset은 결정론적이며
        요일/해시 등 비결정적 요소에 의존하지 않는다.
        """
        fixtures = (
            [("BULL", 1, 5.0), ("BULL", 2, 6.0), ("BULL", 3, 7.0), ("BULL", 4, 8.0), ("BULL", 5, 9.0)]
            + [("SIDEWAYS", 6, 3.0), ("SIDEWAYS", 7, 3.0), ("SIDEWAYS", 8, 3.0)]
            + [("BEAR", 9, 40.0), ("BEAR", 10, 2.0)]
        )
        for regime, day, change_pct in fixtures:
            db.add(
                SurgeHorizonShadowObservation(
                    observed_at=datetime(2026, 6, day, 9, 0, tzinfo=timezone.utc),
                    market_regime=regime,
                    existing_qualified_count=10,
                    shadow_qualified_count=10,
                    added_codes_json="[]",
                    removed_codes_json="[]",
                    change_pct=change_pct,
                )
            )
        db.commit()

        result = check_horizon_transition_readiness(db)

        assert result["observed_trading_days"] == 10
        assert result["regimes_observed"] == {"BULL", "SIDEWAYS", "BEAR"}
        assert result["max_change_pct"] == pytest.approx(40.0, abs=1e-6)
        # BEAR 1일이 40% > 30% 임계값이므로 전체 충족은 False.
        assert result["all_criteria_met"] is False

    def test_empty_observations_returns_zero_and_not_met(self, db: Session):
        result = check_horizon_transition_readiness(db)
        assert result["observed_trading_days"] == 0
        assert result["regimes_observed"] == set()
        assert result["max_change_pct"] == 0.0
        assert result["all_criteria_met"] is False


# ---------------------------------------------------------------------------
# AC-101-011: enabled 플래그를 자동으로 True로 전환하는 코드가 없다 (grep)
# ---------------------------------------------------------------------------


class TestNoAutoEnabledTransition:
    def test_no_source_file_sets_enabled_to_true(self):
        """app/services/, app/surge_config/ 어떤 파일도 horizon_aware_thresholds.enabled를
        프로그램적으로 True로 설정하지 않는다(D5, REQ-AI101-005/AC-101-011).

        subprocess grep 대신 순수 Python 스캔을 사용한다 — Windows 환경에서 `grep`
        실행 파일 PATH 가용성에 의존하지 않기 위함.
        """
        pattern = re.compile(
            r"horizon_aware_thresholds\.enabled\s*=\s*True"
            r"|horizon_aware_thresholds\[.enabled.\]\s*="
        )
        backend_root = Path(__file__).resolve().parent.parent
        offenders: list[str] = []
        for base in ("app/services", "app/surge_config"):
            for py_file in (backend_root / base).rglob("*.py"):
                text = py_file.read_text(encoding="utf-8")
                if pattern.search(text):
                    offenders.append(str(py_file))
        assert offenders == [], f"자동 전환 코드 발견: {offenders}"
