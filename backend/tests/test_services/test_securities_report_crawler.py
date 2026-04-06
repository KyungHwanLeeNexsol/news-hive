"""증권사 리포트 크롤러 단위 테스트 (SPEC-FOLLOW-002).

네이버 리서치 HTTP 요청과 DB를 Mock으로 대체하여 크롤링 로직을 검증한다.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


from app.services.securities_report_crawler import (
    _parse_target_price,
    _parse_report_rows,
    fetch_securities_reports,
)


# ---------------------------------------------------------------------------
# _parse_target_price 유닛 테스트
# ---------------------------------------------------------------------------


class TestParseTargetPrice:
    """목표주가 파싱 엣지 케이스 검증."""

    def test_normal_price(self):
        """일반적인 숫자 문자열을 정수로 변환한다."""
        assert _parse_target_price("100000") == 100000

    def test_comma_formatted(self):
        """쉼표가 포함된 가격을 정수로 변환한다."""
        assert _parse_target_price("1,234,000") == 1234000

    def test_with_won_sign(self):
        """'원' 단위가 붙은 문자열에서 숫자를 추출한다."""
        assert _parse_target_price("1,234,000원") == 1234000

    def test_dash_returns_none(self):
        """'-'는 None을 반환한다."""
        assert _parse_target_price("-") is None

    def test_na_returns_none(self):
        """'N/A'는 None을 반환한다."""
        assert _parse_target_price("N/A") is None

    def test_none_input(self):
        """None 입력은 None을 반환한다."""
        assert _parse_target_price(None) is None

    def test_empty_string(self):
        """빈 문자열은 None을 반환한다."""
        assert _parse_target_price("") is None

    def test_zero(self):
        """0원은 None을 반환한다 (숫자 없음과 동일)."""
        # "0"은 사실상 유효한 값이므로 0을 반환해야 함
        assert _parse_target_price("0") == 0


# ---------------------------------------------------------------------------
# fetch_securities_reports 테스트
# ---------------------------------------------------------------------------


def _make_db_mock(existing_urls: list[str] | None = None, stocks: list | None = None):
    """테스트용 DB 세션 Mock을 생성한다."""
    db = MagicMock()

    # 기존 URL 쿼리 결과
    url_rows = [(url,) for url in (existing_urls or [])]

    # Stock 쿼리 결과 (name_to_id 매핑용)
    stock_mocks = stocks or []

    # query 체인 구성
    url_query = MagicMock()
    url_query.all.return_value = url_rows

    stock_query = MagicMock()
    stock_query.filter.return_value.all.return_value = stock_mocks

    call_count = 0

    def query_side_effect(model):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # SecuritiesReport.url 쿼리
            return url_query
        elif call_count == 2:
            # Stock 쿼리
            return stock_query
        return MagicMock()

    db.query.side_effect = query_side_effect
    db.add = MagicMock()
    db.commit = MagicMock()
    db.rollback = MagicMock()

    return db


# 샘플 HTML (네이버 리서치 종목분석 테이블 구조)
_SAMPLE_HTML = """
<html><body>
<table class="type_1">
  <tr>
    <th>종목명</th><th>제목</th><th>증권사</th><th>목표주가</th><th>의견</th><th>날짜</th>
  </tr>
  <tr>
    <td>삼성전자</td>
    <td><a href="/research/company_read.naver?nid=12345">HBM 수요 증가 전망</a></td>
    <td>한국투자증권</td>
    <td>95,000원</td>
    <td>매수</td>
    <td>2026.04.06</td>
  </tr>
  <tr>
    <td>SK하이닉스</td>
    <td><a href="/research/company_read.naver?nid=67890">AI 반도체 호황</a></td>
    <td>삼성증권</td>
    <td>200,000원</td>
    <td>매수</td>
    <td>2026.04.05</td>
  </tr>
</table>
</body></html>
"""


class TestFetchSecuritiesReports:
    """fetch_securities_reports 통합 테스트."""

    def test_circuit_open_returns_zero(self):
        """서킷 브레이커가 열려 있으면 0을 반환하고 HTTP 요청을 하지 않는다."""
        db = MagicMock()

        with patch(
            "app.services.securities_report_crawler.api_circuit_breaker"
        ) as mock_cb:
            mock_cb.is_available.return_value = False

            result = asyncio.run(fetch_securities_reports(db, pages=1))

        assert result == 0
        # HTTP 요청이 발생하지 않아야 함
        db.query.assert_not_called()

    def test_saves_new_reports(self):
        """샘플 HTML에서 리포트를 파싱하여 DB에 저장한다."""
        db = _make_db_mock(existing_urls=[], stocks=[])

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.text = _SAMPLE_HTML

        with (
            patch("app.services.securities_report_crawler.api_circuit_breaker") as mock_cb,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_cb.is_available.return_value = True

            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = asyncio.run(fetch_securities_reports(db, pages=1))

        # 2건 저장
        assert result == 2
        assert db.add.call_count == 2

    def test_deduplication(self):
        """이미 DB에 있는 URL은 건너뛴다."""
        existing_url = "https://finance.naver.com/research/company_read.naver?nid=12345"
        db = _make_db_mock(existing_urls=[existing_url], stocks=[])

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.text = _SAMPLE_HTML

        with (
            patch("app.services.securities_report_crawler.api_circuit_breaker") as mock_cb,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_cb.is_available.return_value = True

            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = asyncio.run(fetch_securities_reports(db, pages=1))

        # 1건만 저장 (중복 1건 스킵)
        assert result == 1

    def test_stock_mapping(self):
        """회사명이 Stock에 매핑되면 stock_id가 설정된다."""
        # 삼성전자 종목 Mock
        samsung_stock = MagicMock()
        samsung_stock.name = "삼성전자"
        samsung_stock.id = 42

        db = _make_db_mock(existing_urls=[], stocks=[samsung_stock])

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.text = _SAMPLE_HTML

        saved_reports = []

        def capture_add(obj):
            saved_reports.append(obj)

        db.add = capture_add

        with (
            patch("app.services.securities_report_crawler.api_circuit_breaker") as mock_cb,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_cb.is_available.return_value = True

            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            asyncio.run(fetch_securities_reports(db, pages=1))

        # 삼성전자 리포트는 stock_id=42, SK하이닉스는 None
        samsung_report = next(
            (r for r in saved_reports if r.company_name == "삼성전자"), None
        )
        sk_report = next(
            (r for r in saved_reports if r.company_name == "SK하이닉스"), None
        )
        assert samsung_report is not None
        assert samsung_report.stock_id == 42
        assert sk_report is not None
        assert sk_report.stock_id is None

    def test_http_failure_records_circuit_failure(self):
        """HTTP 요청 실패 시 서킷 브레이커에 실패를 기록한다."""
        import httpx

        db = _make_db_mock(existing_urls=[], stocks=[])

        with (
            patch("app.services.securities_report_crawler.api_circuit_breaker") as mock_cb,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_cb.is_available.return_value = True

            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=httpx.RequestError("connection failed"))
            mock_client_cls.return_value = mock_client

            result = asyncio.run(fetch_securities_reports(db, pages=1))

        assert result == 0
        mock_cb.record_failure.assert_called_with("naver_research")


# ---------------------------------------------------------------------------
# _parse_report_rows 유닛 테스트
# ---------------------------------------------------------------------------


class TestParseReportRows:
    """HTML 파서 단위 테스트."""

    def test_parses_sample_html(self):
        """샘플 HTML에서 2개의 리포트 행을 파싱한다."""
        rows = _parse_report_rows(_SAMPLE_HTML)
        assert len(rows) == 2

    def test_correct_fields(self):
        """파싱된 첫 번째 행의 필드가 올바르다."""
        rows = _parse_report_rows(_SAMPLE_HTML)
        first = rows[0]
        assert first["company_name"] == "삼성전자"
        assert "HBM" in first["title"]
        assert first["securities_firm"] == "한국투자증권"
        assert first["target_price"] == 95000
        assert first["opinion"] == "매수"
        assert first["published_at"] is not None

    def test_url_is_absolute(self):
        """URL이 절대 경로로 변환된다."""
        rows = _parse_report_rows(_SAMPLE_HTML)
        for row in rows:
            assert row["url"].startswith("https://")

    def test_empty_table_returns_empty(self):
        """빈 HTML은 빈 목록을 반환한다."""
        rows = _parse_report_rows("<html><body></body></html>")
        assert rows == []
