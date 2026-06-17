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
        """예측=A,B,C 실제급등=B,C,D → TP=2, FP=1, FN=1."""
        trading_date = date(2026, 6, 9)
        predicted = ["111111", "222222", "333333"]
        actual_surge = ["222222", "333333", "444444"]

        self._setup_signals_and_outcomes(db, predicted, actual_surge, trading_date)

        from app.services.surge_evaluation_service import evaluate_surge_predictions
        eval_result = evaluate_surge_predictions(db, trading_date)

        assert eval_result.true_positive == 2
        assert eval_result.false_positive == 1
        assert eval_result.false_negative == 1

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
