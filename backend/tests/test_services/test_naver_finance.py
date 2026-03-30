"""naver_finance 서비스 테스트.

네이버 금융 스크래핑/API 호출을 모두 mock 처리하여
파싱 로직, 캐시 동작, 에러 핸들링을 검증한다.
"""

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.naver_finance import (
    SectorPerformance,
    _cache,
    _extract_code,
    _parse_change_rate,
    _parse_int_safe,
    _parse_comma_int,
    fetch_sector_performances,
    fetch_stock_fundamentals,
    fetch_stock_fundamentals_batch,
    fetch_stock_price_history,
    fetch_naver_stock_list,
    fetch_sector_stock_codes,
    fetch_investor_trading,
    _fundamentals_cache,
    _price_cache,
    _naver_stock_list_cache,
)


# ---------------------------------------------------------------------------
# 유틸 함수 단위 테스트
# ---------------------------------------------------------------------------


class TestParseHelpers:
    """파싱 유틸리티 함수 테스트."""

    def test_extract_code_with_no_param(self) -> None:
        """no= 파라미터가 있는 URL에서 코드를 추출한다."""
        assert _extract_code("/sise/sise_group_detail.naver?type=upjong&no=261") == "261"

    def test_extract_code_without_no_param(self) -> None:
        """no= 파라미터가 없으면 None을 반환한다."""
        assert _extract_code("/sise/sise_group.naver?type=upjong") is None

    def test_extract_code_empty_string(self) -> None:
        assert _extract_code("") is None

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("+8.02%", 8.02),
            ("-1.23%", -1.23),
            ("0.00%", 0.0),
            ("3.5%", 3.5),
            ("abc", 0.0),
            ("", 0.0),
        ],
        ids=["positive", "negative", "zero", "no_sign", "invalid", "empty"],
    )
    def test_parse_change_rate(self, text: str, expected: float) -> None:
        assert _parse_change_rate(text) == pytest.approx(expected)

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("1,234", 1234),
            ("0", 0),
            ("abc", 0),
            ("", 0),
        ],
        ids=["comma_separated", "zero", "invalid", "empty"],
    )
    def test_parse_int_safe(self, text: str, expected: int) -> None:
        assert _parse_int_safe(text) == expected

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("187,400", 187400),
            ("0", 0),
            ("abc", 0),
        ],
    )
    def test_parse_comma_int(self, text: str, expected: int) -> None:
        assert _parse_comma_int(text) == expected


# ---------------------------------------------------------------------------
# fetch_sector_performances 테스트
# ---------------------------------------------------------------------------


class TestFetchSectorPerformances:
    """섹터 실적 스크래핑 테스트."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        """각 테스트 전후로 캐시를 초기화한다."""
        _cache.data.clear()
        _cache.last_updated = 0.0
        yield
        _cache.data.clear()
        _cache.last_updated = 0.0

    @pytest.mark.asyncio
    @patch("app.services.naver_finance.httpx.AsyncClient")
    async def test_fetches_and_parses_sector_html(self, mock_client_cls) -> None:
        """HTML 테이블에서 섹터 데이터를 파싱한다."""
        # 네이버 금융 섹터 페이지를 모사하는 최소 HTML
        html = """
        <table class="type_1">
          <tr>
            <td><a href="/sise/sise_group_detail.naver?type=upjong&no=261">반도체</a></td>
            <td>+2.50%</td>
            <td>30</td><td>20</td><td>5</td><td>5</td>
            <td>기타</td>
          </tr>
        </table>
        """.encode("euc-kr")

        mock_resp = MagicMock()
        mock_resp.content = html
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await fetch_sector_performances(force=True)

        assert "261" in result
        assert result["261"].name == "반도체"
        assert result["261"].change_rate == pytest.approx(2.5)
        assert result["261"].rising_stocks == 20

    @pytest.mark.asyncio
    async def test_returns_cached_data_when_available(self) -> None:
        """캐시에 데이터가 있으면 HTTP 요청 없이 반환한다."""
        _cache.data = {"100": SectorPerformance(
            naver_code="100", name="테스트", change_rate=1.0,
            total_stocks=10, rising_stocks=5, flat_stocks=3, falling_stocks=2,
        )}
        _cache.last_updated = time.time()

        result = await fetch_sector_performances(force=False)
        assert "100" in result

    @pytest.mark.asyncio
    @patch("app.services.naver_finance.httpx.AsyncClient")
    async def test_returns_stale_cache_on_error(self, mock_client_cls) -> None:
        """HTTP 에러 시 기존 캐시를 반환한다."""
        _cache.data = {"100": SectorPerformance(
            naver_code="100", name="캐시", change_rate=0.5,
            total_stocks=5, rising_stocks=2, flat_stocks=2, falling_stocks=1,
        )}

        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.HTTPError("네트워크 에러")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await fetch_sector_performances(force=True)
        assert "100" in result
        assert result["100"].name == "캐시"


# ---------------------------------------------------------------------------
# fetch_stock_fundamentals 테스트
# ---------------------------------------------------------------------------


class TestFetchStockFundamentals:
    """종목 기본 정보 조회 테스트."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        _fundamentals_cache.data.clear()
        _fundamentals_cache.last_updated.clear()
        yield
        _fundamentals_cache.data.clear()
        _fundamentals_cache.last_updated.clear()

    @pytest.mark.asyncio
    @patch("app.services.naver_finance.httpx.AsyncClient")
    async def test_parses_polling_api_json(self, mock_client_cls) -> None:
        """Naver polling API JSON 응답을 파싱한다."""
        api_response = {
            "result": {
                "areas": [{
                    "datas": [{
                        "nv": "50000",
                        "cv": "1000",
                        "cr": "2.04",
                        "eps": "3000",
                        "bps": "40000",
                        "dv": "500",
                        "aq": "1000000",
                        "aa": "50000000",
                    }]
                }]
            }
        }
        encoded = json.dumps(api_response).encode("euc-kr")

        mock_resp = MagicMock()
        mock_resp.content = encoded
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await fetch_stock_fundamentals("005930")

        assert result is not None
        assert result.current_price == 50000
        assert result.price_change == 1000
        assert result.change_rate == pytest.approx(2.04)
        assert result.eps == 3000

    @pytest.mark.asyncio
    @patch("app.services.naver_finance.httpx.AsyncClient")
    async def test_returns_none_on_empty_areas(self, mock_client_cls) -> None:
        """응답에 데이터가 없으면 None/캐시를 반환한다."""
        api_response = {"result": {"areas": []}}
        encoded = json.dumps(api_response).encode("euc-kr")

        mock_resp = MagicMock()
        mock_resp.content = encoded
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await fetch_stock_fundamentals("999999")
        assert result is None

    @pytest.mark.asyncio
    @patch("app.services.naver_finance.httpx.AsyncClient")
    async def test_returns_cache_on_http_error(self, mock_client_cls) -> None:
        """HTTP 에러 시 캐시 데이터를 반환한다."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.HTTPError("timeout")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await fetch_stock_fundamentals("005930")
        # 캐시가 비어있으므로 None 반환
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_hit_skips_http_call(self) -> None:
        """캐시 TTL 내에서는 HTTP 호출을 생략한다."""
        from app.services.naver_finance import StockFundamentals

        cached = StockFundamentals(stock_code="005930", current_price=60000)
        _fundamentals_cache.data["005930"] = cached
        _fundamentals_cache.last_updated["005930"] = time.time()

        result = await fetch_stock_fundamentals("005930")
        assert result is not None
        assert result.current_price == 60000


# ---------------------------------------------------------------------------
# fetch_stock_price_history 테스트
# ---------------------------------------------------------------------------


class TestFetchStockPriceHistory:
    """주가 히스토리 스크래핑 테스트."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        _price_cache.data.clear()
        _price_cache.last_updated.clear()
        yield
        _price_cache.data.clear()
        _price_cache.last_updated.clear()

    @pytest.mark.asyncio
    @patch("app.services.naver_finance.httpx.AsyncClient")
    async def test_parses_sise_day_html(self, mock_client_cls) -> None:
        """sise_day.naver HTML에서 OHLCV를 파싱한다."""
        html = """
        <table class="type2">
          <tr>
            <td>2026.03.28</td>
            <td>50,000</td>
            <td>1,000</td>
            <td>49,500</td>
            <td>50,500</td>
            <td>49,000</td>
            <td>1,234,567</td>
          </tr>
        </table>
        """.encode("euc-kr")

        mock_resp = MagicMock()
        mock_resp.content = html
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await fetch_stock_price_history("005930", pages=1)

        assert len(result) == 1
        assert result[0].date == "2026.03.28"
        assert result[0].close == 50000
        assert result[0].volume == 1234567

    @pytest.mark.asyncio
    @patch("app.services.naver_finance.httpx.AsyncClient")
    async def test_returns_empty_on_error(self, mock_client_cls) -> None:
        """HTTP 에러 시 빈 리스트를 반환한다."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.HTTPError("connection error")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await fetch_stock_price_history("005930", pages=1)
        assert result == []


# ---------------------------------------------------------------------------
# fetch_naver_stock_list 테스트
# ---------------------------------------------------------------------------


class TestFetchNaverStockList:
    """네이버 모바일 API 종목 리스트 테스트."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        _naver_stock_list_cache.data.clear()
        _naver_stock_list_cache.last_updated.clear()
        yield
        _naver_stock_list_cache.data.clear()
        _naver_stock_list_cache.last_updated.clear()

    @pytest.mark.asyncio
    @patch("app.services.naver_finance.httpx.AsyncClient")
    async def test_parses_mobile_api_json(self, mock_client_cls) -> None:
        """모바일 API JSON 응답을 파싱한다."""
        api_data = {
            "totalCount": 100,
            "stocks": [
                {
                    "itemCode": "005930",
                    "stockName": "삼성전자",
                    "closePrice": "60,000",
                    "compareToPreviousClosePrice": "-1,000",
                    "fluctuationsRatio": -1.64,
                    "marketValue": "3,580,000",
                    "accumulatedTradingVolume": "10,000,000",
                    "accumulatedTradingValue": "600,000",
                    "compareToPreviousPrice": {"name": "FALLING"},
                },
            ],
        }

        mock_resp = MagicMock()
        mock_resp.json.return_value = api_data
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        items, total = await fetch_naver_stock_list("KOSPI", page=1, page_size=50)

        assert total == 100
        assert len(items) == 1
        assert items[0].stock_code == "005930"
        assert items[0].name == "삼성전자"
        assert items[0].current_price == 60000
        assert items[0].change_rate < 0  # FALLING이므로 음수

    @pytest.mark.asyncio
    @patch("app.services.naver_finance.httpx.AsyncClient")
    async def test_returns_empty_on_api_error(self, mock_client_cls) -> None:
        """API 에러 시 빈 리스트를 반환한다."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.HTTPError("timeout")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        items, total = await fetch_naver_stock_list()
        assert items == []
        assert total == 0


# ---------------------------------------------------------------------------
# fetch_sector_stock_codes 테스트
# ---------------------------------------------------------------------------


class TestFetchSectorStockCodes:
    """섹터 구성 종목 코드 스크래핑 테스트."""

    @pytest.mark.asyncio
    @patch("app.services.naver_finance.httpx.AsyncClient")
    async def test_extracts_stock_codes_from_html(self, mock_client_cls) -> None:
        """섹터 상세 페이지에서 종목 코드를 추출한다."""
        html = """
        <a href="/item/main.naver?code=005930">삼성전자</a>
        <a href="/item/main.naver?code=000660">SK하이닉스</a>
        <a href="/other/page.naver?code=notstock">기타</a>
        """.encode("euc-kr")

        mock_resp = MagicMock()
        mock_resp.content = html
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        codes = await fetch_sector_stock_codes("261")
        assert "005930" in codes
        assert "000660" in codes

    @pytest.mark.asyncio
    @patch("app.services.naver_finance.httpx.AsyncClient")
    async def test_returns_empty_on_error(self, mock_client_cls) -> None:
        """에러 시 빈 리스트를 반환한다."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("error")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        codes = await fetch_sector_stock_codes("261")
        assert codes == []


# ---------------------------------------------------------------------------
# fetch_investor_trading 테스트
# ---------------------------------------------------------------------------


class TestFetchInvestorTrading:
    """투자자별 매매동향 테스트."""

    @pytest.mark.asyncio
    @patch("app.services.naver_finance.httpx.AsyncClient")
    async def test_parses_investor_trading_html(self, mock_client_cls) -> None:
        """투자자 매매동향 테이블을 파싱한다."""
        html = """
        <table class="type2">
          <tr>
            <td>2026.03.28</td>
            <td>50,000</td>
            <td>+1,000</td>
            <td>500,000</td>
            <td>+10,000</td>
            <td>-5,000</td>
          </tr>
        </table>
        """
        mock_resp = MagicMock()
        mock_resp.text = html
        mock_resp.status_code = 200

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await fetch_investor_trading("005930", days=5)
        assert len(result) >= 1
        assert result[0].date == "2026.03.28"
        assert result[0].institution_net == 10000
        assert result[0].foreign_net == -5000

    @pytest.mark.asyncio
    @patch("app.services.naver_finance.httpx.AsyncClient")
    async def test_returns_empty_on_non_200(self, mock_client_cls) -> None:
        """200이 아닌 응답 시 빈 리스트를 반환한다."""
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await fetch_investor_trading("005930")
        assert result == []

    @pytest.mark.asyncio
    @patch("app.services.naver_finance.httpx.AsyncClient")
    async def test_returns_empty_on_exception(self, mock_client_cls) -> None:
        """예외 발생 시 빈 리스트를 반환한다."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("network error")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await fetch_investor_trading("005930")
        assert result == []


# ---------------------------------------------------------------------------
# fetch_stock_fundamentals_batch 테스트
# ---------------------------------------------------------------------------


class TestFetchStockFundamentalsBatch:
    """배치 기본 정보 조회 테스트."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        _fundamentals_cache.data.clear()
        _fundamentals_cache.last_updated.clear()
        yield
        _fundamentals_cache.data.clear()
        _fundamentals_cache.last_updated.clear()

    @pytest.mark.asyncio
    @patch("app.services.naver_finance.httpx.AsyncClient")
    @patch("app.services.naver_finance._fetch_fundamentals_mobile", new_callable=AsyncMock)
    async def test_batch_fetches_multiple_stocks(
        self, mock_mobile, mock_client_cls
    ) -> None:
        """여러 종목을 배치로 조회한다."""
        api_response = {
            "result": {
                "areas": [{
                    "datas": [
                        {"cd": "005930", "nv": "60000", "cv": "500", "cr": "0.84",
                         "eps": "3000", "bps": "40000", "dv": "500", "aq": "1000000", "aa": "60000000"},
                    ]
                }]
            }
        }
        encoded = json.dumps(api_response).encode("euc-kr")

        mock_resp = MagicMock()
        mock_resp.content = encoded
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client
        mock_mobile.return_value = None  # 모바일 fallback은 None 반환

        result = await fetch_stock_fundamentals_batch(["005930"])

        assert "005930" in result
        assert result["005930"].current_price == 60000
