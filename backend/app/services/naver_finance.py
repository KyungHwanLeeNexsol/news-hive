"""Naver Finance scraper with in-memory caching.

Sector performance: scrapes sise_group.naver for ~80 sectors.
Stock fundamentals: polling.finance.naver.com realtime JSON API.
Price history: sise_day.naver daily OHLCV scraping.
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

SECTOR_LIST_URL = "https://finance.naver.com/sise/sise_group.naver?type=upjong"
SECTOR_DETAIL_URL = "https://finance.naver.com/sise/sise_group_detail.naver?type=upjong&no={code}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

CACHE_TTL_SECONDS = 300  # 5 minutes


@dataclass
class SectorPerformance:
    """Live performance data for a single sector."""
    naver_code: str
    name: str
    change_rate: float          # 전일대비 등락률 (%)
    total_stocks: int           # 전체 종목 수
    rising_stocks: int          # 상승
    flat_stocks: int            # 보합
    falling_stocks: int         # 하락


@dataclass
class _SectorCache:
    """In-memory cache for sector performance data."""
    data: dict[str, SectorPerformance] = field(default_factory=dict)
    last_updated: float = 0.0


_cache = _SectorCache()


def _extract_code(href: str) -> Optional[str]:
    """Extract 'no' parameter from a Naver Finance URL."""
    if "no=" in href:
        return href.split("no=")[-1].split("&")[0].strip()
    return None


def _parse_change_rate(text: str) -> float:
    """Parse change rate text like '+8.02%' or '-1.23%' to float."""
    cleaned = text.replace("%", "").replace(",", "").strip()
    # Handle cases where + is missing for positive values
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _parse_int_safe(text: str) -> int:
    """Parse integer from text, returning 0 on failure."""
    try:
        return int(text.replace(",", "").strip())
    except (ValueError, AttributeError):
        return 0


async def fetch_sector_performances(force: bool = False) -> dict[str, SectorPerformance]:
    """Fetch all sector performance data from Naver Finance.

    Returns dict keyed by naver_code. Uses in-memory cache with 5 min TTL.
    Non-forced calls always return cached data immediately (even if stale)
    — the scheduler refreshes the cache every 5 minutes in the background.
    Only blocks when force=True (scheduler) or on first call with empty cache.
    """
    now = time.time()
    cache_fresh = (now - _cache.last_updated) < CACHE_TTL_SECONDS

    if not force:
        if _cache.data:
            return _cache.data
        if cache_fresh:
            return _cache.data

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(SECTOR_LIST_URL, headers=HEADERS)
            resp.raise_for_status()

        # Naver Finance uses euc-kr encoding
        content = resp.content.decode("euc-kr", errors="replace")
        soup = BeautifulSoup(content, "html.parser")

        # Find the sector table — Naver uses table.type_1
        table = soup.select_one("table.type_1")
        if not table:
            logger.warning("Could not find sector table on Naver Finance page")
            return _cache.data

        results: dict[str, SectorPerformance] = {}
        for row in table.select("tr"):
            cols = row.select("td")
            if len(cols) < 7:
                continue

            # Column 0: sector name with link
            link = cols[0].select_one("a")
            if not link:
                continue
            name = link.get_text(strip=True)
            href = link.get("href", "")
            code = _extract_code(href)
            if not code or not name:
                continue

            # Column 1: 전일대비 (change rate %)
            change_rate = _parse_change_rate(cols[1].get_text(strip=True))

            # Columns 2-5: 등락현황 (전체, 상승, 보합, 하락)
            total = _parse_int_safe(cols[2].get_text())
            rising = _parse_int_safe(cols[3].get_text())
            flat = _parse_int_safe(cols[4].get_text())
            falling = _parse_int_safe(cols[5].get_text())

            results[code] = SectorPerformance(
                naver_code=code,
                name=name,
                change_rate=change_rate,
                total_stocks=total,
                rising_stocks=rising,
                flat_stocks=flat,
                falling_stocks=falling,
            )

        if results:
            _cache.data = results
            _cache.last_updated = now
            logger.info(f"Fetched performance data for {len(results)} sectors from Naver Finance")

        return results if results else _cache.data

    except Exception as e:
        logger.error(f"Failed to fetch Naver sector data: {e}")
        return _cache.data  # graceful fallback to stale cache


async def fetch_all_naver_sectors() -> list[dict]:
    """Fetch all sector names and codes from Naver (for seeding).

    Returns list of {"name": str, "code": str}.
    """
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(SECTOR_LIST_URL, headers=HEADERS)
            resp.raise_for_status()

        content = resp.content.decode("euc-kr", errors="replace")
        soup = BeautifulSoup(content, "html.parser")

        table = soup.select_one("table.type_1")
        if not table:
            return []

        sectors = []
        for row in table.select("tr"):
            link = row.select_one("td a")
            if not link:
                continue
            name = link.get_text(strip=True)
            href = link.get("href", "")
            code = _extract_code(href)
            if name and code:
                sectors.append({"name": name, "code": code})

        logger.info(f"Found {len(sectors)} sectors from Naver Finance")
        return sectors

    except Exception as e:
        logger.error(f"Failed to fetch Naver sector list: {e}")
        return []


@dataclass
class StockPerformance:
    """Live performance data for a single stock within a sector."""
    stock_code: str
    name: str
    current_price: int = 0          # 현재가
    price_change: int = 0           # 전일비 (signed)
    change_rate: float = 0.0        # 등락률 (%)
    bid_price: int = 0              # 매수호가
    ask_price: int = 0              # 매도호가
    volume: int = 0                 # 거래량
    trading_value: int = 0          # 거래대금 (백만)
    prev_volume: int = 0            # 전일거래량


@dataclass
class _StockPerfCache:
    """In-memory cache for stock-level performance data, keyed by naver_code."""
    data: dict[str, list[StockPerformance]] = field(default_factory=dict)
    last_updated: dict[str, float] = field(default_factory=dict)


_stock_perf_cache = _StockPerfCache()


async def fetch_sector_stock_performances(naver_code: str) -> list[StockPerformance]:
    """Fetch stock-level performance data from a Naver sector detail page.

    Scrapes the sector detail page to get each stock's name, code, and change rate.
    Uses in-memory cache with 5 min TTL.
    """
    now = time.time()
    if (naver_code in _stock_perf_cache.data
            and (now - _stock_perf_cache.last_updated.get(naver_code, 0)) < CACHE_TTL_SECONDS):
        return _stock_perf_cache.data[naver_code]

    url = SECTOR_DETAIL_URL.format(code=naver_code)
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=HEADERS)
            resp.raise_for_status()

        content = resp.content.decode("euc-kr", errors="replace")
        soup = BeautifulSoup(content, "html.parser")

        results: list[StockPerformance] = []
        # The detail page has a table with stock rows
        # Columns: 종목명(0) 현재가(1) 전일비(2) 등락률(3) 매수호가(4) 매도호가(5) 거래량(6) 거래대금(7) 전일거래량(8) [기타(9)]
        for table in soup.select("table.type_5"):
            for row in table.select("tr"):
                cols = row.select("td")
                if len(cols) < 9:
                    continue

                # Column 0: stock name with link containing code
                link = cols[0].select_one("a[href*='code=']")
                if not link:
                    continue

                name = link.get_text(strip=True)
                href = link.get("href", "")
                code = href.split("code=")[-1].split("&")[0].strip()
                if not code or len(code) != 6 or not code.isdigit():
                    continue

                # Column 1: 현재가
                current_price = _parse_int_safe(cols[1].get_text())

                # Column 2: 전일비 (contains direction prefix + number, e.g. "상승130")
                change_text = re.sub(r"[^\d]", "", cols[2].get_text())
                change_abs = int(change_text) if change_text else 0

                # Column 3: 등락률
                change_rate = _parse_change_rate(cols[3].get_text(strip=True))

                # Apply sign to 전일비 based on 등락률 direction
                if change_rate < 0:
                    change_abs = -change_abs

                # Columns 4-8
                bid_price = _parse_int_safe(cols[4].get_text())
                ask_price = _parse_int_safe(cols[5].get_text())
                volume = _parse_int_safe(cols[6].get_text())
                trading_value = _parse_int_safe(cols[7].get_text())
                prev_volume = _parse_int_safe(cols[8].get_text())

                results.append(StockPerformance(
                    stock_code=code,
                    name=name,
                    current_price=current_price,
                    price_change=change_abs,
                    change_rate=change_rate,
                    bid_price=bid_price,
                    ask_price=ask_price,
                    volume=volume,
                    trading_value=trading_value,
                    prev_volume=prev_volume,
                ))

        if results:
            _stock_perf_cache.data[naver_code] = results
            _stock_perf_cache.last_updated[naver_code] = now
            logger.info(f"Fetched performance data for {len(results)} stocks in sector {naver_code}")

        return results

    except Exception as e:
        logger.error(f"Failed to fetch stock performances for sector {naver_code}: {e}")
        return _stock_perf_cache.data.get(naver_code, [])


POLLING_API_URL = "https://polling.finance.naver.com/api/realtime?query=SERVICE_ITEM:{code}"
SISE_DAY_URL = "https://finance.naver.com/item/sise_day.naver?code={code}&page={page}"
PRICE_CACHE_TTL = 3600  # 1 hour for daily price data


@dataclass
class StockFundamentals:
    """Realtime fundamentals from Naver polling API."""
    stock_code: str
    current_price: int = 0
    price_change: int = 0
    change_rate: float = 0.0
    eps: int = 0                    # 주당순이익
    bps: int = 0                    # 주당순자산
    dividend: int = 0               # 주당배당금
    high_52w: int = 0               # 52주 최고
    low_52w: int = 0                # 52주 최저
    volume: int = 0                 # 거래량
    trading_value: int = 0          # 거래대금 (백만)


@dataclass
class _FundamentalsCache:
    data: dict[str, StockFundamentals] = field(default_factory=dict)
    last_updated: dict[str, float] = field(default_factory=dict)


_fundamentals_cache = _FundamentalsCache()


async def fetch_stock_fundamentals(stock_code: str) -> Optional[StockFundamentals]:
    """Fetch realtime stock fundamentals from Naver polling API (JSON).

    Returns StockFundamentals or None on failure. 5-min cache per stock.
    """
    now = time.time()
    if (stock_code in _fundamentals_cache.data
            and (now - _fundamentals_cache.last_updated.get(stock_code, 0)) < CACHE_TTL_SECONDS):
        return _fundamentals_cache.data[stock_code]

    url = POLLING_API_URL.format(code=stock_code)
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(url, headers=HEADERS)
            resp.raise_for_status()

        # Response is EUC-KR encoded — decode before JSON parsing
        text = resp.content.decode("euc-kr", errors="replace")
        data = json.loads(text)

        # Navigate: result → areas[0] → datas[0]
        areas = data.get("result", {}).get("areas", [])
        if not areas or not areas[0].get("datas"):
            return _fundamentals_cache.data.get(stock_code)

        item = areas[0]["datas"][0]

        def _int(key: str) -> int:
            try:
                return int(float(item.get(key, 0) or 0))
            except (ValueError, TypeError):
                return 0

        def _float(key: str) -> float:
            try:
                return float(item.get(key, 0) or 0)
            except (ValueError, TypeError):
                return 0.0

        # Note: ul=상한가(upper limit), ll=하한가(lower limit), NOT 52-week high/low
        # hv=당일고가, lv=당일저가, ov=시가, pcv=전일종가
        result = StockFundamentals(
            stock_code=stock_code,
            current_price=_int("nv"),
            price_change=_int("cv"),
            change_rate=_float("cr"),
            eps=_int("eps"),
            bps=_int("bps"),
            dividend=_int("dv"),
            high_52w=0,   # Not available from polling API
            low_52w=0,    # Not available from polling API
            volume=_int("aq"),
            trading_value=_int("aa"),
        )

        _fundamentals_cache.data[stock_code] = result
        _fundamentals_cache.last_updated[stock_code] = now
        return result

    except Exception as e:
        logger.error(f"Failed to fetch fundamentals for {stock_code}: {e}")
        return _fundamentals_cache.data.get(stock_code)


@dataclass
class PriceRecord:
    """Daily OHLCV price record."""
    date: str           # "2026.02.26"
    close: int = 0
    open: int = 0
    high: int = 0
    low: int = 0
    volume: int = 0


@dataclass
class _PriceHistoryCache:
    data: dict[str, list[PriceRecord]] = field(default_factory=dict)
    last_updated: dict[str, float] = field(default_factory=dict)


_price_cache = _PriceHistoryCache()


async def fetch_stock_price_history(stock_code: str, pages: int = 5) -> list[PriceRecord]:
    """Fetch daily OHLCV from Naver sise_day.naver (euc-kr HTML).

    pages=5 → ~50 trading days (~2.5 months). Cache TTL = 1 hour.
    """
    now = time.time()
    if (stock_code in _price_cache.data
            and (now - _price_cache.last_updated.get(stock_code, 0)) < PRICE_CACHE_TTL):
        return _price_cache.data[stock_code]

    results: list[PriceRecord] = []
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            for pg in range(1, pages + 1):
                url = SISE_DAY_URL.format(code=stock_code, page=pg)
                resp = await client.get(url, headers=HEADERS)
                resp.raise_for_status()

                content = resp.content.decode("euc-kr", errors="replace")
                soup = BeautifulSoup(content, "html.parser")

                for row in soup.select("table.type2 tr"):
                    cols = row.select("td")
                    if len(cols) < 7:
                        continue
                    date_text = cols[0].get_text(strip=True)
                    if not date_text or "." not in date_text:
                        continue

                    close = _parse_int_safe(cols[1].get_text())
                    # cols[2] = 전일비 (skip, redundant)
                    open_price = _parse_int_safe(cols[3].get_text())
                    high = _parse_int_safe(cols[4].get_text())
                    low = _parse_int_safe(cols[5].get_text())
                    volume = _parse_int_safe(cols[6].get_text())

                    if close > 0:
                        results.append(PriceRecord(
                            date=date_text,
                            close=close,
                            open=open_price,
                            high=high,
                            low=low,
                            volume=volume,
                        ))

        if results:
            _price_cache.data[stock_code] = results
            _price_cache.last_updated[stock_code] = now
            logger.info(f"Fetched {len(results)} daily prices for {stock_code}")

        return results

    except Exception as e:
        logger.error(f"Failed to fetch price history for {stock_code}: {e}")
        return _price_cache.data.get(stock_code, [])


async def fetch_sector_stock_codes(naver_code: str) -> list[str]:
    """Fetch stock codes belonging to a Naver sector (for stock-to-sector mapping).

    Scrapes the sector detail page to get constituent stock codes.
    """
    url = SECTOR_DETAIL_URL.format(code=naver_code)
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=HEADERS)
            resp.raise_for_status()

        content = resp.content.decode("euc-kr", errors="replace")
        soup = BeautifulSoup(content, "html.parser")

        stock_codes = []
        # Stock links: /item/main.naver?code=XXXXXX or /item/main.nhn?code=XXXXXX
        for link in soup.select("a[href*='code=']"):
            href = link.get("href", "")
            if "/item/" not in href:
                continue
            code = href.split("code=")[-1].split("&")[0].strip()
            if code and len(code) == 6 and code.isdigit():
                stock_codes.append(code)

        return list(set(stock_codes))  # deduplicate

    except Exception as e:
        logger.error(f"Failed to fetch stocks for Naver sector {naver_code}: {e}")
        return []
