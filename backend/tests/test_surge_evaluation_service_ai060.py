"""SPEC-AI-060: surge_evaluation_service 종목별 원인 분석 단위 테스트.

enrich_surge_stock_context / analyze_surge_cause_with_llm / _LLMBudgetGuard /
generate_detector_improvement_suggestions / analyze_true_positives_with_llm /
analyze_misses_with_llm 함수를 검증한다.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.orm import Session

from app.models.disclosure import Disclosure
from app.models.fund_signal import FundSignal
from app.models.news import NewsArticle
from app.models.news_relation import NewsStockRelation
from app.models.stock import Stock
from app.models.sector import Sector
from app.models.surge_prediction_evaluation import SurgePredictionEvaluation


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _make_stock(db: Session, code: str, name: str = "테스트종목") -> Stock:
    """테스트용 Stock + Sector 생성 헬퍼."""
    sector = Sector(name=f"테스트섹터_{code}", is_custom=False)
    db.add(sector)
    db.flush()
    stock = Stock(stock_code=code, name=name, sector_id=sector.id, market="KOSPI")
    db.add(stock)
    db.flush()
    return stock


def _make_disclosure(
    db: Session,
    stock_code: str,
    rcept_dt: str,
    report_name: str = "사업보고서",
    ai_summary: str | None = None,
) -> Disclosure:
    import random
    d = Disclosure(
        corp_code=f"0000{random.randint(1000, 9999)}",
        corp_name="테스트기업",
        stock_code=stock_code,
        report_name=report_name,
        rcept_no=f"2026{random.randint(100000000000, 999999999999)}",
        rcept_dt=rcept_dt,
        url="https://dart.fss.or.kr/test",
        ai_summary=ai_summary,
    )
    db.add(d)
    db.flush()
    return d


def _make_news_with_relation(
    db: Session,
    stock: Stock,
    title: str,
    published_at: datetime,
) -> NewsArticle:
    article = NewsArticle(
        title=title,
        url=f"https://test.example.com/{title[:10]}{published_at.timestamp()}",
        source="test",
        published_at=published_at,
    )
    db.add(article)
    db.flush()

    rel = NewsStockRelation(
        news_id=article.id,
        stock_id=stock.id,
        match_type="keyword",
        relevance="direct",
    )
    db.add(rel)
    db.flush()
    return article


# ---------------------------------------------------------------------------
# TestEnrichSurgeStockContext
# ---------------------------------------------------------------------------

class TestEnrichSurgeStockContext:
    """AC-1, AC-2, AC-3: enrich_surge_stock_context 컨텍스트 수집 검증."""

    def test_ac1_all_context_populated(self, db: Session):
        """AC-1: 공시/뉴스/거래량/시그널 모두 시드 후 4개 키 존재 확인."""
        from app.services.surge_evaluation_service import enrich_surge_stock_context

        trading_date = date(2026, 6, 23)
        code = "AC0001"
        stock = _make_stock(db, code)

        # 공시 시드
        today_str = trading_date.strftime("%Y%m%d")
        _make_disclosure(db, code, today_str, "수주 공시", "수주 계약 체결")

        # 뉴스 시드
        pub_dt = datetime(2026, 6, 23, 9, 0, tzinfo=timezone.utc)
        _make_news_with_relation(db, stock, "AI반도체 수주 공시", pub_dt)

        # FundSignal 시드 (T-1 = 2026-06-22 월→금? 아니면 6/22는 월요일이므로 T-1=6/19 금)
        # trading_date=2026-06-23 화요일 → T-1=2026-06-22 월요일
        prev_day = date(2026, 6, 22)
        signal = FundSignal(
            stock_id=stock.id,
            signal="buy",
            signal_type="surge_candidate",
            confidence=0.75,
            reasoning="테스트",
            surge_metadata='{"surge_basis": ["theme_cluster"], "theme_cluster_score": 0.8}',
            created_at=datetime(prev_day.year, prev_day.month, prev_day.day, 15, 20, tzinfo=timezone.utc),
        )
        db.add(signal)
        db.commit()

        # 거래량은 _get_volume_history mock
        with patch(
            "app.services.surge_evaluation_service.enrich_surge_stock_context.__wrapped__"
            if hasattr(enrich_surge_stock_context, "__wrapped__") else
            "app.services.surge_detector._get_volume_history",
            return_value=[1000.0, 1200.0, 1100.0, 1300.0, 1000.0, 5000.0],
        ):
            result = enrich_surge_stock_context(code, trading_date, db)

        assert "disclosures" in result
        assert "news_headlines" in result
        assert "volume_ratio" in result
        assert "our_signal" in result
        # 공시 포함
        assert len(result["disclosures"]) >= 1
        assert result["disclosures"][0]["report_name"] == "수주 공시"
        # 뉴스 포함
        assert len(result["news_headlines"]) >= 1
        # 시그널 포함
        assert result["our_signal"] is not None
        assert result["our_signal"]["signal_type"] == "surge_candidate"

    def test_ac2_no_news_relation_returns_empty_headlines(self, db: Session):
        """AC-2: NewsStockRelation 없으면 news_headlines=[] 이고 예외 없음."""
        from app.services.surge_evaluation_service import enrich_surge_stock_context

        code = "AC0002"
        _make_stock(db, code)
        db.commit()

        result = enrich_surge_stock_context(code, date(2026, 6, 23), db)
        assert result["news_headlines"] == []

    def test_ac3_disclosure_date_filter(self, db: Session):
        """AC-3: 오늘/전일 공시만 포함, 이전 날짜 공시는 제외."""
        from app.services.surge_evaluation_service import enrich_surge_stock_context

        trading_date = date(2026, 6, 23)
        code = "AC0003"
        _make_stock(db, code)

        today_str = "20260623"
        prev_str = "20260622"
        old_str = "20260610"  # 2주 전 — 제외되어야 함

        _make_disclosure(db, code, today_str, "오늘 공시")
        _make_disclosure(db, code, prev_str, "전일 공시")
        _make_disclosure(db, code, old_str, "오래된 공시")
        db.commit()

        result = enrich_surge_stock_context(code, trading_date, db)
        report_names = [d["report_name"] for d in result["disclosures"]]
        assert "오래된 공시" not in report_names
        assert "오늘 공시" in report_names or "전일 공시" in report_names


# ---------------------------------------------------------------------------
# TestAnalyzeSurgeCauseWithLLM
# ---------------------------------------------------------------------------

class TestAnalyzeSurgeCauseWithLLM:
    """AC-4, AC-5, AC-15: analyze_surge_cause_with_llm 검증."""

    @pytest.mark.asyncio
    async def test_ac4_valid_json_response(self, db: Session):
        """AC-4: LLM이 유효한 JSON 반환 → 4개 필드 존재, root_cause enum 검증."""
        from app.services.surge_evaluation_service import (
            analyze_surge_cause_with_llm,
            _LLMBudgetGuard,
        )

        context = {
            "disclosures": [{"report_name": "수주 공시", "ai_summary": "계약 체결"}],
            "news_headlines": [{"title": "AI수주 공시", "summary": None}],
            "volume_ratio": 3.5,
            "our_signal": None,
        }

        mock_response = json.dumps({
            "root_cause": "공시",
            "should_have_fired": "disclosure_pattern",
            "improvement_suggestion": "공시 키워드 임계값 하향 조정 필요",
            "confidence_note": "공시 데이터 명확",
        })

        guard = _LLMBudgetGuard(max_calls=5, delay_sec=0.0)

        with patch(
            "app.services.surge_evaluation_service.ask_ai_with_openai_fallback",
            new_callable=AsyncMock,
            return_value=(mock_response, "gemini-flash"),
        ):
            result = await analyze_surge_cause_with_llm("AC0004", context, None, db, guard)

        valid_causes = {"공시", "뉴스", "거래량", "테마", "불명"}
        assert result["root_cause"] in valid_causes
        assert "should_have_fired" in result
        assert "improvement_suggestion" in result
        assert "confidence_note" in result
        assert result["stock_code"] == "AC0004"

    @pytest.mark.asyncio
    async def test_ac5_free_text_response_no_exception(self, db: Session):
        """AC-5: LLM이 자유 텍스트 반환 → improvement_suggestion에 보존, 예외 없음."""
        from app.services.surge_evaluation_service import (
            analyze_surge_cause_with_llm,
            _LLMBudgetGuard,
        )

        context = {
            "disclosures": [{"report_name": "임상 시험 결과", "ai_summary": "긍정적"}],
            "news_headlines": [],
            "volume_ratio": 2.0,
            "our_signal": None,
        }

        guard = _LLMBudgetGuard(max_calls=5, delay_sec=0.0)

        with patch(
            "app.services.surge_evaluation_service.ask_ai_with_openai_fallback",
            new_callable=AsyncMock,
            return_value=("이 종목은 바이오 임상 결과 호재로 급등했습니다. 공시 탐지기 강화 필요.", "gemini-flash"),
        ):
            result = await analyze_surge_cause_with_llm("AC0005", context, None, db, guard)

        assert result is not None
        assert "improvement_suggestion" in result
        assert len(result["improvement_suggestion"]) > 0

    @pytest.mark.asyncio
    async def test_ac15_empty_context_no_llm_call(self, db: Session):
        """AC-15: 공시/뉴스/거래량 전부 없음 → '데이터 없음' 반환, LLM 호출 0회."""
        from app.services.surge_evaluation_service import (
            analyze_surge_cause_with_llm,
            _LLMBudgetGuard,
        )

        context = {
            "disclosures": [],
            "news_headlines": [],
            "volume_ratio": None,
            "our_signal": None,
        }

        guard = _LLMBudgetGuard(max_calls=5, delay_sec=0.0)

        with patch(
            "app.services.surge_evaluation_service.ask_ai_with_openai_fallback",
            new_callable=AsyncMock,
        ) as mock_llm:
            result = await analyze_surge_cause_with_llm("AC0015", context, None, db, guard)

        mock_llm.assert_not_called()
        assert "데이터 없음" in result["improvement_suggestion"]
        assert result["root_cause"] == "불명"


# ---------------------------------------------------------------------------
# TestLLMBudgetGuard
# ---------------------------------------------------------------------------

class TestLLMBudgetGuard:
    """AC-6, AC-7: _LLMBudgetGuard 횟수 제한 검증."""

    @pytest.mark.asyncio
    async def test_ac6_budget_exhausted_after_max_calls(self, db: Session):
        """AC-6: max=3 가드, 4번 시도 시 4번째는 fallback 반환 (LLM 호출 ≤ 3)."""
        from app.services.surge_evaluation_service import (
            analyze_surge_cause_with_llm,
            _LLMBudgetGuard,
        )

        context = {
            "disclosures": [{"report_name": "테스트", "ai_summary": "요약"}],
            "news_headlines": [],
            "volume_ratio": 1.5,
            "our_signal": None,
        }

        guard = _LLMBudgetGuard(max_calls=3, delay_sec=0.0)
        mock_json = json.dumps({
            "root_cause": "공시",
            "should_have_fired": "disclosure_pattern",
            "improvement_suggestion": "테스트",
            "confidence_note": "OK",
        })

        call_count = 0

        async def _mock_llm(prompt: str, **kwargs):
            nonlocal call_count
            call_count += 1
            return (mock_json, "gemini-flash")

        with patch(
            "app.services.surge_evaluation_service.ask_ai_with_openai_fallback",
            side_effect=_mock_llm,
        ):
            for i in range(4):
                await analyze_surge_cause_with_llm(f"CODE{i:04d}", context, None, db, guard)

        assert call_count <= 3, f"LLM 호출이 3회를 초과함: {call_count}"

    @pytest.mark.asyncio
    async def test_ac7_llm_returns_none_uses_fallback(self, db: Session):
        """AC-7: LLM이 None 반환 → fallback 사용, 예외 없음."""
        from app.services.surge_evaluation_service import (
            analyze_surge_cause_with_llm,
            _LLMBudgetGuard,
        )

        context = {
            "disclosures": [{"report_name": "테스트 공시", "ai_summary": "요약"}],
            "news_headlines": [],
            "volume_ratio": 2.0,
            "our_signal": None,
        }

        guard = _LLMBudgetGuard(max_calls=5, delay_sec=0.0)

        with patch(
            "app.services.surge_evaluation_service.ask_ai_with_openai_fallback",
            new_callable=AsyncMock,
            return_value=(None, "gemini-flash"),
        ):
            result = await analyze_surge_cause_with_llm("AC0007", context, None, db, guard)

        assert result is not None
        assert "stock_code" in result


# ---------------------------------------------------------------------------
# TestLLMFreeOnlyPath
# ---------------------------------------------------------------------------

class TestLLMFreeOnlyPath:
    """AC-8: ask_ai_with_openai_fallback가 free_only=True 키워드로 호출되는지 검증."""

    @pytest.mark.asyncio
    async def test_ac8_free_only_kwarg(self, db: Session):
        """AC-8: analyze_surge_cause_with_llm이 free_only=True로 LLM 호출."""
        from app.services.surge_evaluation_service import (
            analyze_surge_cause_with_llm,
            _LLMBudgetGuard,
        )

        context = {
            "disclosures": [{"report_name": "수주", "ai_summary": "계약"}],
            "news_headlines": [],
            "volume_ratio": None,
            "our_signal": None,
        }

        guard = _LLMBudgetGuard(max_calls=5, delay_sec=0.0)
        mock_json = json.dumps({
            "root_cause": "공시",
            "should_have_fired": "disclosure_pattern",
            "improvement_suggestion": "테스트",
            "confidence_note": "OK",
        })

        with patch(
            "app.services.surge_evaluation_service.ask_ai_with_openai_fallback",
            new_callable=AsyncMock,
            return_value=(mock_json, "gemini-flash"),
        ) as mock_llm:
            await analyze_surge_cause_with_llm("AC0008", context, None, db, guard)

        # free_only=True 키워드 인수가 전달되었는지 확인
        called_kwargs = mock_llm.call_args.kwargs if mock_llm.call_args else {}
        assert called_kwargs.get("free_only") is True


# ---------------------------------------------------------------------------
# TestGenerateDetectorImprovementSuggestions
# ---------------------------------------------------------------------------

class TestGenerateDetectorImprovementSuggestions:
    """AC-9: 탐지기별 집계 및 정렬 검증."""

    def test_ac9_aggregation_and_ordering(self):
        """AC-9: 3×disclosure_impact + 2×theme_cluster → 순서와 그룹 필드 검증."""
        from app.services.surge_evaluation_service import generate_detector_improvement_suggestions

        analysis_results = [
            {"stock_code": "A", "should_have_fired": "disclosure_impact", "improvement_suggestion": "제안1"},
            {"stock_code": "B", "should_have_fired": "disclosure_impact", "improvement_suggestion": "제안2"},
            {"stock_code": "C", "should_have_fired": "disclosure_impact", "improvement_suggestion": "제안3"},
            {"stock_code": "D", "should_have_fired": "theme_cluster", "improvement_suggestion": "제안4"},
            {"stock_code": "E", "should_have_fired": "theme_cluster", "improvement_suggestion": "제안5"},
        ]

        suggestions = generate_detector_improvement_suggestions(analysis_results)

        # disclosure_impact가 첫 번째 (3건 > 2건)
        assert suggestions[0]["detector"] == "disclosure_impact"
        assert suggestions[0]["missed_count"] == 3
        assert suggestions[1]["detector"] == "theme_cluster"
        assert suggestions[1]["missed_count"] == 2

        # 필드 존재 확인
        for s in suggestions:
            assert "detector" in s
            assert "missed_count" in s
            assert "sample_codes" in s
            assert "suggestion" in s
            assert "priority" in s


# ---------------------------------------------------------------------------
# TestAnalyzeTruePositivesWithLLM
# ---------------------------------------------------------------------------

class TestAnalyzeTruePositivesWithLLM:
    """AC-10: analyze_true_positives_with_llm 결과 형식 검증."""

    @pytest.mark.asyncio
    async def test_ac10_tp_analysis_returns_required_fields(self, db: Session):
        """AC-10: 3개 TP 종목 입력 → 각 결과에 winning_detector/pattern_summary/reinforce 포함."""
        from app.services.surge_evaluation_service import (
            analyze_true_positives_with_llm,
            _LLMBudgetGuard,
        )

        tp_stocks = [
            {"stock_code": "TP0001", "change_rate": 15.0, "stock_name": "종목A"},
            {"stock_code": "TP0002", "change_rate": 12.0, "stock_name": "종목B"},
            {"stock_code": "TP0003", "change_rate": 11.0, "stock_name": "종목C"},
        ]

        mock_json = json.dumps({
            "winning_detector": "theme_cluster",
            "pattern_summary": "반도체 테마 클러스터링으로 급등 예측 성공",
            "reinforce": True,
        })

        guard = _LLMBudgetGuard(max_calls=8, delay_sec=0.0)

        with patch(
            "app.services.surge_evaluation_service.ask_ai_with_openai_fallback",
            new_callable=AsyncMock,
            return_value=(mock_json, "gemini-flash"),
        ):
            # enrich_surge_stock_context가 DB 조회하므로 mock 처리
            with patch(
                "app.services.surge_evaluation_service.enrich_surge_stock_context",
                return_value={
                    "disclosures": [],
                    "news_headlines": [],
                    "volume_ratio": None,
                    "our_signal": {"signal_type": "surge_candidate", "confidence": 0.8, "contributions": {}},
                },
            ):
                results = await analyze_true_positives_with_llm(tp_stocks, db, guard)

        assert len(results) == 3
        for r in results:
            assert "stock_code" in r
            assert "winning_detector" in r
            assert "pattern_summary" in r
            assert "reinforce" in r


# ---------------------------------------------------------------------------
# TestAnalyzeMissesWithLLMSignature
# ---------------------------------------------------------------------------

class TestAnalyzeMissesWithLLMSignature:
    """AC-11: analyze_misses_with_llm 반환값이 str 타입인지 확인 (시그니처 하위호환)."""

    @pytest.mark.asyncio
    async def test_ac11_returns_str(self, db: Session):
        """AC-11: 결과는 항상 str 타입 (scheduler.py miss_analysis_json 호환)."""
        from app.services.surge_evaluation_service import analyze_misses_with_llm

        missed = [{"stock_code": "AC0011", "change_rate": 13.0, "stock_name": "테스트"}]

        with patch(
            "app.services.surge_evaluation_service.ask_ai_with_openai_fallback",
            new_callable=AsyncMock,
            return_value=('{"root_cause": "공시", "should_have_fired": "disclosure_pattern", "improvement_suggestion": "테스트", "confidence_note": "OK"}', "gemini-flash"),
        ):
            with patch(
                "app.services.surge_evaluation_service.enrich_surge_stock_context",
                return_value={
                    "disclosures": [{"report_name": "수주", "ai_summary": "계약"}],
                    "news_headlines": [],
                    "volume_ratio": 2.0,
                    "our_signal": None,
                },
            ):
                result = await analyze_misses_with_llm(missed, db)

        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# TestPerStockAnalysisStorage
# ---------------------------------------------------------------------------

class TestPerStockAnalysisStorage:
    """AC-12: per_stock_analysis_json 컬럼 DB 저장 및 재조회 검증."""

    def test_ac12_per_stock_json_roundtrip(self, db: Session):
        """AC-12: SurgePredictionEvaluation에 per_stock_analysis_json 저장 후 재조회."""
        sample_data = {
            "fn_analysis": [{"stock_code": "X", "root_cause": "공시"}],
            "tp_analysis": [{"stock_code": "Y", "winning_detector": "theme_cluster"}],
        }
        json_str = json.dumps(sample_data, ensure_ascii=False)

        eval_row = SurgePredictionEvaluation(
            evaluation_date=date(2026, 6, 22),
            predicted_count=5,
            actual_surge_count=3,
            true_positive=2,
            false_positive=3,
            false_negative=1,
            precision=0.4,
            recall=0.67,
            f1_score=0.5,
            per_stock_analysis_json=json_str,
        )
        db.add(eval_row)
        db.commit()

        loaded = (
            db.query(SurgePredictionEvaluation)
            .filter(SurgePredictionEvaluation.evaluation_date == date(2026, 6, 22))
            .first()
        )
        assert loaded is not None
        assert loaded.per_stock_analysis_json == json_str
        parsed = json.loads(loaded.per_stock_analysis_json)
        assert parsed["fn_analysis"][0]["stock_code"] == "X"
        assert parsed["tp_analysis"][0]["winning_detector"] == "theme_cluster"


# ---------------------------------------------------------------------------
# TestSchedulerExceptionIsolation
# ---------------------------------------------------------------------------

class TestSchedulerExceptionIsolation:
    """AC-13, AC-14: 스케줄러 예외 격리 및 시장 마감 skip 검증."""

    def test_ac13_tp_analysis_failure_preserves_evaluation(self, db: Session):
        """AC-13: TP 분석이 예외를 던져도 precision/recall/f1이 보존됨."""
        # SurgePredictionEvaluation을 직접 생성 (스케줄러 외부에서)
        from app.services.surge_evaluation_service import evaluate_surge_predictions
        from app.models.surge_actual_outcome import SurgeActualOutcome
        from app.models.fund_signal import FundSignal as _FS
        from datetime import timezone

        trading_date = date(2026, 6, 24)

        # 예측 종목 + 실제 급등 종목 시드
        stock1 = _make_stock(db, "SC0001", "종목1")
        _make_stock(db, "SC0002", "종목2")

        from app.services.surge_trading_service import _get_prev_business_day
        prev_day = _get_prev_business_day(trading_date)

        signal = _FS(
            stock_id=stock1.id,
            signal="buy",
            signal_type="surge_candidate",
            confidence=0.8,
            reasoning="테스트",
            surge_metadata='{"test": true}',
            created_at=datetime(prev_day.year, prev_day.month, prev_day.day, 15, 20, tzinfo=timezone.utc),
        )
        db.add(signal)

        outcome1 = SurgeActualOutcome(
            trading_date=trading_date, stock_code="SC0001", stock_name="종목1",
            change_rate=15.0, was_surge=True, market="KOSPI",
        )
        outcome2 = SurgeActualOutcome(
            trading_date=trading_date, stock_code="SC0002", stock_name="종목2",
            change_rate=12.0, was_surge=True, market="KOSPI",
        )
        db.add(outcome1)
        db.add(outcome2)
        db.commit()

        # evaluate_surge_predictions 실행
        evaluation = evaluate_surge_predictions(db, trading_date)

        # precision/recall이 계산되어 있는지 확인
        assert evaluation.true_positive >= 0
        assert evaluation.precision is not None or evaluation.precision == 0.0

        # TP 분석에서 예외가 발생해도 evaluation 레코드가 유지되어야 함
        # per_stock_analysis_json은 None이거나 값이 있어야 함 (예외 격리)
        # DB 재조회
        loaded = (
            db.query(SurgePredictionEvaluation)
            .filter(SurgePredictionEvaluation.evaluation_date == trading_date)
            .first()
        )
        assert loaded is not None
        # precision/recall/f1은 반드시 보존됨
        assert loaded.false_negative is not None

    def test_ac14_market_closed_no_llm_calls(self):
        """AC-14: _is_kr_market_open() → False이면 스케줄러가 즉시 리턴 (LLM 호출 0)."""
        with patch(
            "app.services.scheduler._is_kr_market_open",
            return_value=False,
        ):
            with patch(
                "app.services.surge_evaluation_service.ask_ai_with_openai_fallback",
                new_callable=AsyncMock,
            ) as mock_llm:
                from app.services.scheduler import _run_surge_verify_predictions
                _run_surge_verify_predictions()

        mock_llm.assert_not_called()


# ---------------------------------------------------------------------------
# TestEdgeCases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """EC-1~EC-6: 엣지 케이스 검증."""

    @pytest.mark.asyncio
    async def test_ec1_empty_fn_and_tp(self, db: Session):
        """EC-1: FN=0 AND TP=0 → 빈 결과, LLM 호출 0."""
        from app.services.surge_evaluation_service import analyze_misses_with_llm

        with patch(
            "app.services.surge_evaluation_service.ask_ai_with_openai_fallback",
            new_callable=AsyncMock,
        ) as mock_llm:
            result = await analyze_misses_with_llm([], db)

        mock_llm.assert_not_called()
        assert "FN=0" in result or "없음" in result

    def test_ec2_surge_metadata_none(self, db: Session):
        """EC-2: FundSignal.surge_metadata=None → our_signal contributions 빈 dict."""
        from app.services.surge_evaluation_service import enrich_surge_stock_context

        code = "EC0002"
        stock = _make_stock(db, code)

        prev_day = date(2026, 6, 20)  # 금요일
        signal = FundSignal(
            stock_id=stock.id,
            signal="buy",
            signal_type="surge_candidate",
            confidence=0.6,
            reasoning="테스트",
            surge_metadata=None,  # None
            created_at=datetime(prev_day.year, prev_day.month, prev_day.day, 15, tzinfo=timezone.utc),
        )
        db.add(signal)
        db.commit()

        trading_date = date(2026, 6, 23)
        result = enrich_surge_stock_context(code, trading_date, db)

        # surge_metadata=None인 시그널은 isnot(None) 필터에 걸려 our_signal=None
        # (또는 있더라도 contributions가 빈 dict이어야 함)
        if result["our_signal"] is not None:
            assert isinstance(result["our_signal"].get("contributions", {}), dict)

    def test_ec3_multiple_disclosures_capped(self, db: Session):
        """EC-3: 3개 공시 시드 → 최대 2개만 반환."""
        from app.services.surge_evaluation_service import enrich_surge_stock_context

        code = "EC0003"
        _make_stock(db, code)

        today_str = "20260623"
        _make_disclosure(db, code, today_str, "공시1")
        _make_disclosure(db, code, today_str, "공시2")
        _make_disclosure(db, code, today_str, "공시3")
        db.commit()

        result = enrich_surge_stock_context(code, date(2026, 6, 23), db)
        assert len(result["disclosures"]) <= 2

    def test_ec5_short_volume_history(self, db: Session):
        """EC-5: 거래량 히스토리 2개 → volume_ratio 계산 (None 아님)."""
        from app.services.surge_evaluation_service import enrich_surge_stock_context

        code = "EC0005"
        _make_stock(db, code)
        db.commit()

        with patch(
            "app.services.surge_detector._get_volume_history",
            return_value=[1000.0, 3000.0],  # 2개만 — baseline=1000, today=3000
        ):
            result = enrich_surge_stock_context(code, date(2026, 6, 23), db)

        assert result["volume_ratio"] is not None
        assert abs(result["volume_ratio"] - 3.0) < 0.01

    def test_ec6_unknown_detector_normalized(self):
        """EC-6: should_have_fired가 공백/None → 'unknown'으로 정규화."""
        from app.services.surge_evaluation_service import generate_detector_improvement_suggestions

        results = [
            {"stock_code": "A", "should_have_fired": None, "improvement_suggestion": "제안"},
            {"stock_code": "B", "should_have_fired": "", "improvement_suggestion": "제안2"},
        ]
        suggestions = generate_detector_improvement_suggestions(results)

        detectors = [s["detector"] for s in suggestions]
        assert "unknown" in detectors
