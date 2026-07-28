"""SPEC-AI-090 M1 인수 테스트.

REQ-AI090-002/003의 신규 읽기 전용 파생 계산(continuation_bar_measurement_service)만
검증한다. 신호 생성 경로(compute_ensemble_score/gather_surge_candidates/
build_scan_universe)와 기존 기여도 집계 경로(evaluate_detector_contribution)는 전혀
호출하지 않으며, 기존 스위트(test_spec_ai_070.py 등)는 이 파일에서 전혀 수정되지 않는다
(별도 diff 0 확인 — 회귀 없음, REQ-AI090-004).

AC-090-002/003 커버.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.models.fund_signal import FundSignal
from app.models.surge_actual_outcome import SurgeActualOutcome
from app.services.continuation_bar_measurement_service import (
    BAR_B_FLOOR_THRESHOLD_PCT,
    BAR_C_GAIN_THRESHOLD_HIGH_PCT,
    BAR_C_GAIN_THRESHOLD_LOW_PCT,
    CRITERION_BAR_B,
    CRITERION_BAR_C_HIGH,
    CRITERION_BAR_C_LOW,
    CRITERION_WAS_SURGE,
    _extract_t1_change_rate,
    _parse_surge_basis,
    classify_continuation_outcome,
    measure_continuation_detector_bars,
)
from app.services.surge_trading_service import _get_prev_business_day

TRADING_DATE = date(2026, 6, 30)
PREV_DAY = _get_prev_business_day(TRADING_DATE)


def _prev_day_dt() -> datetime:
    return datetime(PREV_DAY.year, PREV_DAY.month, PREV_DAY.day, 15, 20, tzinfo=timezone.utc)


def _make_signal(
    db: Session, stock_id: int, surge_metadata: dict, created_at: datetime
) -> FundSignal:
    signal = FundSignal(
        stock_id=stock_id,
        signal="buy",
        signal_type="surge_candidate",
        confidence=0.7,
        reasoning="SPEC-AI-090 테스트 시그널",
        surge_metadata=json.dumps(surge_metadata, ensure_ascii=False),
        created_at=created_at,
    )
    db.add(signal)
    db.flush()
    return signal


def _make_outcome(
    db: Session,
    trading_date: date,
    stock_code: str,
    change_rate: float,
    surge_type: str | None = None,
) -> SurgeActualOutcome:
    outcome = SurgeActualOutcome(
        trading_date=trading_date,
        stock_code=stock_code,
        stock_name=f"주식{stock_code}",
        change_rate=change_rate,
        was_surge=change_rate >= 10.0,
        market="KOSPI",
        surge_type=surge_type,
    )
    db.add(outcome)
    db.flush()
    return outcome


# ---------------------------------------------------------------------------
# AC-090-002: classify_continuation_outcome — 순수 함수 판정 로직
# ---------------------------------------------------------------------------


class TestClassifyContinuationOutcome:
    def test_named_constants_values(self) -> None:
        """REQ-002: 임계값이 하드코딩이 아닌 명명된 상수로 존재한다."""
        assert BAR_B_FLOOR_THRESHOLD_PCT == 0.0
        assert BAR_C_GAIN_THRESHOLD_LOW_PCT == 3.0
        assert BAR_C_GAIN_THRESHOLD_HIGH_PCT == 5.0

    def test_success_when_t_change_rate_meets_threshold(self) -> None:
        assert classify_continuation_outcome(10.0, 5.0, 0.0) == "success"

    def test_boundary_equal_to_threshold_is_success(self) -> None:
        assert classify_continuation_outcome(10.0, 3.0, 3.0) == "success"

    def test_fail_when_t_change_rate_below_threshold(self) -> None:
        assert classify_continuation_outcome(10.0, -1.5, 0.0) == "fail"
        assert classify_continuation_outcome(20.0, 2.9, 3.0) == "fail"

    def test_unmeasurable_when_t_change_rate_missing(self) -> None:
        assert classify_continuation_outcome(10.0, None, 0.0) == "unmeasurable"

    def test_unmeasurable_when_t1_change_rate_non_positive(self) -> None:
        """기준 B/C는 'T-1 변화율이 양수였던 종목'에 대해서만 정의된다(REQ-002)."""
        assert classify_continuation_outcome(0.0, 5.0, 0.0) == "unmeasurable"
        assert classify_continuation_outcome(-3.0, 5.0, 0.0) == "unmeasurable"

    def test_deterministic_repeated_calls(self) -> None:
        """동일 입력에 대해 항상 동일한 판정을 반환한다(순수 함수, AC-090-002)."""
        args = (12.5, 4.2, 3.0)
        results = {classify_continuation_outcome(*args) for _ in range(5)}
        assert results == {"success"}


# ---------------------------------------------------------------------------
# AC-090-003: measure_continuation_detector_bars — 4-기준 병렬 재채점
# ---------------------------------------------------------------------------


class TestMeasureContinuationDetectorBars:
    def test_near_limit_up_carry_solo_signal_all_four_criteria(
        self, db: Session, make_stock
    ) -> None:
        """near_limit_up_carry solo 시그널 — yesterday_change_pct에서 T-1 변화율을
        직접 읽고, T당일 SurgeActualOutcome으로 4-기준 모두 판정한다."""
        stock = make_stock(stock_code="910001")
        _make_signal(
            db,
            stock.id,
            {
                "surge_basis": ["near_limit_up_carry"],
                "yesterday_change_pct": 18.0,
                "near_limit_up_carry": True,
            },
            _prev_day_dt(),
        )
        # T당일 +6% — was_surge(<10%) 미달, 기준B(>=0%) 성공, 기준C@3%/5% 성공
        _make_outcome(db, TRADING_DATE, "910001", change_rate=6.0, surge_type=None)
        db.commit()

        result = measure_continuation_detector_bars(db, [TRADING_DATE])
        nlu = result["near_limit_up_carry"]

        assert nlu["solo_signal_count"] == 1
        assert nlu["measured_dates"] == [TRADING_DATE]
        assert nlu["criteria"][CRITERION_WAS_SURGE]["hit"] == 0
        assert nlu["criteria"][CRITERION_WAS_SURGE]["miss"] == 1
        assert nlu["criteria"][CRITERION_BAR_B]["hit"] == 1
        assert nlu["criteria"][CRITERION_BAR_C_LOW]["hit"] == 1
        assert nlu["criteria"][CRITERION_BAR_C_HIGH]["hit"] == 1
        assert nlu["criteria"][CRITERION_BAR_B]["hit_rate"] == 1.0

    def test_momentum_continuation_uses_surge_actual_outcome_for_t1(
        self, db: Session, make_stock
    ) -> None:
        """momentum_continuation solo 시그널 — surge_metadata에 T-1 변화율이 없으므로
        SurgeActualOutcome(T-1)에서 조회한다(REQ-002 구현 참고)."""
        stock = make_stock(stock_code="910002")
        _make_signal(
            db,
            stock.id,
            {
                "surge_basis": ["momentum_continuation"],
                "momentum_continuation_score": 0.42,
            },
            _prev_day_dt(),
        )
        # T-1 변화율(momentum_continuation 후보 선정 근거) = 8.0%
        _make_outcome(db, PREV_DAY, "910002", change_rate=8.0, surge_type=None)
        # T당일 -2% — 기준B(>=0%) 실패, was_surge 미달
        _make_outcome(db, TRADING_DATE, "910002", change_rate=-2.0, surge_type=None)
        db.commit()

        result = measure_continuation_detector_bars(db, [TRADING_DATE])
        mc = result["momentum_continuation"]

        assert mc["solo_signal_count"] == 1
        assert mc["criteria"][CRITERION_WAS_SURGE]["miss"] == 1
        assert mc["criteria"][CRITERION_BAR_B]["hit"] == 0
        assert mc["criteria"][CRITERION_BAR_B]["miss"] == 1

    def test_combo_signal_excluded_from_solo_measurement(
        self, db: Session, make_stock
    ) -> None:
        """surge_basis가 2개 이상(combo)인 시그널은 solo attribution에서 제외된다
        (evaluate_detector_contribution과 동일 정의, REQ-003)."""
        stock = make_stock(stock_code="910003")
        _make_signal(
            db,
            stock.id,
            {
                "surge_basis": ["momentum_continuation", "volume_breakout"],
                "momentum_continuation_score": 0.3,
            },
            _prev_day_dt(),
        )
        _make_outcome(db, PREV_DAY, "910003", change_rate=7.0, surge_type=None)
        _make_outcome(db, TRADING_DATE, "910003", change_rate=15.0, surge_type="scannable")
        db.commit()

        result = measure_continuation_detector_bars(db, [TRADING_DATE])
        mc = result["momentum_continuation"]

        assert mc["solo_signal_count"] == 0
        assert mc["measured_dates"] == []
        for criterion in mc["criteria"].values():
            assert criterion["hit"] == 0
            assert criterion["miss"] == 0
            assert criterion["unmeasurable"] == 0
            assert criterion["hit_rate"] is None

    def test_unmeasurable_when_t_day_outcome_missing(self, db: Session, make_stock) -> None:
        """T당일 SurgeActualOutcome 행 자체가 없으면 기준 B/C는 측정불가로 분류되고
        분모(hit+miss)에서 제외된다(REQ-002)."""
        stock = make_stock(stock_code="910004")
        _make_signal(
            db,
            stock.id,
            {"surge_basis": ["near_limit_up_carry"], "yesterday_change_pct": 20.0},
            _prev_day_dt(),
        )
        # T당일 SurgeActualOutcome 없음 — 해당 종목은 scannable_codes에도 없음
        db.commit()

        result = measure_continuation_detector_bars(db, [TRADING_DATE])
        nlu = result["near_limit_up_carry"]

        assert nlu["criteria"][CRITERION_WAS_SURGE]["miss"] == 1  # was_surge는 항상 판정 가능
        assert nlu["criteria"][CRITERION_BAR_B]["unmeasurable"] == 1
        assert nlu["criteria"][CRITERION_BAR_C_LOW]["unmeasurable"] == 1
        assert nlu["criteria"][CRITERION_BAR_C_HIGH]["unmeasurable"] == 1
        assert nlu["criteria"][CRITERION_BAR_B]["hit_rate"] is None

    def test_hit_rate_excludes_unmeasurable_from_denominator(
        self, db: Session, make_stock
    ) -> None:
        """측정불가 건수는 hit_rate 분모(hit+miss)에서 제외된다(AC-090-003)."""
        stock_a = make_stock(stock_code="910005")
        stock_b = make_stock(stock_code="910006")
        _make_signal(
            db,
            stock_a.id,
            {"surge_basis": ["near_limit_up_carry"], "yesterday_change_pct": 16.0},
            _prev_day_dt(),
        )
        _make_signal(
            db,
            stock_b.id,
            {"surge_basis": ["near_limit_up_carry"], "yesterday_change_pct": 22.0},
            _prev_day_dt(),
        )
        # A: T당일 성공(+4%), B: T당일 관측치 없음(측정불가)
        _make_outcome(db, TRADING_DATE, "910005", change_rate=4.0, surge_type=None)
        db.commit()

        result = measure_continuation_detector_bars(db, [TRADING_DATE])
        nlu = result["near_limit_up_carry"]

        bar_c_low = nlu["criteria"][CRITERION_BAR_C_LOW]
        assert bar_c_low["hit"] == 1
        assert bar_c_low["miss"] == 0
        assert bar_c_low["unmeasurable"] == 1
        assert bar_c_low["hit_rate"] == 1.0  # 1 / (1+0), unmeasurable 제외

    def test_multiple_sample_dates_aggregation(self, db: Session, make_stock) -> None:
        """복수 표본 거래일의 solo 시그널이 누적 집계된다."""
        day2 = date(2026, 7, 1)  # TRADING_DATE(2026-06-30) 다음 영업일
        prev_day2 = _get_prev_business_day(day2)

        stock1 = make_stock(stock_code="910007")
        stock2 = make_stock(stock_code="910008")

        _make_signal(
            db,
            stock1.id,
            {"surge_basis": ["near_limit_up_carry"], "yesterday_change_pct": 17.0},
            _prev_day_dt(),
        )
        _make_outcome(db, TRADING_DATE, "910007", change_rate=1.0, surge_type=None)

        _make_signal(
            db,
            stock2.id,
            {"surge_basis": ["near_limit_up_carry"], "yesterday_change_pct": 19.0},
            datetime(prev_day2.year, prev_day2.month, prev_day2.day, 15, 20, tzinfo=timezone.utc),
        )
        _make_outcome(db, day2, "910008", change_rate=2.0, surge_type=None)
        db.commit()

        result = measure_continuation_detector_bars(db, [TRADING_DATE, day2])
        nlu = result["near_limit_up_carry"]

        assert nlu["solo_signal_count"] == 2
        assert nlu["measured_dates"] == [TRADING_DATE, day2]
        assert nlu["criteria"][CRITERION_BAR_B]["hit"] == 2

    def test_zero_solo_signals_yields_null_hit_rate(self, db: Session) -> None:
        """solo 시그널이 전혀 없는 날짜만 넘기면 hit_rate는 None(측정 불가 상태를
        명시적으로 나타낸다) — momentum_continuation의 07-20~07-27 프로덕션 관측치와
        동일한 구조적 패턴(§Context)."""
        result = measure_continuation_detector_bars(db, [TRADING_DATE])
        for detector_result in result.values():
            assert detector_result["solo_signal_count"] == 0
            assert detector_result["measured_dates"] == []
            for criterion in detector_result["criteria"].values():
                assert criterion["hit_rate"] is None

    def test_was_surge_hit_when_stock_in_scannable_set(self, db: Session, make_stock) -> None:
        """T당일 scannable 실제급등주에 포함되면 기존 was_surge 기준이 hit으로 집계된다."""
        stock = make_stock(stock_code="910009")
        _make_signal(
            db,
            stock.id,
            {"surge_basis": ["near_limit_up_carry"], "yesterday_change_pct": 25.0},
            _prev_day_dt(),
        )
        _make_outcome(db, TRADING_DATE, "910009", change_rate=12.0, surge_type="scannable")
        db.commit()

        result = measure_continuation_detector_bars(db, [TRADING_DATE])
        nlu = result["near_limit_up_carry"]

        assert nlu["criteria"][CRITERION_WAS_SURGE]["hit"] == 1
        assert nlu["criteria"][CRITERION_WAS_SURGE]["miss"] == 0

    def test_t1_change_rate_missing_marks_bar_criteria_unmeasurable(
        self, db: Session, make_stock
    ) -> None:
        """near_limit_up_carry 시그널에 yesterday_change_pct 키 자체가 없으면 T-1 변화율을
        추출할 수 없어 기준 B/C가 측정불가로 분류된다(방어적 분기)."""
        stock = make_stock(stock_code="910010")
        _make_signal(
            db,
            stock.id,
            {"surge_basis": ["near_limit_up_carry"]},  # yesterday_change_pct 누락
            _prev_day_dt(),
        )
        _make_outcome(db, TRADING_DATE, "910010", change_rate=4.0, surge_type=None)
        db.commit()

        result = measure_continuation_detector_bars(db, [TRADING_DATE])
        nlu = result["near_limit_up_carry"]

        assert nlu["criteria"][CRITERION_BAR_B]["unmeasurable"] == 1
        assert nlu["criteria"][CRITERION_BAR_C_LOW]["unmeasurable"] == 1

    def test_non_target_detector_solo_signal_ignored(self, db: Session, make_stock) -> None:
        """측정 대상 2종 외 탐지기의 solo 시그널은 무시된다(other-detector 분기)."""
        stock = make_stock(stock_code="910011")
        _make_signal(
            db,
            stock.id,
            {"surge_basis": ["volume_breakout"]},
            _prev_day_dt(),
        )
        db.commit()

        result = measure_continuation_detector_bars(db, [TRADING_DATE])
        for detector_result in result.values():
            assert detector_result["solo_signal_count"] == 0


# ---------------------------------------------------------------------------
# 내부 파서 방어적 분기 (malformed surge_metadata)
# ---------------------------------------------------------------------------


class TestParseSurgeBasisDefensiveBranches:
    def test_empty_or_none_metadata_returns_empty_list(self) -> None:
        assert _parse_surge_basis(None) == []
        assert _parse_surge_basis("") == []

    def test_malformed_json_returns_empty_list(self) -> None:
        assert _parse_surge_basis("{not valid json") == []

    def test_non_list_surge_basis_returns_empty_list(self) -> None:
        assert _parse_surge_basis(json.dumps({"surge_basis": "not-a-list"})) == []


class TestExtractT1ChangeRateDefensiveBranches:
    def test_near_limit_up_carry_missing_metadata_returns_none(self, db: Session) -> None:
        assert (
            _extract_t1_change_rate(db, "near_limit_up_carry", None, "000001", PREV_DAY)
            is None
        )

    def test_near_limit_up_carry_malformed_json_returns_none(self, db: Session) -> None:
        assert (
            _extract_t1_change_rate(
                db, "near_limit_up_carry", "{not valid json", "000001", PREV_DAY
            )
            is None
        )
