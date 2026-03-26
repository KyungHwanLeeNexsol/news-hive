"""섹터 라우터 통합 테스트.

GET /api/sectors, POST /api/sectors, GET /api/sectors/{id},
DELETE /api/sectors/{id}, GET /api/sectors/{id}/news 엔드포인트를 검증한다.

외부 서비스(Naver Finance)는 mock 처리한다.
"""

from unittest.mock import AsyncMock, patch

import pytest


# ---------------------------------------------------------------------------
# GET /api/sectors -- 섹터 목록 조회
# ---------------------------------------------------------------------------

class TestListSectors:
    """GET /api/sectors 엔드포인트 테스트."""

    @patch(
        "app.services.naver_finance.fetch_sector_performances",
        new_callable=AsyncMock,
        return_value={},
    )
    def test_list_sectors_empty(self, _mock_perf, client):
        """섹터가 없으면 빈 리스트를 반환한다."""
        resp = client.get("/api/sectors")
        assert resp.status_code == 200
        assert resp.json() == []

    @patch(
        "app.services.naver_finance.fetch_sector_performances",
        new_callable=AsyncMock,
        return_value={},
    )
    def test_list_sectors_with_data(self, _mock_perf, client, make_sector, make_stock):
        """섹터와 종목이 있으면 stock_count를 포함하여 반환한다."""
        sector = make_sector(name="반도체")
        make_stock(name="삼성전자", sector_id=sector.id)
        make_stock(name="SK하이닉스", sector_id=sector.id)

        resp = client.get("/api/sectors")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "반도체"
        assert data[0]["stock_count"] == 2

    @patch(
        "app.services.naver_finance.fetch_sector_performances",
        new_callable=AsyncMock,
        return_value={},
    )
    def test_list_sectors_multiple(self, _mock_perf, client, make_sector):
        """여러 섹터가 존재하면 모두 반환한다."""
        make_sector(name="반도체")
        make_sector(name="건설기계")
        make_sector(name="자동차")

        resp = client.get("/api/sectors")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3


# ---------------------------------------------------------------------------
# POST /api/sectors -- 커스텀 섹터 생성
# ---------------------------------------------------------------------------

class TestCreateSector:
    """POST /api/sectors 엔드포인트 테스트."""

    def test_create_sector_success(self, client):
        """유효한 이름으로 커스텀 섹터를 생성한다."""
        resp = client.post("/api/sectors", json={"name": "나의 섹터"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "나의 섹터"
        assert data["is_custom"] is True
        assert "id" in data

    def test_create_sector_missing_name(self, client):
        """name 필드가 없으면 422를 반환한다."""
        resp = client.post("/api/sectors", json={})
        assert resp.status_code == 422

    def test_create_sector_empty_body(self, client):
        """요청 바디가 없으면 422를 반환한다."""
        resp = client.post("/api/sectors")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/sectors/{id} -- 섹터 상세 조회
# ---------------------------------------------------------------------------

class TestGetSector:
    """GET /api/sectors/{id} 엔드포인트 테스트."""

    @patch(
        "app.services.naver_finance.fetch_sector_stock_performances",
        new_callable=AsyncMock,
        return_value=[],
    )
    def test_get_sector_success(self, _mock_stock_perf, client, make_sector, make_stock):
        """존재하는 섹터의 상세 정보를 종목 목록과 함께 반환한다."""
        sector = make_sector(name="건설기계")
        make_stock(name="대창단조", stock_code="015230", sector_id=sector.id)

        resp = client.get(f"/api/sectors/{sector.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "건설기계"
        assert len(data["stocks"]) == 1
        assert data["stocks"][0]["name"] == "대창단조"
        assert data["stocks"][0]["stock_code"] == "015230"

    @patch(
        "app.services.naver_finance.fetch_sector_stock_performances",
        new_callable=AsyncMock,
        return_value=[],
    )
    def test_get_sector_no_stocks(self, _mock_stock_perf, client, make_sector):
        """종목이 없는 섹터도 정상적으로 반환한다."""
        sector = make_sector(name="빈 섹터")

        resp = client.get(f"/api/sectors/{sector.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["stocks"] == []

    def test_get_sector_not_found(self, client):
        """존재하지 않는 섹터 ID로 조회하면 404를 반환한다."""
        resp = client.get("/api/sectors/99999")
        assert resp.status_code == 404

    @patch(
        "app.services.naver_finance.fetch_sector_stock_performances",
        new_callable=AsyncMock,
        return_value=[],
    )
    def test_get_sector_news_count_in_stocks(
        self, _mock_stock_perf, client, db, make_sector, make_stock, make_news, make_news_relation
    ):
        """종목별 뉴스 수(news_count)가 정확히 계산된다."""
        sector = make_sector(name="테스트")
        stock = make_stock(name="종목A", sector_id=sector.id)
        news1 = make_news(title="뉴스1")
        news2 = make_news(title="뉴스2")
        make_news_relation(news_id=news1.id, stock_id=stock.id)
        make_news_relation(news_id=news2.id, stock_id=stock.id)

        resp = client.get(f"/api/sectors/{sector.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["stocks"][0]["news_count"] == 2


# ---------------------------------------------------------------------------
# DELETE /api/sectors/{id} -- 섹터 삭제
# ---------------------------------------------------------------------------

class TestDeleteSector:
    """DELETE /api/sectors/{id} 엔드포인트 테스트."""

    def test_delete_custom_sector(self, client, make_sector):
        """커스텀 섹터는 정상적으로 삭제된다."""
        sector = make_sector(name="삭제용", is_custom=True)
        resp = client.delete(f"/api/sectors/{sector.id}")
        assert resp.status_code == 204

    def test_delete_default_sector_fails(self, client, make_sector):
        """기본 섹터(is_custom=False)는 삭제할 수 없다 (400)."""
        sector = make_sector(name="기본섹터", is_custom=False)
        resp = client.delete(f"/api/sectors/{sector.id}")
        assert resp.status_code == 400
        assert "Cannot delete default sector" in resp.json()["detail"]

    def test_delete_sector_not_found(self, client):
        """존재하지 않는 섹터 삭제 시 404를 반환한다."""
        resp = client.delete("/api/sectors/99999")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/sectors/{id}/news -- 섹터 뉴스 피드
# ---------------------------------------------------------------------------

class TestGetSectorNews:
    """GET /api/sectors/{id}/news 엔드포인트 테스트."""

    def test_sector_news_with_data(
        self, client, db, make_sector, make_stock, make_news, make_news_relation
    ):
        """섹터에 연결된 뉴스가 있으면 목록을 반환한다."""
        sector = make_sector(name="반도체")
        stock = make_stock(name="삼성전자", sector_id=sector.id)
        news = make_news(title="삼성전자 실적 발표")
        make_news_relation(news_id=news.id, stock_id=stock.id, sector_id=sector.id)

        resp = client.get(f"/api/sectors/{sector.id}/news")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "삼성전자 실적 발표"
        assert "X-Total-Count" in resp.headers

    def test_sector_news_empty(self, client, make_sector):
        """뉴스가 없는 섹터는 빈 리스트와 total 0을 반환한다."""
        sector = make_sector(name="뉴스없음")

        resp = client.get(f"/api/sectors/{sector.id}/news")
        assert resp.status_code == 200
        assert resp.json() == []
        assert resp.headers["X-Total-Count"] == "0"

    def test_sector_news_not_found(self, client):
        """존재하지 않는 섹터의 뉴스 조회 시 404를 반환한다."""
        resp = client.get("/api/sectors/99999/news")
        assert resp.status_code == 404

    def test_sector_news_pagination(
        self, client, db, make_sector, make_stock, make_news, make_news_relation
    ):
        """limit/offset 파라미터로 뉴스 페이징이 동작한다."""
        sector = make_sector(name="페이징")
        stock = make_stock(name="종목", sector_id=sector.id)

        # 5개 뉴스 생성
        for i in range(5):
            news = make_news(title=f"뉴스 {i}")
            make_news_relation(news_id=news.id, stock_id=stock.id, sector_id=sector.id)

        resp = client.get(f"/api/sectors/{sector.id}/news?limit=2&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert resp.headers["X-Total-Count"] == "5"
