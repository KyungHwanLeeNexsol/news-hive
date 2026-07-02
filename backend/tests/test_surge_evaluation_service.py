"""SPEC-AI-041: surge_evaluation_service 단위 테스트."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.models.surge_actual_outcome import SurgeActualOutcome


# ---------------------------------------------------------------------------
# T-1 영업일 계산 테스트
# ---------------------------------------------------------------------------

class TestGetPrevBusinessDay:
    def test_monday_returns_friday(self):
        """월요일의 T-1은 직전 금요일이어야 한다."""
        from app.services.surge_trading_service import _get_prev_business_day

        # 2026-06-08은 월요일 (weekday=0)
        monday = date(2026, 6, 8)
        assert monday.weekday() == 0, f"{monday}는 월요일이 아님 (weekday={monday.weekday()})"
        prev = _get_prev_business_day(monday)
        assert prev.weekday() == 4, f"직전 영업일이 금요일이어야 함: {prev} (weekday={prev.weekday()})"
        assert prev == date(2026, 6, 5)

    def test_tuesday_returns_monday(self):
        """화요일의 T-1은 직전 월요일."""
        from app.services.surge_trading_service import _get_prev_business_day

        # 2026-06-09는 화요일
        tuesday = date(2026, 6, 9)
        assert tuesday.weekday() == 1, f"{tuesday}는 화요일이 아님"
        prev = _get_prev_business_day(tuesday)
        assert prev == date(2026, 6, 8)

    def test_wednesday_returns_tuesday(self):
        """수요일의 T-1은 화요일."""
        from app.services.surge_trading_service import _get_prev_business_day

        # 2026-06-10은 수요일
        wednesday = date(2026, 6, 10)
        assert wednesday.weekday() == 2, f"{wednesday}는 수요일이 아님"
        prev = _get_prev_business_day(wednesday)
        assert prev == date(2026, 6, 9)


# ---------------------------------------------------------------------------
# TP/FP/FN 계산 테스트
# ---------------------------------------------------------------------------

class TestTPFPFNCalculation:
    def _setup_signals_and_outcomes(
        self,
        db: Session,
        predicted_codes: list[str],
        actual_surge_codes: list[str],
        trading_date: date,
    ):
        """FundSignal + SurgeActualOutcome을 테스트용으로 셋업한다."""
        from datetime import datetime, timezone
        from app.models.stock import Stock
        from app.models.fund_signal import FundSignal

        stocks: dict[str, int] = {}
        all_codes = list(set(predicted_codes + actual_surge_codes))

        for i, code in enumerate(all_codes):
            # 섹터가 없으면 생성
            from app.models.sector import Sector
            sector = Sector(name=f"테스트섹터_{i}", is_custom=False)
            db.add(sector)
            db.flush()

            stock = Stock(
                stock_code=code,
                name=f"주식{code}",
                sector_id=sector.id,
                market="KOSPI",
            )
            db.add(stock)
            db.flush()
            stocks[code] = stock.id

        # T-1 날짜 계산
        from app.services.surge_trading_service import _get_prev_business_day
        t_minus_1 = _get_prev_business_day(trading_date)

        for code in predicted_codes:
            signal = FundSignal(
                stock_id=stocks[code],
                signal="buy",
                signal_type="surge_candidate",
                confidence=0.7,
                reasoning="테스트",
                surge_metadata='{"surge_basis": ["theme_cluster"], "theme_cluster_score": 0.8}',
                created_at=datetime(t_minus_1.year, t_minus_1.month, t_minus_1.day, 15, 20, tzinfo=timezone.utc),
            )
            db.add(signal)

        for code in actual_surge_codes:
            outcome = SurgeActualOutcome(
                trading_date=trading_date,
                stock_code=code,
                stock_name=f"주식{code}",
                change_rate=12.0,
                was_surge=True,
                market="KOSPI",
            )
            db.add(outcome)

        db.commit()

    def test_tp_fp_fn_calculation(self, db):
        """예측=A,B,C 실제급등=B,C,D → TP=2, FP=1, FN=1.

        surge_actual_outcome이 스캔 유니버스이므로 추가 필터 없이 was_surge=True 전체를 actual로 사용.
        D(444444)는 예측하지 못했으므로 FN=1.
        """
        trading_date = date(2026, 6, 9)
        predicted = ["111111", "222222", "333333"]
        actual_surge = ["222222", "333333", "444444"]

        self._setup_signals_and_outcomes(db, predicted, actual_surge, trading_date)

        from app.services.surge_evaluation_service import evaluate_surge_predictions
        eval_result = evaluate_surge_predictions(db, trading_date)

        assert eval_result.true_positive == 2
        assert eval_result.false_positive == 1
        assert eval_result.false_negative == 1  # 444444는 예측 못한 실제 급등 → FN

    def test_zero_denominator_precision(self, db):
        """TP=0, FP=0 일 때 precision=0.0 (ZeroDivisionError 방지)."""
        trading_date = date(2026, 6, 9)
        # 예측 없음, 실제 급등 없음
        self._setup_signals_and_outcomes(db, [], [], trading_date)

        from app.services.surge_evaluation_service import evaluate_surge_predictions
        eval_result = evaluate_surge_predictions(db, trading_date)

        assert eval_result.precision == 0.0
        assert eval_result.recall == 0.0
        assert eval_result.f1_score == 0.0

    def test_perfect_precision(self, db):
        """모든 예측이 적중 → precision=1.0."""
        trading_date = date(2026, 6, 9)
        codes = ["555555", "666666"]
        self._setup_signals_and_outcomes(db, codes, codes, trading_date)

        from app.services.surge_evaluation_service import evaluate_surge_predictions
        eval_result = evaluate_surge_predictions(db, trading_date)

        assert abs((eval_result.precision or 0.0) - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# analyze_misses_with_llm — LLM 실패 시 fallback 테스트
# ---------------------------------------------------------------------------

class TestAnalyzeMissesWithLLMFallback:
    @pytest.mark.asyncio
    async def test_empty_missed_stocks_returns_no_fn_message(self, db):
        """FN=0 → '미스 종목 없음' 반환."""
        from app.services.surge_evaluation_service import analyze_misses_with_llm

        result = await analyze_misses_with_llm([], db)
        assert "FN=0" in result or "없음" in result

    @pytest.mark.asyncio
    async def test_llm_failure_returns_fallback(self, db):
        """LLM 예외 → rule-based fallback 반환 (TypeError 없음)."""
        from app.services.surge_evaluation_service import analyze_misses_with_llm

        missed = [{"stock_code": "000001", "change_rate": 12.0, "stock_name": "테스트"}]

        with patch(
            "app.services.surge_evaluation_service.ask_ai_with_openai_fallback",
            side_effect=RuntimeError("API 한도 초과"),
        ):
            result = await analyze_misses_with_llm(missed, db)

        assert result is not None
        assert len(result) > 0
        # fallback에는 수동 검토 관련 텍스트 포함
        assert "000001" in result or "수동" in result


# ---------------------------------------------------------------------------
# SPEC-AI-068 T-004: evaluate_surge_predictions PRESERVE 특성화 테스트
#
# T-005에서 evaluate_surge_predictions()를 재작성(Scannable Recall/Coverage 도입)하기 전,
# 현행 동작을 고정한다. 이 클래스의 모든 테스트는 재작성 이후에도 그대로 GREEN이어야 한다
# (레거시 predicted_count/actual_surge_count/TP/FP/FN/precision/recall/pool_counts/upsert/commit
# 동작은 REQ-AI068-002~004 범위에서 보존 대상).
# ---------------------------------------------------------------------------

class TestEvaluateSurgePredictionsCharacterization:
    """PRESERVE 불변식 표(progress.md 참조) 스냅샷 고정."""

    def _setup(
        self,
        db: Session,
        predicted_codes: list[str],
        actual_surge_codes: list[str],
        trading_date: date,
    ):
        """TestTPFPFNCalculation._setup_signals_and_outcomes와 동일한 셋업 헬퍼(독립 복제)."""
        from datetime import datetime, timezone
        from app.models.stock import Stock
        from app.models.fund_signal import FundSignal
        from app.models.sector import Sector
        from app.services.surge_trading_service import _get_prev_business_day

        stocks: dict[str, int] = {}
        all_codes = list(set(predicted_codes + actual_surge_codes))

        for i, code in enumerate(all_codes):
            sector = Sector(name=f"특성화섹터_{code}_{i}", is_custom=False)
            db.add(sector)
            db.flush()

            stock = Stock(
                stock_code=code,
                name=f"주식{code}",
                sector_id=sector.id,
                market="KOSPI",
            )
            db.add(stock)
            db.flush()
            stocks[code] = stock.id

        t_minus_1 = _get_prev_business_day(trading_date)

        for code in predicted_codes:
            signal = FundSignal(
                stock_id=stocks[code],
                signal="buy",
                signal_type="surge_candidate",
                confidence=0.7,
                reasoning="특성화 테스트",
                surge_metadata='{"surge_basis": ["theme_cluster"], "theme_cluster_score": 0.8}',
                created_at=datetime(
                    t_minus_1.year, t_minus_1.month, t_minus_1.day, 15, 20, tzinfo=timezone.utc
                ),
            )
            db.add(signal)

        for code in actual_surge_codes:
            outcome = SurgeActualOutcome(
                trading_date=trading_date,
                stock_code=code,
                stock_name=f"주식{code}",
                change_rate=12.0,
                was_surge=True,
                market="KOSPI",
            )
            db.add(outcome)

        db.commit()
        return t_minus_1

    def test_characterize_predicted_count_from_t_minus_1_surge_candidate_signals(self, db: Session):
        """predicted_count = T-1 surge_candidate ∩ Stock join 종목수 (:515-526)."""
        trading_date = date(2026, 6, 9)
        self._setup(db, ["111111", "222222"], [], trading_date)

        from app.services.surge_evaluation_service import evaluate_surge_predictions
        result = evaluate_surge_predictions(db, trading_date)

        assert result.predicted_count == 2

    def test_characterize_actual_surge_count_from_was_surge_market_wide(self, db: Session):
        """actual_surge_count = SurgeActualOutcome(was_surge=True) 종목수, 유니버스 필터 없음 (:536-548)."""
        trading_date = date(2026, 6, 9)
        self._setup(db, [], ["333333", "444444", "555555"], trading_date)

        from app.services.surge_evaluation_service import evaluate_surge_predictions
        result = evaluate_surge_predictions(db, trading_date)

        assert result.actual_surge_count == 3

    def test_characterize_true_positive_is_predicted_intersect_actual(self, db: Session):
        """true_positive = predicted ∩ actual(시장전체 기준) (:551)."""
        trading_date = date(2026, 6, 9)
        self._setup(db, ["A1", "A2", "A3"], ["A2", "A3", "A4"], trading_date)

        from app.services.surge_evaluation_service import evaluate_surge_predictions
        result = evaluate_surge_predictions(db, trading_date)

        assert result.true_positive == 2  # A2, A3

    def test_characterize_false_positive_is_predicted_minus_actual(self, db: Session):
        """false_positive = predicted − actual (:552)."""
        trading_date = date(2026, 6, 9)
        self._setup(db, ["B1", "B2", "B3"], ["B2"], trading_date)

        from app.services.surge_evaluation_service import evaluate_surge_predictions
        result = evaluate_surge_predictions(db, trading_date)

        assert result.false_positive == 2  # B1, B3

    def test_characterize_precision_zero_denominator_returns_zero(self, db: Session):
        """precision = TP/(TP+FP), 분모 0이면 0.0 (:555)."""
        trading_date = date(2026, 6, 9)
        self._setup(db, [], [], trading_date)

        from app.services.surge_evaluation_service import evaluate_surge_predictions
        result = evaluate_surge_predictions(db, trading_date)

        assert result.precision == 0.0

    def test_characterize_pool_counts_passthrough_on_insert(self, db: Session):
        """pool_counts 전달 시 scan_universe_size/pool_a/b/c_count가 그대로 저장된다 (:568-595)."""
        trading_date = date(2026, 6, 9)
        self._setup(db, [], [], trading_date)

        from app.services.surge_evaluation_service import evaluate_surge_predictions
        result = evaluate_surge_predictions(
            db,
            trading_date,
            pool_counts={"pool_a": 3, "pool_b": 5, "pool_c": 7, "scan_universe_size": 42},
        )

        assert result.pool_a_count == 3
        assert result.pool_b_count == 5
        assert result.pool_c_count == 7
        assert result.scan_universe_size == 42

    def test_characterize_pool_counts_default_zero_when_none(self, db: Session):
        """pool_counts=None(기본값) 신규 삽입 시 pool_*_count/scan_universe_size는 0."""
        trading_date = date(2026, 6, 9)
        self._setup(db, [], [], trading_date)

        from app.services.surge_evaluation_service import evaluate_surge_predictions
        result = evaluate_surge_predictions(db, trading_date)

        assert result.pool_a_count == 0
        assert result.pool_b_count == 0
        assert result.pool_c_count == 0
        assert result.scan_universe_size == 0

    def test_characterize_pool_counts_preserved_on_update_when_none(self, db: Session):
        """기존 레코드가 있고 재호출 시 pool_counts=None이면 기존 pool_* 값을 덮어쓰지 않는다 (:590-595)."""
        trading_date = date(2026, 6, 9)
        self._setup(db, [], [], trading_date)

        from app.services.surge_evaluation_service import evaluate_surge_predictions

        evaluate_surge_predictions(
            db,
            trading_date,
            pool_counts={"pool_a": 9, "pool_b": 9, "pool_c": 9, "scan_universe_size": 99},
        )
        result = evaluate_surge_predictions(db, trading_date, pool_counts=None)

        assert result.pool_a_count == 9
        assert result.pool_b_count == 9
        assert result.pool_c_count == 9
        assert result.scan_universe_size == 99

    def test_characterize_upsert_idempotency_same_evaluation_date(self, db: Session):
        """evaluation_date PK 기준 upsert — 재호출 시 새 행이 아니라 기존 행이 갱신된다 (:574-616)."""
        trading_date = date(2026, 6, 9)
        self._setup(db, ["C1"], ["C1"], trading_date)

        from app.services.surge_evaluation_service import evaluate_surge_predictions
        from app.models.surge_prediction_evaluation import SurgePredictionEvaluation

        first = evaluate_surge_predictions(db, trading_date)
        first_count = (
            db.query(SurgePredictionEvaluation)
            .filter(SurgePredictionEvaluation.evaluation_date == trading_date)
            .count()
        )
        assert first_count == 1
        assert first.true_positive == 1

        # 동일 trading_date로 재호출 — 신규 행이 생기지 않고 기존 evaluation_date PK 행이 갱신되어야 한다
        second = evaluate_surge_predictions(db, trading_date)
        second_count = (
            db.query(SurgePredictionEvaluation)
            .filter(SurgePredictionEvaluation.evaluation_date == trading_date)
            .count()
        )
        assert second_count == 1, "동일 evaluation_date는 upsert되어 행이 늘어나지 않아야 한다"
        assert second.true_positive == 1

    def test_characterize_commit_is_called(self, db: Session):
        """db.commit() 호출 발생 — AI-061 트랜잭션 안전성 패턴 보존 (:618)."""
        trading_date = date(2026, 6, 9)
        self._setup(db, ["D1"], ["D1"], trading_date)

        from app.services.surge_evaluation_service import evaluate_surge_predictions

        with patch.object(db, "commit", wraps=db.commit) as mock_commit:
            evaluate_surge_predictions(db, trading_date)

        assert mock_commit.called


# ---------------------------------------------------------------------------
# SPEC-AI-068 T-005: Scannable Recall / Coverage 신규 지표 테스트
#
# acceptance.md Scenario 1 손계산 대조 + EC-1/EC-2/EC-3 검증.
# ---------------------------------------------------------------------------

def _seed_predicted_and_actual(
    db: Session,
    predicted_codes: list[str],
    actual_surge_codes: list[str],
    trading_date: date,
):
    """FundSignal(T-1 predicted) + SurgeActualOutcome(T actual)을 셋업하고 T-1 날짜를 반환한다."""
    from datetime import datetime, timezone
    from app.models.stock import Stock
    from app.models.sector import Sector
    from app.models.fund_signal import FundSignal
    from app.services.surge_trading_service import _get_prev_business_day

    stocks: dict[str, int] = {}
    all_codes = list(set(predicted_codes + actual_surge_codes))

    for i, code in enumerate(all_codes):
        sector = Sector(name=f"스캔유니버스섹터_{code}_{i}", is_custom=False)
        db.add(sector)
        db.flush()
        stock = Stock(stock_code=code, name=f"주식{code}", sector_id=sector.id, market="KOSPI")
        db.add(stock)
        db.flush()
        stocks[code] = stock.id

    t_minus_1 = _get_prev_business_day(trading_date)

    for code in predicted_codes:
        db.add(
            FundSignal(
                stock_id=stocks[code],
                signal="buy",
                signal_type="surge_candidate",
                confidence=0.7,
                reasoning="scannable recall 테스트",
                surge_metadata='{"surge_basis": ["theme_cluster"], "theme_cluster_score": 0.8}',
                created_at=datetime(
                    t_minus_1.year, t_minus_1.month, t_minus_1.day, 15, 20, tzinfo=timezone.utc
                ),
            )
        )

    for code in actual_surge_codes:
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
    return t_minus_1


class TestScannableRecallAndCoverage:
    def test_scenario1_scannable_recall_and_coverage_hand_calculated(self, db: Session):
        """acceptance.md Scenario 1 손계산 대조.

        T-1 유니버스={A,B,C,D}, 실제급등={A,B,X,Y,Z}(전체5), 발신={A}.
        기대: scannable_actual_count=2({A,B}), total_actual_count=5,
        scannable_recall=1/2=0.5(발신{A}∩scannable_actual{A,B}), coverage=2/5=0.4.
        레거시 recall 컬럼도 유니버스 존재 시 scannable_recall(0.5)로 전환된다.
        """
        trading_date = date(2026, 7, 1)
        predicted = ["A"]
        actual = ["A", "B", "X", "Y", "Z"]

        t_minus_1 = _seed_predicted_and_actual(db, predicted, actual, trading_date)

        from app.services.surge_universe_pool_service import persist_universe_members

        persist_universe_members(
            db,
            t_minus_1,
            ["A", "B", "C", "D"],
            {"A": "pool_a", "B": "pool_b", "C": "pool_b", "D": "pool_c"},
        )
        db.commit()

        from app.services.surge_evaluation_service import evaluate_surge_predictions
        result = evaluate_surge_predictions(db, trading_date)

        # 손계산 대조
        assert result.scannable_actual_count == 2
        assert result.total_actual_count == 5
        assert abs((result.scannable_recall or 0.0) - 0.5) < 1e-9
        assert abs((result.coverage or 0.0) - 0.4) < 1e-9

        # 시장전체 기준 TP/FP/FN/precision은 변경 없이 유지 (REQ-004 예시 정합)
        assert result.true_positive == 1  # A
        assert result.false_positive == 0
        assert result.false_negative == 4  # B, X, Y, Z
        assert abs((result.precision or 0.0) - 1.0) < 1e-9

        # 레거시 recall 컬럼은 유니버스 존재 시 scannable_recall로 전환
        assert abs((result.recall or 0.0) - 0.5) < 1e-9

    def test_ec1_zero_scannable_intersection_recall_is_null_but_coverage_computed(self, db: Session):
        """EC-1: 유니버스 존재하지만 실제급등과 교집합이 0 → scannable_recall=null.

        coverage는 EC-2(유니버스 부재)와 달리 유니버스가 실제로 존재하므로 0.0으로 계산된다
        (측정 불가가 아니라 "커버리지 0%"라는 유효한 값).
        """
        trading_date = date(2026, 7, 1)
        actual = ["M", "N"]
        t_minus_1 = _seed_predicted_and_actual(db, [], actual, trading_date)

        from app.services.surge_universe_pool_service import persist_universe_members

        # 유니버스에는 실제급등(M,N)과 겹치지 않는 종목만 존재
        persist_universe_members(db, t_minus_1, ["Q1", "Q2"], {"Q1": "pool_a", "Q2": "pool_b"})
        db.commit()

        from app.services.surge_evaluation_service import evaluate_surge_predictions
        result = evaluate_surge_predictions(db, trading_date)

        assert result.scannable_actual_count == 0
        assert result.scannable_recall is None
        assert result.coverage == 0.0  # 실제급등 2건 중 유니버스 포함 0건

    def test_ec2_no_persisted_universe_both_metrics_null_legacy_recall_preserved(self, db: Session):
        """EC-2: T-1 유니버스가 영속화되어 있지 않은 과거 날짜.

        scannable_recall/coverage 모두 null(coverage-미상)이며, recall 컬럼은 레거시
        시장전체 기준 값을 그대로 유지한다(REQ-AI068-004, 유니버스 백필 없음).
        """
        trading_date = date(2026, 7, 1)
        predicted = ["P1", "P2"]
        actual = ["P1", "P3"]
        _seed_predicted_and_actual(db, predicted, actual, trading_date)
        # 유니버스는 의도적으로 영속화하지 않음 (과거 미백필 시뮬레이션)

        from app.services.surge_evaluation_service import evaluate_surge_predictions
        result = evaluate_surge_predictions(db, trading_date)

        assert result.scannable_recall is None
        assert result.coverage is None
        assert result.scannable_actual_count == 0
        assert result.total_actual_count == 2

        # 레거시 recall: tp=1(P1), fn=1(P3) → 1/(1+1)=0.5
        assert abs((result.recall or 0.0) - 0.5) < 1e-9

    def test_ec3_zero_total_actual_coverage_is_null(self, db: Session):
        """EC-3: 실제급등주 0건 → coverage=null (분모 0)."""
        trading_date = date(2026, 7, 1)
        t_minus_1 = _seed_predicted_and_actual(db, ["R1"], [], trading_date)

        from app.services.surge_universe_pool_service import persist_universe_members

        persist_universe_members(db, t_minus_1, ["R1"], {"R1": "pool_a"})
        db.commit()

        from app.services.surge_evaluation_service import evaluate_surge_predictions
        result = evaluate_surge_predictions(db, trading_date)

        assert result.total_actual_count == 0
        assert result.coverage is None
        assert result.scannable_recall is None  # scannable_actual도 0이므로 null

    def test_false_negative_semantics_unchanged_market_wide(self, db: Session):
        """false_negative 컬럼 의미는 변경되지 않는다 — 항상 시장전체(actual_set) 기준 유지."""
        trading_date = date(2026, 7, 1)
        t_minus_1 = _seed_predicted_and_actual(db, ["S1"], ["S1", "S2", "S3"], trading_date)

        from app.services.surge_universe_pool_service import persist_universe_members

        # 유니버스는 S1만 포함 (S2, S3는 유니버스 밖)
        persist_universe_members(db, t_minus_1, ["S1"], {"S1": "pool_a"})
        db.commit()

        from app.services.surge_evaluation_service import evaluate_surge_predictions
        result = evaluate_surge_predictions(db, trading_date)

        # false_negative는 시장전체 기준: actual{S1,S2,S3} - predicted{S1} = {S2,S3} → 2
        # (유니버스 밖의 S2, S3도 여전히 FN에 포함되어야 함 — coverage 지표와는 별개)
        assert result.false_negative == 2


# ---------------------------------------------------------------------------
# SPEC-AI-068 T-006: 급등 유형 라벨링(surge_type scannable/non_scannable)
#
# acceptance.md Scenario 3 검증.
# ---------------------------------------------------------------------------

class TestSurgeTypeLabeling:
    def test_scenario3_scannable_and_non_scannable_labels(self, db: Session):
        """Scenario 3: 실제급등 {A(유니버스 포함), X(유니버스 미포함)}.

        A는 surge_type='scannable', X는 surge_type='non_scannable'로 저장된다.
        """
        trading_date = date(2026, 7, 1)
        actual = ["A", "X"]
        t_minus_1 = _seed_predicted_and_actual(db, [], actual, trading_date)

        from app.services.surge_universe_pool_service import persist_universe_members

        persist_universe_members(db, t_minus_1, ["A"], {"A": "pool_a"})
        db.commit()

        from app.services.surge_evaluation_service import evaluate_surge_predictions
        evaluate_surge_predictions(db, trading_date)

        outcome_a = (
            db.query(SurgeActualOutcome)
            .filter(
                SurgeActualOutcome.trading_date == trading_date,
                SurgeActualOutcome.stock_code == "A",
            )
            .first()
        )
        outcome_x = (
            db.query(SurgeActualOutcome)
            .filter(
                SurgeActualOutcome.trading_date == trading_date,
                SurgeActualOutcome.stock_code == "X",
            )
            .first()
        )

        assert outcome_a is not None and outcome_a.surge_type == "scannable"
        assert outcome_x is not None and outcome_x.surge_type == "non_scannable"

    def test_no_universe_all_actual_outcomes_labeled_non_scannable(self, db: Session):
        """유니버스가 영속화되지 않은 날짜는 모든 실제급등주가 non_scannable로 라벨링된다."""
        trading_date = date(2026, 7, 1)
        _seed_predicted_and_actual(db, [], ["Y1", "Y2"], trading_date)
        # 유니버스 미영속화

        from app.services.surge_evaluation_service import evaluate_surge_predictions
        evaluate_surge_predictions(db, trading_date)

        rows = (
            db.query(SurgeActualOutcome)
            .filter(SurgeActualOutcome.trading_date == trading_date)
            .all()
        )
        assert {r.stock_code: r.surge_type for r in rows} == {
            "Y1": "non_scannable",
            "Y2": "non_scannable",
        }

    def test_labeling_does_not_affect_evaluation_metrics(self, db: Session):
        """surge_type 라벨링은 별도 트랜잭션 — SurgePredictionEvaluation 결과에 영향 없음."""
        trading_date = date(2026, 7, 1)
        t_minus_1 = _seed_predicted_and_actual(db, ["Z1"], ["Z1"], trading_date)

        from app.services.surge_universe_pool_service import persist_universe_members

        persist_universe_members(db, t_minus_1, ["Z1"], {"Z1": "pool_a"})
        db.commit()

        from app.services.surge_evaluation_service import evaluate_surge_predictions
        result = evaluate_surge_predictions(db, trading_date)

        assert result.true_positive == 1
        assert result.scannable_recall == 1.0

    def test_labeling_exception_is_fail_open_does_not_raise(self, db: Session):
        """surge_type 라벨링 쿼리 실패 시 evaluate_surge_predictions는 예외를 전파하지 않는다.

        (AI-061 B01/B02 격리 패턴 — 핵심 평가 결과는 라벨링 이전에 이미 commit되어 있다.
        이 테스트가 검증하는 것은 "라벨링 실패가 잡 전체를 죽이지 않는다"는 fail-open 계약이다.)
        """
        trading_date = date(2026, 7, 1)
        t_minus_1 = _seed_predicted_and_actual(db, ["W1"], ["W1"], trading_date)

        from app.services.surge_universe_pool_service import persist_universe_members

        persist_universe_members(db, t_minus_1, ["W1"], {"W1": "pool_a"})
        db.commit()

        from app.services.surge_evaluation_service import evaluate_surge_predictions

        # 라벨링 단계는 db.query(SurgeActualOutcome) 전체 엔티티 조회로 실제급등주 행을
        # 가져온다(3단계의 actual_set 조회는 컬럼 단위 조회라 구분 가능). 이 호출만 실패시켜
        # fail-open 경로(except + rollback)를 재현한다.
        original_query = db.query

        def _query_side_effect(*args, **kwargs):
            if args and args[0] is SurgeActualOutcome:
                raise RuntimeError("의도적 라벨링 쿼리 실패")
            return original_query(*args, **kwargs)

        with patch.object(db, "query", side_effect=_query_side_effect):
            # 예외가 전파되지 않아야 한다 (raise되면 이 호출 자체가 테스트를 실패시킴)
            evaluate_surge_predictions(db, trading_date)


class TestScannableMetricsExceptionFailOpen:
    def test_universe_lookup_exception_nulls_metrics_but_evaluation_succeeds(self, db: Session):
        """get_universe_members_for_date 조회 실패 시 scannable_recall/coverage만 null 처리되고
        평가 잡 자체는 정상 완료된다 (REQ-004 리스크 완화, EC-4류 조인 실패와 동일한 fail-open)."""
        trading_date = date(2026, 7, 1)
        self_codes = ["V1"]
        _seed_predicted_and_actual(db, self_codes, self_codes, trading_date)
        # 유니버스는 영속화하지 않고, get_universe_members_for_date 자체가 예외를 던지도록 강제

        from app.services.surge_evaluation_service import evaluate_surge_predictions

        with patch(
            "app.services.surge_universe_pool_service.get_universe_members_for_date",
            side_effect=RuntimeError("의도적 조회 실패"),
        ):
            result = evaluate_surge_predictions(db, trading_date)

        assert result.true_positive == 1
        assert result.scannable_recall is None
        assert result.coverage is None
        # 레거시 recall은 여전히 시장전체 기준으로 계산되어 저장됨 (tp=1, fn=0 → 1.0)
        assert abs((result.recall or 0.0) - 1.0) < 1e-9


class TestPoolCountsUpdatePath:
    def test_pool_counts_applied_on_existing_row_update(self, db: Session):
        """기존 evaluation 행이 있고 pool_counts가 전달되면 update 경로에서 값이 반영된다."""
        trading_date = date(2026, 7, 1)
        _seed_predicted_and_actual(db, ["U1"], ["U1"], trading_date)

        from app.services.surge_evaluation_service import evaluate_surge_predictions

        # 1차: 신규 insert (pool_counts 없음)
        evaluate_surge_predictions(db, trading_date)

        # 2차: 동일 날짜 재호출 — update 경로 + pool_counts 전달
        result = evaluate_surge_predictions(
            db,
            trading_date,
            pool_counts={"pool_a": 1, "pool_b": 2, "pool_c": 3, "scan_universe_size": 6},
        )

        assert result.pool_a_count == 1
        assert result.pool_b_count == 2
        assert result.pool_c_count == 3
        assert result.scan_universe_size == 6
