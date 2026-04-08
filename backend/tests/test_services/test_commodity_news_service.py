"""원자재 뉴스 크롤링 및 분류 서비스 테스트.

commodity_news_service.py의 핵심 기능을 테스트한다:
- 키워드 기반 원자재 뉴스 분류 (classify_commodity_news)
- 영향 방향 판별 (_determine_impact_direction)
- AI 기반 원자재 분류 (classify_commodity_news_with_ai)
- MacroAlert 생성 (_check_supply_disruption_alerts)
- 크롤링 파이프라인 (crawl_commodity_news)
"""
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.orm import Session

from app.models.commodity import Commodity, SectorCommodityRelation
from app.models.news import NewsArticle
from app.models.news_commodity_relation import NewsCommodityRelation
from app.models.macro_alert import MacroAlert
from app.services.commodity_news_service import (
    classify_commodity_news,
    _determine_impact_direction,
    _build_commodity_keyword_map,
    get_commodity_search_queries,
    _infer_category_from_keyword,
    _check_supply_disruption_alerts,
    _get_related_sector_names,
    classify_commodity_news_with_ai,
    crawl_commodity_news,
    COMMODITY_KEYWORDS_KO,
)


# ---------------------------------------------------------------------------
# 픽스처
# ---------------------------------------------------------------------------

@pytest.fixture
def make_commodity(db: Session):
    """Commodity 팩토리."""
    _counter = 0

    def _factory(
        symbol: str | None = None,
        name_ko: str | None = None,
        name_en: str | None = None,
        category: str = "energy",
        unit: str = "barrel",
        **kwargs,
    ) -> Commodity:
        nonlocal _counter
        _counter += 1
        defaults = {
            "symbol": symbol or f"TEST{_counter}=F",
            "name_ko": name_ko or f"테스트원자재_{_counter}",
            "name_en": name_en or f"Test Commodity {_counter}",
            "category": category,
            "unit": unit,
        }
        defaults.update(kwargs)
        commodity = Commodity(**defaults)
        db.add(commodity)
        db.flush()
        return commodity

    return _factory


@pytest.fixture
def make_sector_commodity_relation(db: Session):
    """SectorCommodityRelation 팩토리."""

    def _factory(
        sector_id: int,
        commodity_id: int,
        correlation_type: str = "positive",
        description: str | None = None,
    ) -> SectorCommodityRelation:
        rel = SectorCommodityRelation(
            sector_id=sector_id,
            commodity_id=commodity_id,
            correlation_type=correlation_type,
            description=description,
        )
        db.add(rel)
        db.flush()
        return rel

    return _factory


# ---------------------------------------------------------------------------
# 테스트: 영향 방향 판별
# ---------------------------------------------------------------------------

class TestDetermineImpactDirection:
    """_determine_impact_direction 함수 테스트."""

    def test_price_up(self):
        assert _determine_impact_direction("국제유가 급등, 배럴당 80달러 돌파") == "price_up"
        assert _determine_impact_direction("금값 상승세 지속") == "price_up"

    def test_price_down(self):
        assert _determine_impact_direction("원유 가격 급락, OPEC 감산 실패") == "price_down"
        assert _determine_impact_direction("구리가격 하락세 전환") == "price_down"

    def test_supply_disruption(self):
        assert _determine_impact_direction("중동 긴장으로 원유 공급 차질 우려") == "supply_disruption"
        assert _determine_impact_direction("호주 광산 파업, 철광석 감산 우려") == "supply_disruption"

    def test_demand_change(self):
        assert _determine_impact_direction("중국 경기 둔화로 원자재 수요 감소") == "demand_change"
        assert _determine_impact_direction("전기차 확대로 리튬 수요 급증") == "demand_change"

    def test_policy_change(self):
        assert _determine_impact_direction("원자재 무역 규제 변경") == "policy_change"
        assert _determine_impact_direction("OPEC 정책 논의 진행") == "policy_change"

    def test_neutral(self):
        assert _determine_impact_direction("원자재 시장 동향 분석") == "neutral"
        assert _determine_impact_direction("국제 에너지 보고서 발간") == "neutral"


# ---------------------------------------------------------------------------
# 테스트: 키워드 맵 빌드
# ---------------------------------------------------------------------------

class TestBuildCommodityKeywordMap:
    """_build_commodity_keyword_map 함수 테스트."""

    def test_normal_commodity(self, db, make_commodity):
        """일반 원자재 이름이 키워드 맵에 등록되는지 확인."""
        oil = make_commodity(
            symbol="CL=F", name_ko="WTI 원유", name_en="WTI Crude Oil",
            category="energy", unit="barrel",
        )
        kw_map = _build_commodity_keyword_map([oil])
        assert "wti 원유" in kw_map
        assert "wti crude oil" in kw_map
        assert kw_map["wti 원유"] == oil.id

    def test_short_korean_name_skipped(self, db, make_commodity):
        """1~2글자 한국어 이름(금, 은 등)은 단독 키워드로 등록하지 않는다."""
        gold = make_commodity(
            symbol="GC=F", name_ko="금", name_en="Gold",
            category="metal", unit="oz",
        )
        kw_map = _build_commodity_keyword_map([gold])
        # "금"은 직접 등록하지 않음 (오탐 방지)
        assert "금" not in kw_map
        # 보강 키워드는 등록됨
        assert "금값" in kw_map
        assert "금가격" in kw_map

    def test_symbol_too_short_excluded(self, db, make_commodity):
        """2글자 이하 심볼은 오탐 방지로 제외."""
        commodity = make_commodity(symbol="CL=F", name_ko="원유", name_en="Crude Oil")
        kw_map = _build_commodity_keyword_map([commodity])
        # CL (2글자) → 제외
        assert "cl" not in kw_map


# ---------------------------------------------------------------------------
# 테스트: 키워드 기반 원자재 분류
# ---------------------------------------------------------------------------

class TestClassifyCommodityNews:
    """classify_commodity_news 키워드 기반 분류 테스트."""

    def test_direct_match(self, db, make_commodity, make_news):
        """제목에 원자재 이름이 포함되면 direct 관계 생성."""
        oil = make_commodity(
            symbol="CL=F", name_ko="WTI 원유", name_en="WTI Crude Oil",
            category="energy", unit="barrel",
        )
        news = make_news(title="WTI 원유 가격 급등, 배럴당 85달러 돌파")

        relations = classify_commodity_news(db, news.id, news.title)
        assert len(relations) >= 1
        assert relations[0].commodity_id == oil.id
        assert relations[0].relevance == "direct"
        assert relations[0].impact_direction == "price_up"

    def test_no_match(self, db, make_commodity, make_news):
        """원자재와 무관한 뉴스는 빈 리스트 반환."""
        make_commodity(
            symbol="CL=F", name_ko="WTI 원유", name_en="WTI Crude Oil",
            category="energy", unit="barrel",
        )
        news = make_news(title="삼성전자 반도체 투자 확대 발표")

        relations = classify_commodity_news(db, news.id, news.title)
        assert len(relations) == 0

    def test_non_financial_article_skipped(self, db, make_commodity, make_news):
        """비금융 기사는 분류를 건너뛴다."""
        make_commodity(
            symbol="GC=F", name_ko="금", name_en="Gold",
            category="metal", unit="oz",
        )
        news = make_news(title="드라마 속 금 장신구 화제")

        relations = classify_commodity_news(db, news.id, news.title)
        assert len(relations) == 0

    def test_category_fallback(self, db, make_commodity, make_news):
        """특정 원자재 매칭 실패 시 포괄 키워드로 카테고리 매칭."""
        oil = make_commodity(
            symbol="CL=F", name_ko="WTI 원유", name_en="WTI Crude Oil",
            category="energy", unit="barrel",
        )
        news = make_news(title="국제유가 향방에 시장 촉각")

        relations = classify_commodity_news(db, news.id, news.title)
        # "국제유가" → energy 카테고리 → WTI 원유 매칭
        assert len(relations) >= 1
        matched_commodity_ids = {r.commodity_id for r in relations}
        assert oil.id in matched_commodity_ids

    def test_dedup_same_commodity(self, db, make_commodity, make_news):
        """동일 원자재가 여러 키워드로 매칭되어도 중복 생성하지 않는다."""
        gold = make_commodity(
            symbol="GC=F", name_ko="금", name_en="Gold",
            category="metal", unit="oz",
        )
        # "금값"과 "금가격" 모두 gold에 매핑되지만 1건만 생성
        news = make_news(title="금값 상승, 금가격 전망 밝아")

        relations = classify_commodity_news(db, news.id, news.title)
        commodity_ids = [r.commodity_id for r in relations]
        assert commodity_ids.count(gold.id) == 1


# ---------------------------------------------------------------------------
# 테스트: 검색 쿼리
# ---------------------------------------------------------------------------

class TestGetCommoditySearchQueries:

    def test_returns_queries(self):
        queries = get_commodity_search_queries()
        assert len(queries) > 0
        assert len(queries) <= 10

    def test_contains_korean_keywords(self):
        queries = get_commodity_search_queries()
        # 한국어 키워드에서 선택됨
        assert all(q in COMMODITY_KEYWORDS_KO for q in queries)


# ---------------------------------------------------------------------------
# 테스트: 카테고리 추론
# ---------------------------------------------------------------------------

class TestInferCategory:

    def test_energy(self):
        assert _infer_category_from_keyword("유가") == "energy"
        assert _infer_category_from_keyword("천연가스") == "energy"

    def test_metal(self):
        assert _infer_category_from_keyword("금값") == "metal"
        assert _infer_category_from_keyword("구리가격") == "metal"

    def test_agriculture(self):
        assert _infer_category_from_keyword("곡물가격") == "agriculture"

    def test_generic_returns_none(self):
        assert _infer_category_from_keyword("원자재") is None


# ---------------------------------------------------------------------------
# 테스트: 관련 섹터 이름 조회
# ---------------------------------------------------------------------------

class TestGetRelatedSectorNames:

    def test_returns_sector_names(
        self, db, make_sector, make_commodity, make_sector_commodity_relation,
    ):
        sector = make_sector(name="에너지")
        oil = make_commodity(symbol="CL=F", name_ko="WTI 원유", name_en="WTI Crude Oil")
        make_sector_commodity_relation(sector.id, oil.id)

        names = _get_related_sector_names(db, {oil.id})
        assert "에너지" in names

    def test_empty_for_no_ids(self, db):
        names = _get_related_sector_names(db, set())
        assert names == []


# ---------------------------------------------------------------------------
# 테스트: MacroAlert 생성
# ---------------------------------------------------------------------------

class TestCheckSupplyDisruptionAlerts:

    def test_creates_alert_for_supply_disruption(
        self, db, make_commodity, make_sector, make_sector_commodity_relation,
    ):
        """supply_disruption 뉴스가 있으면 관련 섹터 태그를 포함한 MacroAlert를 생성한다."""
        sector = make_sector(name="에너지")
        oil = make_commodity(
            symbol="CL=F", name_ko="WTI 원유", name_en="WTI Crude Oil",
            category="energy", unit="barrel",
        )
        make_sector_commodity_relation(sector.id, oil.id)

        # 제목에 "WTI 원유"를 포함하여 kw_map 매칭이 되도록
        batch = [
            {"title": "중동 긴장으로 WTI 원유 공급 차질 우려 확산", "url": "https://test.com/1"},
        ]
        url_to_id = {"https://test.com/1": 1}

        _check_supply_disruption_alerts(db, batch, url_to_id)

        alert = db.query(MacroAlert).filter(MacroAlert.keyword == "원자재 공급 차질").first()
        assert alert is not None
        assert "공급 차질" in alert.title
        # REQ-CNR-016: 관련 섹터 태그 포함
        assert "에너지" in alert.description

    def test_no_duplicate_alert_within_24h(self, db, make_macro_alert, make_commodity):
        """24시간 내 동일 키워드 알림이 있으면 중복 생성하지 않는다."""
        make_macro_alert(keyword="원자재 공급 차질")
        make_commodity(
            symbol="CL=F", name_ko="WTI 원유", name_en="WTI Crude Oil",
            category="energy", unit="barrel",
        )

        batch = [
            {"title": "원유 공급 차질 우려", "url": "https://test.com/2"},
        ]
        url_to_id = {"https://test.com/2": 2}

        _check_supply_disruption_alerts(db, batch, url_to_id)

        alerts = db.query(MacroAlert).filter(MacroAlert.keyword == "원자재 공급 차질").all()
        assert len(alerts) == 1  # 기존 1건만 존재


# ---------------------------------------------------------------------------
# 테스트: AI 기반 원자재 분류
# ---------------------------------------------------------------------------

class TestClassifyCommodityNewsWithAI:
    """classify_commodity_news_with_ai 함수 테스트."""

    @pytest.mark.asyncio
    async def test_ai_classification_creates_relations(
        self, db, make_commodity, make_news,
    ):
        """AI 분류가 정상적으로 news_commodity_relations을 생성하는지 확인."""
        oil = make_commodity(
            symbol="CL=F", name_ko="WTI 원유", name_en="WTI Crude Oil",
            category="energy", unit="barrel",
        )
        news = make_news(title="OPEC 회의 결과 시장 반응")

        url_to_id = {news.url: news.id}
        articles = [{"title": news.title, "url": news.url, "description": ""}]

        # AI 응답 모킹
        ai_response = json.dumps([{
            "id": 1,
            "commodities": [{
                "commodity_id": oil.id,
                "impact": "policy_change",
                "relevance": "indirect",
            }],
        }])

        with patch("app.services.ai_client.ask_ai_free_standard", new_callable=AsyncMock, return_value=ai_response):
            count = await classify_commodity_news_with_ai(db, articles, url_to_id)

        assert count == 1
        rel = db.query(NewsCommodityRelation).filter(
            NewsCommodityRelation.news_id == news.id,
        ).first()
        assert rel is not None
        assert rel.commodity_id == oil.id
        assert rel.match_type == "ai_classified"
        assert rel.impact_direction == "policy_change"

    @pytest.mark.asyncio
    async def test_ai_skips_already_classified(
        self, db, make_commodity, make_news,
    ):
        """이미 키워드로 분류된 기사는 AI 분류를 건너뛴다."""
        oil = make_commodity(
            symbol="CL=F", name_ko="WTI 원유", name_en="WTI Crude Oil",
            category="energy", unit="barrel",
        )
        news = make_news(title="WTI 원유 급등")

        # 미리 키워드 분류 수행
        rel = NewsCommodityRelation(
            news_id=news.id, commodity_id=oil.id,
            relevance="direct", impact_direction="price_up", match_type="keyword",
        )
        db.add(rel)
        db.flush()

        url_to_id = {news.url: news.id}
        articles = [{"title": news.title, "url": news.url}]

        with patch("app.services.ai_client.ask_ai", new_callable=AsyncMock) as mock_ai:
            count = await classify_commodity_news_with_ai(db, articles, url_to_id)

        assert count == 0
        mock_ai.assert_not_called()

    @pytest.mark.asyncio
    async def test_ai_invalid_impact_defaults_to_neutral(
        self, db, make_commodity, make_news,
    ):
        """AI가 잘못된 impact_direction을 반환하면 neutral로 기본값 처리."""
        oil = make_commodity(
            symbol="CL=F", name_ko="WTI 원유", name_en="WTI Crude Oil",
            category="energy", unit="barrel",
        )
        news = make_news(title="에너지 시장 분석 리포트")

        url_to_id = {news.url: news.id}
        articles = [{"title": news.title, "url": news.url, "description": ""}]

        ai_response = json.dumps([{
            "id": 1,
            "commodities": [{
                "commodity_id": oil.id,
                "impact": "invalid_value",
                "relevance": "direct",
            }],
        }])

        with patch("app.services.ai_client.ask_ai_free_standard", new_callable=AsyncMock, return_value=ai_response):
            count = await classify_commodity_news_with_ai(db, articles, url_to_id)

        assert count == 1
        rel = db.query(NewsCommodityRelation).filter(
            NewsCommodityRelation.news_id == news.id,
        ).first()
        assert rel.impact_direction == "neutral"

    @pytest.mark.asyncio
    async def test_ai_failure_returns_zero(
        self, db, make_commodity, make_news,
    ):
        """AI 호출 실패 시 0을 반환하고 기존 데이터에 영향 없음."""
        make_commodity(
            symbol="CL=F", name_ko="WTI 원유", name_en="WTI Crude Oil",
            category="energy", unit="barrel",
        )
        news = make_news(title="에너지 시장 동향")

        url_to_id = {news.url: news.id}
        articles = [{"title": news.title, "url": news.url}]

        with patch("app.services.ai_client.ask_ai", new_callable=AsyncMock, side_effect=Exception("API error")):
            count = await classify_commodity_news_with_ai(db, articles, url_to_id)

        assert count == 0


# ---------------------------------------------------------------------------
# 테스트: 크롤링 파이프라인 통합
# ---------------------------------------------------------------------------

class TestCrawlCommodityNews:
    """crawl_commodity_news 통합 테스트."""

    @pytest.mark.asyncio
    async def test_crawl_saves_articles_and_relations(
        self, db, make_commodity,
    ):
        """크롤링 파이프라인이 기사 저장과 원자재 분류를 수행하는지 확인."""
        oil = make_commodity(
            symbol="CL=F", name_ko="WTI 원유", name_en="WTI Crude Oil",
            category="energy", unit="barrel",
        )

        mock_naver_results = [
            {
                "title": "WTI 원유 가격 급등, 배럴당 85달러",
                "url": "https://test.naver.com/commodity_1",
                "source": "naver",
                "description": "국제유가가 급등했다",
                "published_at": datetime.now(timezone.utc),
            },
        ]

        with patch(
            "app.services.crawlers.naver.search_naver_news",
            new_callable=AsyncMock,
            return_value=mock_naver_results,
        ), patch(
            "app.services.crawlers.google.search_google_news",
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            "app.services.ai_client.ask_ai",
            new_callable=AsyncMock,
            return_value="[]",
        ):
            count = await crawl_commodity_news(db)

        assert count >= 1

        # news_articles에 저장되었는지 확인
        article = db.query(NewsArticle).filter(
            NewsArticle.url == "https://test.naver.com/commodity_1",
        ).first()
        assert article is not None

        # news_commodity_relations에 분류되었는지 확인
        rel = db.query(NewsCommodityRelation).filter(
            NewsCommodityRelation.news_id == article.id,
        ).first()
        assert rel is not None
        assert rel.commodity_id == oil.id

    @pytest.mark.asyncio
    async def test_crawl_deduplicates_urls(self, db, make_commodity, make_news):
        """이미 DB에 있는 URL은 다시 크롤링하지 않는다."""
        make_commodity(
            symbol="CL=F", name_ko="WTI 원유", name_en="WTI Crude Oil",
            category="energy", unit="barrel",
        )
        # 이미 존재하는 기사
        make_news(title="기존 기사", url="https://test.naver.com/existing")

        mock_results = [
            {
                "title": "WTI 원유 급등",
                "url": "https://test.naver.com/existing",  # 중복 URL
                "source": "naver",
                "published_at": datetime.now(timezone.utc),
            },
        ]

        with patch(
            "app.services.crawlers.naver.search_naver_news",
            new_callable=AsyncMock,
            return_value=mock_results,
        ), patch(
            "app.services.crawlers.google.search_google_news",
            new_callable=AsyncMock,
            return_value=[],
        ):
            count = await crawl_commodity_news(db)

        assert count == 0

    @pytest.mark.asyncio
    async def test_crawl_no_commodities(self, db):
        """원자재가 없으면 크롤링만 하고 분류 없이 종료."""
        mock_results = [
            {
                "title": "원자재 시장 동향",
                "url": "https://test.naver.com/empty_commodity",
                "source": "naver",
                "published_at": datetime.now(timezone.utc),
            },
        ]

        with patch(
            "app.services.crawlers.naver.search_naver_news",
            new_callable=AsyncMock,
            return_value=mock_results,
        ), patch(
            "app.services.crawlers.google.search_google_news",
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            "app.services.ai_client.ask_ai",
            new_callable=AsyncMock,
            return_value="[]",
        ):
            count = await crawl_commodity_news(db)

        # 원자재 분류는 안 되지만 기사는 저장될 수 있음
        assert count == 0
