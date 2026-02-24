"""Naver Finance sector scraper with in-memory caching.

Scrapes https://finance.naver.com/sise/sise_group.naver?type=upjong
to get ~80 sector performance data (등락률, 상승/보합/하락 counts).
"""

import logging
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
    On failure, returns stale cached data (graceful degradation).
    """
    now = time.time()
    if not force and _cache.data and (now - _cache.last_updated) < CACHE_TTL_SECONDS:
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
    change_rate: float  # 등락률 (%)


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
        for table in soup.select("table.type_5"):
            for row in table.select("tr"):
                cols = row.select("td")
                if len(cols) < 6:
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

                # Column 4: 등락률 (change rate %)
                change_text = cols[4].get_text(strip=True)
                change_rate = _parse_change_rate(change_text) if change_text else 0.0

                results.append(StockPerformance(
                    stock_code=code,
                    name=name,
                    change_rate=change_rate,
                ))

        if results:
            _stock_perf_cache.data[naver_code] = results
            _stock_perf_cache.last_updated[naver_code] = now
            logger.info(f"Fetched performance data for {len(results)} stocks in sector {naver_code}")

        return results

    except Exception as e:
        logger.error(f"Failed to fetch stock performances for sector {naver_code}: {e}")
        return _stock_perf_cache.data.get(naver_code, [])


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
