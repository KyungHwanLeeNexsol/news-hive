"""뉴스 라우터 통합 테스트.

GET /api/news, GET /api/news/{id} 엔드포인트를 검증한다.
크롤링 트리거(POST /api/news/refresh)는 복잡한 외부 의존성이 있어 제외한다.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.routers.news import _news_cache


@pytest.fixture(autouse=True)
def _clear_news_cache():
    """각 테스트 전에 뉴스 목록 응답 캐시를 초기화한다."""
    _news_cache.clear()
    yield
    _news_cache.clear()


# ---------------------------------------------------------------------------
# GET /api/news -- 뉴스 목록 조회
# ---------------------------------------------------------------------------

class TestListNews:
    """GET /api/news 엔드포인트 테스트."""

    def test_list_news_empty(self, client):
        """뉴스가 없으면 빈 리스트를 반환한다."""
        resp = client.get("/api/news")
        assert resp.status_code == 200
        assert resp.json() == []
        assert resp.headers["X-Total-Count"] == "0"

    def test_list_news_with_data(self, client, make_news):
        """뉴스가 있으면 목록을 반환한다."""
        make_news(title="테스트 뉴스 A")
        make_news(title="테스트 뉴스 B")

        resp = client.get("/api/news")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert resp.headers["X-Total-Count"] == "2"

    def test_list_news_pagination(self, client, make_news):
        """limit/offset으로 페이징이 동작한다."""
        for i in range(5):
            make_news(title=f"뉴스 {i}")

        resp = client.get("/api/news?limit=2&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert resp.headers["X-Total-Count"] == "5"

    def test_list_news_search_by_title(self, client, make_news):
        """q 파라미터로 제목 검색이 동작한다."""
        make_news(title="삼성전자 실적 발표")
        make_news(title="SK하이닉스 HBM 수주")
        make_news(title="현대차 전기차 출시")

        resp = client.get("/api/news?q=삼성")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert "삼성" in data[0]["title"]

    def test_list_news_search_no_match(self, client, make_news):
        """검색 결과가 없으면 빈 리스트를 반환한다."""
        make_news(title="테스트 뉴스")

        resp = client.get("/api/news?q=존재하지않는키워드xyz")
        assert resp.status_code == 200
        assert resp.json() == []
        assert resp.headers["X-Total-Count"] == "0"

    def test_list_news_response_structure(self, client, make_news):
        """응답 JSON에 필수 필드가 포함되어 있다."""
        make_news(title="구조 테스트", source="naver", sentiment="positive")

        resp = client.get("/api/news")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        article = data[0]
        assert "id" in article
        assert "title" in article
        assert "url" in article
        assert "source" in article
        assert "sentiment" in article
        assert "published_at" in article
        assert "collected_at" in article
        assert "relations" in article
        assert article["source"] == "naver"
        assert article["sentiment"] == "positive"

    def test_list_news_with_relations(
        self, client, make_news, make_sector, make_stock, make_news_relation
    ):
        """뉴스에 연결된 종목/섹터 관계 정보가 포함된다."""
        sector = make_sector(name="반도체")
        stock = make_stock(name="삼성전자", sector_id=sector.id)
        news = make_news(title="삼성전자 관련 뉴스")
        make_news_relation(
            news_id=news.id,
            stock_id=stock.id,
            sector_id=sector.id,
            relevance="direct",
        )

        resp = client.get("/api/news")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        relations = data[0]["relations"]
        assert len(relations) == 1
        assert relations[0]["stock_name"] == "삼성전자"
        assert relations[0]["sector_name"] == "반도체"
        assert relations[0]["relevance"] == "direct"


# ---------------------------------------------------------------------------
# GET /api/news/{id} -- 뉴스 상세 조회
# ---------------------------------------------------------------------------

class TestGetNewsDetail:
    """GET /api/news/{id} 엔드포인트 테스트."""

    def test_get_news_detail_success(self, client, make_news, make_sector, make_news_relation):
        """존재하는 뉴스의 상세 정보를 반환한다."""
        sector = make_sector(name="테스트섹터")
        news = make_news(title="상세 조회 뉴스")
        # 섹터 관계가 있어야 on-demand 분류가 트리거되지 않음
        make_news_relation(news_id=news.id, sector_id=sector.id)

        resp = client.get(f"/api/news/{news.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "상세 조회 뉴스"
        assert data["id"] == news.id

    def test_get_news_detail_not_found(self, client):
        """존재하지 않는 뉴스 ID로 조회하면 404를 반환한다."""
        resp = client.get("/api/news/99999")
        assert resp.status_code == 404
        assert "News article not found" in resp.json()["detail"]

    @patch(
        "app.routers.news._classify_article_on_demand",
        new_callable=AsyncMock,
    )
    def test_get_news_detail_triggers_classification(
        self, mock_classify, client, make_news
    ):
        """섹터 관계가 없는 뉴스는 on-demand 분류를 트리거한다."""
        news = make_news(title="미분류 뉴스")

        resp = client.get(f"/api/news/{news.id}")
        assert resp.status_code == 200
        mock_classify.assert_called_once()
