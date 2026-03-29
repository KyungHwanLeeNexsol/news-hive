"""fund_manager 서비스 테스트.

외부 API(AI, KIS, Naver) 호출이 없는 순수 함수 및 DB 쿼리 함수를 검증한다.
- _parse_json_response: JSON 파싱 유틸
- _gather_sentiment_trend: 센티먼트 추이 분석
- _gather_macro_alerts: 매크로 리스크 조회
- _gather_stock_news: 종목 뉴스 수집
- _gather_disclosures: 공시 수집
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.services.fund_manager import (
    _parse_json_response,
    _gather_sentiment_trend,
    _gather_macro_alerts,
    _gather_stock_news,
    _gather_sector_news,
    _gather_disclosures,
    _format_briefing_hint,
    validate_cot_steps,
    apply_cot_penalty,
    COT_REQUIRED_STEPS,
)


# SQLite는 timezone-naive datetime을 사용하므로 fund_manager 내부의
# datetime.now(timezone.utc) 호출을 naive UTC로 패치해야 한다.
def _naive_utcnow():
    """SQLite 호환용 naive UTC datetime."""
    return datetime.utcnow()


def _patch_fm_datetime():
    """fund_manager 모듈의 datetime.now를 naive UTC로 패치."""
    return patch(
        "app.services.fund_manager.datetime",
        wraps=datetime,
        **{"now.return_value": _naive_utcnow()},
    )


class TestParseJsonResponse:
    """_parse_json_response JSON 파싱 유틸 검증."""

    def test_valid_json(self) -> None:
        """일반 JSON 문자열을 파싱한다."""
        result = _parse_json_response('{"signal": "buy", "confidence": 0.8}')
        assert result == {"signal": "buy", "confidence": 0.8}

    def test_json_with_markdown_code_block(self) -> None:
        """마크다운 코드블록으로 감싸진 JSON을 파싱한다."""
        text = '```json\n{"signal": "hold"}\n```'
        result = _parse_json_response(text)
        assert result == {"signal": "hold"}

    def test_json_with_bare_code_block(self) -> None:
        """언어 태그 없는 코드블록의 JSON을 파싱한다."""
        text = '```\n{"signal": "sell"}\n```'
        result = _parse_json_response(text)
        assert result == {"signal": "sell"}

    def test_json_embedded_in_text(self) -> None:
        """텍스트 중간에 포함된 JSON 객체를 추출한다."""
        text = 'Here is the analysis:\n{"signal": "buy", "confidence": 0.9}\nEnd.'
        result = _parse_json_response(text)
        assert result is not None
        assert result["signal"] == "buy"

    def test_empty_string_returns_none(self) -> None:
        """빈 문자열이면 None을 반환한다."""
        assert _parse_json_response("") is None

    def test_none_input_returns_none(self) -> None:
        """None 입력이면 None을 반환한다."""
        assert _parse_json_response(None) is None

    def test_invalid_json_returns_none(self) -> None:
        """파싱 불가능한 문자열이면 None을 반환한다."""
        assert _parse_json_response("not json at all") is None

    def test_nested_json(self) -> None:
        """중첩 구조 JSON을 올바르게 파싱한다."""
        text = '{"picks": [{"stock": "삼성전자", "action": "매수"}]}'
        result = _parse_json_response(text)
        assert result is not None
        assert len(result["picks"]) == 1
        assert result["picks"][0]["stock"] == "삼성전자"

    def test_json_with_korean_text(self) -> None:
        """한글이 포함된 JSON을 파싱한다."""
        text = '{"reasoning": "삼성전자의 실적이 양호합니다", "signal": "buy"}'
        result = _parse_json_response(text)
        assert result is not None
        assert "삼성전자" in result["reasoning"]


class TestGatherSentimentTrend:
    """_gather_sentiment_trend 센티먼트 추이 분석 검증.

    SQLite에서는 timezone-naive datetime을 사용하므로
    fund_manager 내부의 datetime.now(timezone.utc)를 패치한다.
    """

    def test_no_articles_returns_zero_counts(self, db: Session) -> None:
        """뉴스가 없으면 모든 카운트가 0이고 추세는 stable이다."""
        now = datetime.utcnow()
        with patch("app.services.fund_manager.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = _gather_sentiment_trend(db)

        assert result["recent_3d"] == {"positive": 0, "negative": 0, "neutral": 0}
        assert result["prev_4d"] == {"positive": 0, "negative": 0, "neutral": 0}
        assert result["trend"] == "stable"
        assert result["score_3d"] == 0.0

    def test_recent_positive_articles(
        self, db: Session, make_news,
    ) -> None:
        """최근 3일에 긍정 뉴스가 많으면 score_3d가 양수이다."""
        now = datetime.utcnow()
        # 최근 12시간: 긍정 3건
        for _ in range(3):
            make_news(
                sentiment="positive",
                published_at=now - timedelta(hours=12),
                collected_at=now - timedelta(hours=12),
            )
        # 최근 6시간: 부정 1건
        make_news(
            sentiment="negative",
            published_at=now - timedelta(hours=6),
            collected_at=now - timedelta(hours=6),
        )

        with patch("app.services.fund_manager.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = _gather_sentiment_trend(db)

        assert result["recent_3d"]["positive"] == 3
        assert result["recent_3d"]["negative"] == 1
        # score = (3 - 1) / 4 * 100 = 50.0
        assert result["score_3d"] == 50.0

    def test_trend_improving(
        self, db: Session, make_news,
    ) -> None:
        """최근 3일 점수가 이전 4일보다 10점 이상 높으면 improving."""
        now = datetime.utcnow()
        # 이전 4일: 부정 뉴스만
        for _ in range(3):
            make_news(
                sentiment="negative",
                published_at=now - timedelta(days=5),
                collected_at=now - timedelta(days=5),
            )
        # 최근 3일: 긍정 뉴스만
        for _ in range(3):
            make_news(
                sentiment="positive",
                published_at=now - timedelta(hours=12),
                collected_at=now - timedelta(hours=12),
            )

        with patch("app.services.fund_manager.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = _gather_sentiment_trend(db)

        assert result["trend"] == "improving"

    def test_trend_worsening(
        self, db: Session, make_news,
    ) -> None:
        """최근 3일 점수가 이전 4일보다 10점 이상 낮으면 worsening."""
        now = datetime.utcnow()
        # 이전 4일: 긍정 뉴스만
        for _ in range(3):
            make_news(
                sentiment="positive",
                published_at=now - timedelta(days=5),
                collected_at=now - timedelta(days=5),
            )
        # 최근 3일: 부정 뉴스만
        for _ in range(3):
            make_news(
                sentiment="negative",
                published_at=now - timedelta(hours=12),
                collected_at=now - timedelta(hours=12),
            )

        with patch("app.services.fund_manager.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = _gather_sentiment_trend(db)

        assert result["trend"] == "worsening"

    def test_filter_by_stock_id(
        self, db: Session, make_stock, make_news, make_news_relation,
    ) -> None:
        """stock_id로 필터링하면 해당 종목 관련 뉴스만 집계한다."""
        now = datetime.utcnow()
        stock = make_stock()
        other_stock = make_stock()

        # stock에 연결된 긍정 뉴스
        news1 = make_news(
            sentiment="positive",
            published_at=now - timedelta(hours=6),
            collected_at=now - timedelta(hours=6),
        )
        make_news_relation(news_id=news1.id, stock_id=stock.id)

        # 다른 종목에 연결된 부정 뉴스
        news2 = make_news(
            sentiment="negative",
            published_at=now - timedelta(hours=6),
            collected_at=now - timedelta(hours=6),
        )
        make_news_relation(news_id=news2.id, stock_id=other_stock.id)

        with patch("app.services.fund_manager.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = _gather_sentiment_trend(db, stock_id=stock.id)

        assert result["recent_3d"]["positive"] == 1
        assert result["recent_3d"]["negative"] == 0

    def test_filter_by_sector_id(
        self, db: Session, make_sector, make_news, make_news_relation,
    ) -> None:
        """sector_id로 필터링하면 해당 섹터 관련 뉴스만 집계한다."""
        now = datetime.utcnow()
        sector = make_sector(name="반도체")

        news1 = make_news(
            sentiment="negative",
            published_at=now - timedelta(hours=6),
            collected_at=now - timedelta(hours=6),
        )
        make_news_relation(news_id=news1.id, sector_id=sector.id)

        # 관계없는 뉴스
        make_news(
            sentiment="positive",
            published_at=now - timedelta(hours=6),
            collected_at=now - timedelta(hours=6),
        )

        with patch("app.services.fund_manager.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = _gather_sentiment_trend(db, sector_id=sector.id)

        assert result["recent_3d"]["negative"] == 1
        assert result["recent_3d"]["positive"] == 0


class TestGatherMacroAlerts:
    """_gather_macro_alerts 매크로 리스크 조회 검증."""

    def test_no_alerts(self, db: Session) -> None:
        """활성 알림이 없으면 빈 리스트를 반환한다."""
        result = _gather_macro_alerts(db)
        assert result == []

    def test_active_alerts_returned(
        self, db: Session, make_macro_alert,
    ) -> None:
        """활성 알림만 조회된다."""
        make_macro_alert(level="warning", keyword="금리인상")
        make_macro_alert(level="critical", keyword="전쟁", is_active=False)

        result = _gather_macro_alerts(db)

        assert len(result) == 1
        assert result[0]["keyword"] == "금리인상"
        assert result[0]["level"] == "warning"

    def test_alert_fields(
        self, db: Session, make_macro_alert,
    ) -> None:
        """알림의 모든 필수 필드가 포함된다."""
        make_macro_alert(
            level="critical",
            keyword="환율급등",
            title="원달러 환율 급등",
            article_count=15,
        )

        result = _gather_macro_alerts(db)

        assert len(result) == 1
        alert = result[0]
        assert alert["level"] == "critical"
        assert alert["keyword"] == "환율급등"
        assert alert["title"] == "원달러 환율 급등"
        assert alert["article_count"] == 15


class TestGatherStockNews:
    """_gather_stock_news 종목 뉴스 수집 검증."""

    def test_no_news(self, db: Session, make_stock) -> None:
        """관련 뉴스가 없으면 빈 리스트를 반환한다."""
        stock = make_stock()
        now = datetime.utcnow()
        with patch("app.services.fund_manager.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = _gather_stock_news(db, stock.id)
        assert result == []

    def test_returns_related_news(
        self, db: Session, make_stock, make_news, make_news_relation,
    ) -> None:
        """종목에 연결된 뉴스만 조회한다."""
        now = datetime.utcnow()
        stock = make_stock()
        news = make_news(
            title="삼성전자 실적 호조",
            sentiment="positive",
            published_at=now - timedelta(hours=6),
            collected_at=now - timedelta(hours=6),
        )
        make_news_relation(news_id=news.id, stock_id=stock.id)

        with patch("app.services.fund_manager.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = _gather_stock_news(db, stock.id)

        assert len(result) == 1
        assert result[0]["title"] == "삼성전자 실적 호조"
        assert result[0]["sentiment"] == "positive"

    def test_respects_days_filter(
        self, db: Session, make_stock, make_news, make_news_relation,
    ) -> None:
        """days 파라미터 내의 뉴스만 조회한다."""
        now = datetime.utcnow()
        stock = make_stock()

        # 최근 뉴스
        recent = make_news(
            title="최근 뉴스",
            collected_at=now - timedelta(hours=6),
            published_at=now - timedelta(hours=6),
        )
        make_news_relation(news_id=recent.id, stock_id=stock.id)

        # 오래된 뉴스 (10일 전)
        old = make_news(
            title="오래된 뉴스",
            collected_at=now - timedelta(days=10),
            published_at=now - timedelta(days=10),
        )
        make_news_relation(news_id=old.id, stock_id=stock.id)

        with patch("app.services.fund_manager.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = _gather_stock_news(db, stock.id, days=3)

        assert len(result) == 1
        assert result[0]["title"] == "최근 뉴스"

    def test_includes_content_snippet(
        self, db: Session, make_stock, make_news, make_news_relation,
    ) -> None:
        """본문이 있으면 200자 스니펫이 포함된다."""
        now = datetime.utcnow()
        stock = make_stock()
        long_content = "가" * 500
        news = make_news(
            content=long_content,
            collected_at=now - timedelta(hours=1),
            published_at=now - timedelta(hours=1),
        )
        make_news_relation(news_id=news.id, stock_id=stock.id)

        with patch("app.services.fund_manager.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = _gather_stock_news(db, stock.id)

        assert len(result) == 1
        assert "content" in result[0]
        assert len(result[0]["content"]) == 200

    def test_limit_10_articles(
        self, db: Session, make_stock, make_news, make_news_relation,
    ) -> None:
        """최대 10건만 반환한다."""
        now = datetime.utcnow()
        stock = make_stock()

        for i in range(15):
            news = make_news(
                title=f"뉴스 {i}",
                collected_at=now - timedelta(hours=i),
                published_at=now - timedelta(hours=i),
            )
            make_news_relation(news_id=news.id, stock_id=stock.id)

        with patch("app.services.fund_manager.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = _gather_stock_news(db, stock.id)

        assert len(result) == 10


class TestGatherSectorNews:
    """_gather_sector_news 섹터 뉴스 수집 검증."""

    def test_returns_sector_related_news(
        self, db: Session, make_sector, make_news, make_news_relation,
    ) -> None:
        """섹터에 연결된 뉴스만 조회한다."""
        now = datetime.utcnow()
        sector = make_sector(name="반도체")
        news = make_news(
            title="반도체 업황 호조",
            sentiment="positive",
            collected_at=now - timedelta(hours=3),
            published_at=now - timedelta(hours=3),
        )
        make_news_relation(news_id=news.id, sector_id=sector.id)

        with patch("app.services.fund_manager.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = _gather_sector_news(db, sector.id)

        assert len(result) == 1
        assert result[0]["title"] == "반도체 업황 호조"


class TestGatherDisclosures:
    """_gather_disclosures 공시 수집 검증."""

    def test_no_disclosures(self, db: Session, make_stock) -> None:
        """공시가 없으면 빈 리스트를 반환한다."""
        stock = make_stock()
        result = _gather_disclosures(db, stock.id)
        assert result == []

    def test_returns_recent_disclosures(
        self, db: Session, make_stock, make_disclosure,
    ) -> None:
        """최근 공시를 조회한다."""
        stock = make_stock()
        today_str = datetime.now().strftime("%Y%m%d")
        make_disclosure(
            stock_id=stock.id,
            report_name="분기보고서 (2024.03)",
            report_type="정기공시",
            rcept_dt=today_str,
        )

        result = _gather_disclosures(db, stock.id, days=7)
        assert len(result) == 1
        assert result[0]["report_name"] == "분기보고서 (2024.03)"

    def test_old_disclosures_excluded(
        self, db: Session, make_stock, make_disclosure,
    ) -> None:
        """오래된 공시는 제외된다."""
        stock = make_stock()
        make_disclosure(
            stock_id=stock.id,
            rcept_dt="20230101",  # 아주 오래된 날짜
        )

        result = _gather_disclosures(db, stock.id, days=7)
        assert len(result) == 0


class TestFormatBriefingHint:
    """_format_briefing_hint 브리핑 힌트 포맷팅 검증."""

    def test_none_hint(self) -> None:
        """힌트가 None이면 독립 분석 표시를 반환한다."""
        result = _format_briefing_hint(None)
        assert result == "(독립 분석)"

    def test_with_action_and_reasoning(self) -> None:
        """action과 reasoning이 포함된 힌트를 포맷팅한다."""
        hint = {"action": "적극매수", "reasoning": "실적 호조와 수급 개선"}
        result = _format_briefing_hint(hint)
        assert "적극매수" in result
        assert "실적 호조와 수급 개선" in result

    def test_with_action_only(self) -> None:
        """action만 있는 힌트도 정상 처리한다."""
        hint = {"action": "관망", "reasoning": ""}
        result = _format_briefing_hint(hint)
        assert "관망" in result


class TestValidateCotSteps:
    """REQ-023: validate_cot_steps CoT 5단계 검증."""

    def test_all_steps_present(self) -> None:
        """5개 STEP 모두 포함된 응답은 complete=True."""
        text = (
            "[STEP 1: 시장 환경 진단] 현재 변동성이 높습니다.\n"
            "[STEP 2: 종목별 팩터 분석] 삼성전자 뉴스 팩터 양호.\n"
            "[STEP 3: 추세 정렬 검증] 5일/20일/60일 모두 상승.\n"
            "[STEP 4: 리스크 평가] 매크로 리스크 낮음.\n"
            "[STEP 5: 최종 추천 및 근거] 삼성전자 매수 추천."
        )
        result = validate_cot_steps(text)
        assert result["complete"] is True
        assert result["missing_steps"] == []
        assert len(result["found_steps"]) == 5

    def test_missing_some_steps(self) -> None:
        """일부 STEP이 누락되면 complete=False이고 missing_steps에 표시."""
        text = (
            "[STEP 1: 시장 환경 진단] 분석 내용.\n"
            "[STEP 3: 추세 정렬 검증] 분석 내용.\n"
            "[STEP 5: 최종 추천 및 근거] 분석 내용."
        )
        result = validate_cot_steps(text)
        assert result["complete"] is False
        assert "STEP 2" in result["missing_steps"]
        assert "STEP 4" in result["missing_steps"]
        assert len(result["found_steps"]) == 3

    def test_no_steps_at_all(self) -> None:
        """STEP이 하나도 없는 응답."""
        text = "그냥 일반 분석 텍스트입니다. 매수 추천합니다."
        result = validate_cot_steps(text)
        assert result["complete"] is False
        assert len(result["missing_steps"]) == 5

    def test_none_input(self) -> None:
        """None 입력이면 모든 STEP이 누락."""
        result = validate_cot_steps(None)
        assert result["complete"] is False
        assert result["missing_steps"] == list(COT_REQUIRED_STEPS)

    def test_empty_string(self) -> None:
        """빈 문자열이면 모든 STEP이 누락."""
        result = validate_cot_steps("")
        assert result["complete"] is False
        assert len(result["missing_steps"]) == 5


class TestApplyCotPenalty:
    """REQ-023: apply_cot_penalty CoT 불완전 분석 패널티 적용."""

    def test_complete_cot_no_penalty(self) -> None:
        """CoT 완전한 경우 패널티 없음."""
        parsed = {"market_overview": "test", "stock_picks": []}
        cot_result = {"complete": True, "missing_steps": [], "found_steps": list(COT_REQUIRED_STEPS)}
        result = apply_cot_penalty(parsed, cot_result)
        assert "_cot_validation" not in result

    def test_incomplete_cot_adds_tag(self) -> None:
        """CoT 불완전 시 _cot_validation 태그가 추가된다."""
        parsed = {"market_overview": "test", "stock_picks": []}
        cot_result = {
            "complete": False,
            "missing_steps": ["STEP 2", "STEP 4"],
            "found_steps": ["STEP 1", "STEP 3", "STEP 5"],
        }
        result = apply_cot_penalty(parsed, cot_result)
        assert "_cot_validation" in result
        assert result["_cot_validation"]["status"] == "incomplete_analysis"
        assert "STEP 2" in result["_cot_validation"]["missing_steps"]
        assert "STEP 4" in result["_cot_validation"]["missing_steps"]

    def test_all_steps_missing(self) -> None:
        """모든 STEP 누락 시에도 정상 동작."""
        parsed = {"market_overview": "test"}
        cot_result = {
            "complete": False,
            "missing_steps": list(COT_REQUIRED_STEPS),
            "found_steps": [],
        }
        result = apply_cot_penalty(parsed, cot_result)
        assert result["_cot_validation"]["status"] == "incomplete_analysis"
        assert len(result["_cot_validation"]["missing_steps"]) == 5
