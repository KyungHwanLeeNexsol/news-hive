"""벤치마크/알파 헬퍼 단위 테스트."""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.services import benchmark


@pytest.fixture(autouse=True)
def _clear_cache():
    benchmark.clear_cache()
    yield
    benchmark.clear_cache()


SAMPLE_ROWS = [
    {"date": "2026.04.09", "close": 5778.01},
    {"date": "2026.04.08", "close": 5872.34},
    {"date": "2026.04.07", "close": 5494.78},
    {"date": "2026.04.06", "close": 5450.33},
    {"date": "2026.04.03", "close": 5377.30},
    {"date": "2026.04.02", "close": 5234.05},
    {"date": "2026.04.01", "close": 5478.70},
    {"date": "2026.03.31", "close": 5450.10},
]


@pytest.mark.asyncio
async def test_get_kospi_close_정확한_날짜():
    with patch(
        "app.services.naver_finance.fetch_index_price_history",
        new_callable=AsyncMock,
        return_value=SAMPLE_ROWS,
    ):
        close = await benchmark.get_kospi_close(date(2026, 4, 9))
    assert close == 5778.01


@pytest.mark.asyncio
async def test_get_kospi_close_휴일_직전영업일_폴백():
    """2026-04-05(토)는 거래일 아님 → 직전 2026-04-03 종가로 폴백."""
    with patch(
        "app.services.naver_finance.fetch_index_price_history",
        new_callable=AsyncMock,
        return_value=SAMPLE_ROWS,
    ):
        close = await benchmark.get_kospi_close(date(2026, 4, 5))
    assert close == 5377.30


@pytest.mark.asyncio
async def test_get_kospi_cumulative_return_기간수익률():
    """04-02(5234.05) → 04-09(5778.01) → 약 +10.39%."""
    with patch(
        "app.services.naver_finance.fetch_index_price_history",
        new_callable=AsyncMock,
        return_value=SAMPLE_ROWS,
    ):
        ret = await benchmark.get_kospi_cumulative_return(date(2026, 4, 2), date(2026, 4, 9))
    assert ret is not None
    assert round(ret, 2) == 10.39


@pytest.mark.asyncio
async def test_get_kospi_cumulative_return_역순_None():
    with patch(
        "app.services.naver_finance.fetch_index_price_history",
        new_callable=AsyncMock,
        return_value=SAMPLE_ROWS,
    ):
        ret = await benchmark.get_kospi_cumulative_return(date(2026, 4, 9), date(2026, 4, 2))
    assert ret is None


@pytest.mark.asyncio
async def test_get_kospi_cumulative_return_데이터없음():
    with patch(
        "app.services.naver_finance.fetch_index_price_history",
        new_callable=AsyncMock,
        return_value=[],
    ):
        ret = await benchmark.get_kospi_cumulative_return(date(2026, 4, 2), date(2026, 4, 9))
    assert ret is None


@pytest.mark.asyncio
async def test_get_kospi_period_return_datetime_UTC():
    """UTC datetime을 KST 날짜로 변환해 기간 수익률을 산정해야 한다."""
    from_dt = datetime(2026, 4, 2, 0, 0, tzinfo=timezone.utc)  # KST 04-02 09:00
    to_dt = datetime(2026, 4, 9, 5, 0, tzinfo=timezone.utc)    # KST 04-09 14:00
    with patch(
        "app.services.naver_finance.fetch_index_price_history",
        new_callable=AsyncMock,
        return_value=SAMPLE_ROWS,
    ):
        ret = await benchmark.get_kospi_period_return(from_dt, to_dt)
    assert ret is not None
    assert round(ret, 2) == 10.39


@pytest.mark.asyncio
async def test_메모리캐시_30분_TTL():
    """같은 pages 인자로 연속 호출 시 두 번째는 네트워크 호출 없이 캐시 반환."""
    mock = AsyncMock(return_value=SAMPLE_ROWS)
    with patch("app.services.naver_finance.fetch_index_price_history", mock):
        r1 = await benchmark.get_kospi_close(date(2026, 4, 9))
        r2 = await benchmark.get_kospi_close(date(2026, 4, 8))
    assert r1 == 5778.01
    assert r2 == 5872.34
    assert mock.call_count == 1  # 캐시 적중
