"""종목 라우터 통합 테스트.

GET /api/stocks, GET /api/stocks/{id}, POST /api/sectors/{id}/stocks,
DELETE /api/stocks/{id}, GET /api/stocks/{id}/news 엔드포인트를 검증한다.

외부 서비스(naver_finance, financial_scraper, kis_api)는 mock 처리한다.
"""

from unittest.mock import AsyncMock, MagicMock, patch



# ---------------------------------------------------------------------------
# 외부 서비스 mock을 위한 헬퍼
# ---------------------------------------------------------------------------

def _make_fundamentals(**overrides):
    """fetch_stock_fundamentals 반환 객체를 모방하는 MagicMock."""
    defaults = {
        "current_price": 50000,
        "price_change": 1000,
        "change_rate": 2.0,
        "volume": 100000,
        "trading_value": 5000000000,
        "eps": 3000,
        "bps": 25000,
        "dividend": 500,
    }
    defaults.update(overrides)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _make_valuation(**overrides):
    """fetch_stock_valuation 반환 객체를 모방하는 MagicMock."""
    defaults = {
        "per": 15.0,
        "pbr": 1.2,
        "market_cap": 300000000000,
        "foreign_ratio": 30.5,
        "dividend_yield": 1.5,
        "industry_per": 18.0,
    }
    defaults.update(overrides)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _make_kis(**overrides):
    """fetch_kis_stock_price 반환 객체를 모방하는 MagicMock."""
    defaults = {
        "current_price": 51000,
        "price_change": 1100,
        "change_rate": 2.2,
        "volume": 110000,
        "trading_value": 5500000000,
        "eps": 3100,
        "bps": 26000,
        "per": 16.0,
        "pbr": 1.3,
        "market_cap": 310000000000,
        "foreign_ratio": 31.0,
        "high_52w": 70000,
        "low_52w": 30000,
    }
    defaults.update(overrides)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


# ---------------------------------------------------------------------------
# POST /api/sectors/{sector_id}/stocks -- 종목 생성
# ---------------------------------------------------------------------------

class TestCreateStock:
    """POST /api/sectors/{sector_id}/stocks 엔드포인트 테스트."""

    def test_create_stock_success(self, client, make_sector):
        """유효한 데이터로 종목을 생성하면 201을 반환한다."""
        sector = make_sector(name="반도체")
        resp = client.post(
            f"/api/sectors/{sector.id}/stocks",
            json={"name": "삼성전자", "stock_code": "005930"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "삼성전자"
        assert data["stock_code"] == "005930"
        assert data["sector_id"] == sector.id

    def test_create_stock_sector_not_found(self, client):
        """존재하지 않는 섹터 ID로 요청하면 404를 반환한다."""
        resp = client.post(
            "/api/sectors/99999/stocks",
            json={"name": "테스트", "stock_code": "000000"},
        )
        assert resp.status_code == 404

    def test_create_stock_with_keywords(self, client, make_sector):
        """keywords 필드를 포함하여 종목을 생성할 수 있다."""
        sector = make_sector(name="건설기계")
        resp = client.post(
            f"/api/sectors/{sector.id}/stocks",
            json={"name": "대창단조", "stock_code": "015230", "keywords": ["포크레인", "건설"]},
        )
        assert resp.status_code == 201
        assert resp.json()["name"] == "대창단조"


# ---------------------------------------------------------------------------
# GET /api/stocks -- 종목 목록 조회
# ---------------------------------------------------------------------------

class TestListStocks:
    """GET /api/stocks 엔드포인트 테스트."""

    @patch(
        "app.routers.stocks.fetch_naver_stock_list",
        new_callable=AsyncMock,
        return_value=([], 0),
    )
    def test_list_stocks_empty_default(self, _mock_naver, client):
        """종목이 없으면 빈 리스트를 반환한다 (기본 Naver 모드)."""
        resp = client.get("/api/stocks")
        assert resp.status_code == 200
        assert resp.json() == []

    @patch(
        "app.routers.stocks.fetch_stock_fundamentals_batch",
        new_callable=AsyncMock,
        return_value={},
    )
    def test_list_stocks_with_search_query(self, _mock_batch, client, make_stock):
        """q 파라미터로 종목 이름 검색이 가능하다."""
        stock = make_stock(name="삼성전자", stock_code="005930")
        resp = client.get("/api/stocks", params={"q": "삼성"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["name"] == "삼성전자"

    @patch(
        "app.routers.stocks.fetch_stock_fundamentals_batch",
        new_callable=AsyncMock,
        return_value={},
    )
    def test_list_stocks_with_ids_filter(self, _mock_batch, client, make_stock):
        """ids 파라미터로 특정 종목만 조회할 수 있다."""
        s1 = make_stock(name="종목A")
        s2 = make_stock(name="종목B")
        make_stock(name="종목C")  # 조회에 포함되지 않아야 함

        resp = client.get("/api/stocks", params={"ids": f"{s1.id},{s2.id}"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        names = {item["name"] for item in data}
        assert "종목A" in names
        assert "종목B" in names

    @patch(
        "app.routers.stocks.fetch_stock_fundamentals_batch",
        new_callable=AsyncMock,
        return_value={},
    )
    def test_list_stocks_pagination(self, _mock_batch, client, make_sector, make_stock):
        """limit/offset 파라미터로 페이지네이션이 동작한다."""
        sector = make_sector(name="테스트섹터")
        for i in range(5):
            make_stock(name=f"종목_{i:02d}", sector_id=sector.id)

        resp = client.get("/api/stocks", params={"sector_id": sector.id, "limit": 2, "offset": 0})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert resp.headers.get("X-Total-Count") == "5"


# ---------------------------------------------------------------------------
# GET /api/stocks/{stock_id} -- 종목 상세 조회
# ---------------------------------------------------------------------------

class TestGetStockDetail:
    """GET /api/stocks/{id} 엔드포인트 테스트."""

    @patch("app.routers.stocks.fetch_kis_stock_price", new_callable=AsyncMock)
    @patch("app.routers.stocks.fetch_stock_valuation", new_callable=AsyncMock)
    @patch("app.routers.stocks.fetch_stock_fundamentals", new_callable=AsyncMock)
    def test_stock_detail_success(
        self, mock_fund, mock_val, mock_kis, client, make_stock
    ):
        """종목 상세 조회 시 외부 데이터를 병합하여 반환한다."""
        stock = make_stock(name="삼성전자", stock_code="005930")
        mock_fund.return_value = _make_fundamentals()
        mock_val.return_value = _make_valuation()
        mock_kis.return_value = _make_kis()

        resp = client.get(f"/api/stocks/{stock.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "삼성전자"
        assert data["stock_code"] == "005930"
        # KIS 데이터가 우선
        assert data["current_price"] == 51000
        assert data["high_52w"] == 70000
        assert data["low_52w"] == 30000

    @patch("app.routers.stocks.fetch_kis_stock_price", new_callable=AsyncMock, return_value=None)
    @patch("app.routers.stocks.fetch_stock_valuation", new_callable=AsyncMock, return_value=None)
    @patch("app.routers.stocks.fetch_stock_fundamentals", new_callable=AsyncMock)
    def test_stock_detail_kis_unavailable_falls_back_to_naver(
        self, mock_fund, _mock_val, _mock_kis, client, make_stock
    ):
        """KIS API가 실패하면 Naver 데이터로 fallback한다."""
        stock = make_stock(name="SK하이닉스", stock_code="000660")
        mock_fund.return_value = _make_fundamentals(current_price=120000)

        resp = client.get(f"/api/stocks/{stock.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_price"] == 120000
        # KIS 전용 필드는 None
        assert data["high_52w"] is None

    def test_stock_detail_not_found(self, client):
        """존재하지 않는 종목 ID로 요청하면 404를 반환한다."""
        resp = client.get("/api/stocks/99999")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/stocks/{stock_id} -- 종목 삭제
# ---------------------------------------------------------------------------

class TestDeleteStock:
    """DELETE /api/stocks/{id} 엔드포인트 테스트."""

    def test_delete_stock_success(self, client, make_stock):
        """존재하는 종목을 삭제하면 204를 반환한다."""
        stock = make_stock(name="삭제대상")
        resp = client.delete(f"/api/stocks/{stock.id}")
        assert resp.status_code == 204

    def test_delete_stock_not_found(self, client):
        """존재하지 않는 종목을 삭제하면 404를 반환한다."""
        resp = client.delete("/api/stocks/99999")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/stocks/{stock_id}/news -- 종목 뉴스 피드
# ---------------------------------------------------------------------------

class TestGetStockNews:
    """GET /api/stocks/{id}/news 엔드포인트 테스트."""

    def test_stock_news_empty(self, client, make_stock):
        """뉴스가 없는 종목은 빈 리스트를 반환한다."""
        stock = make_stock(name="뉴스없는종목")
        resp = client.get(f"/api/stocks/{stock.id}/news")
        assert resp.status_code == 200
        assert resp.json() == []
        assert resp.headers.get("X-Total-Count") == "0"

    def test_stock_news_with_data(
        self, client, make_stock, make_news, make_news_relation
    ):
        """종목에 연결된 뉴스가 있으면 해당 뉴스를 반환한다."""
        stock = make_stock(name="뉴스종목")
        news1 = make_news(title="관련 뉴스 1")
        news2 = make_news(title="관련 뉴스 2")
        make_news_relation(news_id=news1.id, stock_id=stock.id)
        make_news_relation(news_id=news2.id, stock_id=stock.id)

        resp = client.get(f"/api/stocks/{stock.id}/news")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert resp.headers.get("X-Total-Count") == "2"

    def test_stock_news_not_found(self, client):
        """존재하지 않는 종목의 뉴스를 조회하면 404를 반환한다."""
        resp = client.get("/api/stocks/99999/news")
        assert resp.status_code == 404
