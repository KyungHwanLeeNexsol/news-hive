"""Naver Finance scraper with in-memory caching.

Sector performance: scrapes sise_group.naver for ~80 sectors.
Stock fundamentals: polling.finance.naver.com realtime JSON API.
Price history: sise_day.naver daily OHLCV scraping.
"""

import asyncio
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from app.config import settings as _settings

logger = logging.getLogger(__name__)

SECTOR_LIST_URL = "https://finance.naver.com/sise/sise_group.naver?type=upjong"
SECTOR_DETAIL_URL = "https://finance.naver.com/sise/sise_group_detail.naver?type=upjong&no={code}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

# 설정에서 캐시 TTL 로드
_CACHE_TTL_MARKET_OPEN = _settings.PRICE_CACHE_TTL_MARKET_OPEN    # 장중 캐시 TTL (초)
_CACHE_TTL_MARKET_CLOSED = _settings.PRICE_CACHE_TTL_MARKET_CLOSED  # 장외 캐시 TTL (초)


def _is_market_open() -> bool:
    """Check if KRX market is currently open (weekdays 09:00~15:30 KST)."""
    from datetime import datetime, timezone, timedelta
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)
    if now.weekday() >= 5:
        return False
    t = now.time()
    from datetime import time as dt_time
    return dt_time(9, 0) <= t <= dt_time(15, 30)


def _cache_ttl() -> int:
    return _CACHE_TTL_MARKET_OPEN if _is_market_open() else _CACHE_TTL_MARKET_CLOSED


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
    Redis 사용 가능 시 인메모리 캐시가 비어있으면 Redis에서 복구 시도.
    """
    now = time.time()
    cache_fresh = (now - _cache.last_updated) < _cache_ttl()

    if not force:
        if _cache.data:
            return _cache.data
        # 인메모리 비어있으면 Redis에서 복구 시도
        if not _cache.data:
            try:
                from app.cache import cache_get
                redis_data = await cache_get("sector:perf")
                if redis_data and isinstance(redis_data, dict):
                    _cache.data = {
                        k: SectorPerformance(**v) for k, v in redis_data.items()
                    }
                    _cache.last_updated = now
                    return _cache.data
            except Exception:
                pass
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
            # Redis에도 저장 (비동기, 실패 무시)
            try:
                from app.cache import cache_set
                from dataclasses import asdict
                await cache_set(
                    "sector:perf",
                    {k: asdict(v) for k, v in results.items()},
                    ttl=_cache_ttl(),
                )
            except Exception:
                pass
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
            and (now - _stock_perf_cache.last_updated.get(naver_code, 0)) < _cache_ttl()):
        return _stock_perf_cache.data[naver_code]

    # 인메모리 미스 시 Redis 복구 시도
    if naver_code not in _stock_perf_cache.data:
        try:
            from app.cache import cache_get
            redis_data = await cache_get(f"sector:{naver_code}:stocks")
            if redis_data and isinstance(redis_data, list):
                _stock_perf_cache.data[naver_code] = [StockPerformance(**item) for item in redis_data]
                _stock_perf_cache.last_updated[naver_code] = now
                return _stock_perf_cache.data[naver_code]
        except Exception:
            pass

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
            # Redis write-through
            try:
                from app.cache import cache_set
                from dataclasses import asdict
                await cache_set(
                    f"sector:{naver_code}:stocks",
                    [asdict(s) for s in results],
                    ttl=_cache_ttl(),
                )
            except Exception:
                pass
            logger.info(f"Fetched performance data for {len(results)} stocks in sector {naver_code}")

        return results

    except Exception as e:
        logger.error(f"Failed to fetch stock performances for sector {naver_code}: {e}")
        return _stock_perf_cache.data.get(naver_code, [])


POLLING_API_URL = "https://polling.finance.naver.com/api/realtime?query=SERVICE_ITEM:{code}"
SISE_DAY_URL = "https://finance.naver.com/item/sise_day.naver?code={code}&page={page}"
# SPEC-AI-067 REQ-008: _PriceHistoryCache의 인메모리 만료는 형제 캐시와 동일하게 _cache_ttl()
# (장중 짧은 TTL / 장외 긴 TTL)을 사용한다. 아래 상수는 Redis write-through TTL로만 잔존.
# [HARD] 이 TTL 변경만으로는 오늘(위메이드형) 장중 지연 재발이 방지되지 않는다 — 신선 fetch에서도
# sise_day 페이지 자체가 stale. 재발 방지 핵심 수정은 REQ-001~005(실시간 모바일 소스 전환)다.
PRICE_CACHE_TTL = 3600  # Redis write-through TTL (일봉 데이터 1시간)


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
            and (now - _fundamentals_cache.last_updated.get(stock_code, 0)) < _cache_ttl()):
        return _fundamentals_cache.data[stock_code]

    # 인메모리 미스 시 Redis 복구 시도
    if stock_code not in _fundamentals_cache.data:
        try:
            from app.cache import cache_get
            redis_data = await cache_get(f"stock:{stock_code}:fundamentals")
            if redis_data and isinstance(redis_data, dict):
                _fundamentals_cache.data[stock_code] = StockFundamentals(**redis_data)
                _fundamentals_cache.last_updated[stock_code] = now
                return _fundamentals_cache.data[stock_code]
        except Exception:
            pass

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
        # Redis write-through
        try:
            from app.cache import cache_set
            from dataclasses import asdict
            await cache_set(f"stock:{stock_code}:fundamentals", asdict(result), ttl=_cache_ttl())
        except Exception:
            pass
        return result

    except Exception as e:
        logger.error(f"Failed to fetch fundamentals for {stock_code}: {e}")
        return _fundamentals_cache.data.get(stock_code)


def _parse_fundamentals_item(item: dict, stock_code: str) -> StockFundamentals:
    """Parse a single item from the Naver polling API response."""
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

    return StockFundamentals(
        stock_code=stock_code,
        current_price=_int("nv"),
        price_change=_int("cv"),
        change_rate=_float("cr"),
        eps=_int("eps"),
        bps=_int("bps"),
        dividend=_int("dv"),
        high_52w=0,
        low_52w=0,
        volume=_int("aq"),
        trading_value=_int("aa"),
    )


BATCH_SIZE = 50  # Naver API max per request


async def fetch_stock_fundamentals_batch(
    stock_codes: list[str],
) -> dict[str, StockFundamentals]:
    """Batch fetch realtime fundamentals from Naver polling API.

    Returns dict keyed by stock_code. Uses per-stock cache (5-min TTL).
    Fetches up to 50 codes per HTTP request.
    """
    now = time.time()
    result: dict[str, StockFundamentals] = {}
    codes_to_fetch: list[str] = []

    # Return cached entries, collect uncached
    for code in stock_codes:
        if (code in _fundamentals_cache.data
                and (now - _fundamentals_cache.last_updated.get(code, 0)) < _cache_ttl()):
            result[code] = _fundamentals_cache.data[code]
        else:
            codes_to_fetch.append(code)

    if not codes_to_fetch:
        return result

    # Fetch in batches of BATCH_SIZE
    for i in range(0, len(codes_to_fetch), BATCH_SIZE):
        batch = codes_to_fetch[i:i + BATCH_SIZE]
        query = ",".join(f"SERVICE_ITEM:{c}" for c in batch)
        url = f"https://polling.finance.naver.com/api/realtime?query={query}"

        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(url, headers=HEADERS)
                resp.raise_for_status()

            text = resp.content.decode("euc-kr", errors="replace")
            data = json.loads(text)

            for area in data.get("result", {}).get("areas", []):
                for item in area.get("datas", []):
                    code = item.get("cd", "")
                    if not code:
                        continue
                    fund = _parse_fundamentals_item(item, code)
                    result[code] = fund
                    _fundamentals_cache.data[code] = fund
                    _fundamentals_cache.last_updated[code] = now

        except Exception as e:
            logger.error(f"Failed to batch fetch fundamentals: {e}")

    # Fallback: fetch missing stocks via Naver mobile API
    missing_codes = [c for c in stock_codes if c not in result]
    if missing_codes:
        import asyncio as _aio
        fallback_tasks = [_fetch_fundamentals_mobile(c) for c in missing_codes]
        fallback_results = await _aio.gather(*fallback_tasks, return_exceptions=True)
        for code, res in zip(missing_codes, fallback_results):
            if isinstance(res, StockFundamentals):
                result[code] = res
                _fundamentals_cache.data[code] = res
                _fundamentals_cache.last_updated[code] = now

    return result


def _extract_accumulated_volume(entries) -> Optional[int]:
    """모바일 price API 응답에서 당일 accumulatedTradingVolume(실시간 누적 거래량)을 추출한다.

    entries[0]가 "오늘" 데이터. _fetch_fundamentals_mobile(async)와
    fetch_live_today_volume_sync(sync, SPEC-AI-067)가 공유하는 파싱 로직 (중복 방지).
    유효 값이 없으면 None (호출부 fail-open).
    """
    if not entries or not isinstance(entries, list):
        return None
    data = entries[0]  # 오늘 데이터
    if not isinstance(data, dict):
        return None
    val = data.get("accumulatedTradingVolume")
    if val is None:
        return None
    try:
        if isinstance(val, (int, float)):
            return int(val)
        return int(str(val).replace(",", "").strip() or 0)
    except (ValueError, TypeError):
        return None


async def _fetch_fundamentals_mobile(stock_code: str) -> Optional[StockFundamentals]:
    """Fallback: fetch stock fundamentals from Naver mobile price API.

    Used when the polling API doesn't return data for a stock.
    The /price endpoint returns daily OHLCV; we use the first entry (today).
    """
    url = f"https://m.stock.naver.com/api/stock/{stock_code}/price"
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(url, headers=HEADERS)
            resp.raise_for_status()

        entries = resp.json()
        if not entries or not isinstance(entries, list):
            return None

        data = entries[0]  # Today's data

        def _parse_int(val) -> int:
            if val is None:
                return 0
            if isinstance(val, (int, float)):
                return int(val)
            return int(str(val).replace(",", "").strip() or 0)

        def _parse_float(val) -> float:
            if val is None:
                return 0.0
            if isinstance(val, (int, float)):
                return float(val)
            return float(str(val).replace(",", "").replace("%", "").strip() or 0)

        return StockFundamentals(
            stock_code=stock_code,
            current_price=_parse_int(data.get("closePrice")),
            price_change=_parse_int(data.get("compareToPreviousClosePrice")),
            change_rate=_parse_float(data.get("fluctuationsRatio")),
            volume=_extract_accumulated_volume(entries) or 0,
            trading_value=0,
        )
    except Exception as e:
        logger.error(f"Mobile API fallback failed for {stock_code}: {e}")
        return None


@dataclass
class PriceRecord:
    """Daily OHLCV price record."""
    date: str           # "2026.02.26"
    close: int = 0
    open: int = 0
    high: int = 0
    low: int = 0
    volume: int = 0


PRICE_CACHE_MAX_SIZE = 500

@dataclass
class _PriceHistoryCache:
    data: dict[str, list[PriceRecord]] = field(default_factory=dict)
    last_updated: dict[str, float] = field(default_factory=dict)
    # SPEC-AI-097 REQ-003: 캐시된 데이터가 몇 페이지 분량인지 기록 — stock_code만으로 히트를
    # 판정하면 짧은 이력(pages=1)이 더 긴 이력(pages=3)을 요구하는 호출에 잘못 재사용될 수 있다.
    pages_fetched: dict[str, int] = field(default_factory=dict)

    def evict_expired(self, ttl: float, max_size: int) -> None:
        now = time.time()
        expired = [k for k, t in self.last_updated.items() if (now - t) > ttl]
        for k in expired:
            self.data.pop(k, None)
            self.last_updated.pop(k, None)
            self.pages_fetched.pop(k, None)
        if len(self.data) > max_size:
            oldest = sorted(self.last_updated, key=lambda k: self.last_updated[k])
            for k in oldest[: len(self.data) - max_size]:
                self.data.pop(k, None)
                self.last_updated.pop(k, None)
                self.pages_fetched.pop(k, None)

    def is_fresh_hit(self, stock_code: str, pages: int, ttl: float) -> bool:
        """SPEC-AI-097 REQ-003: TTL 유효 + pages_fetched >= 요청 pages일 때만 히트로 판정한다.

        pages_fetched가 없는 레거시 상태(코드 배포 직후 재시작 전 캐시)는 0으로 취급해
        항상 미스로 처리한다 — 과소 이력의 조용한 재사용보다 재조회 1회 추가가 안전하다.
        """
        if stock_code not in self.data:
            return False
        now = time.time()
        if (now - self.last_updated.get(stock_code, 0)) >= ttl:
            return False
        return self.pages_fetched.get(stock_code, 0) >= pages


_price_cache = _PriceHistoryCache()


async def fetch_stock_price_history(stock_code: str, pages: int = 5) -> list[PriceRecord]:
    """Fetch daily OHLCV from Naver sise_day.naver (euc-kr HTML).

    pages=5 → ~50 trading days (~2.5 months). Cache TTL = 1 hour.
    """
    now = time.time()
    # SPEC-AI-067 REQ-008: 장중 인지형 TTL (_cache_ttl) — 형제 캐시와 일관.
    # SPEC-AI-097 REQ-003: pages 인지형 조건을 기존 TTL 판정에 AND로 추가.
    if _price_cache.is_fresh_hit(stock_code, pages, _cache_ttl()):
        return _price_cache.data[stock_code]

    # 인메모리 미스 시 Redis 복구 시도.
    # SPEC-AI-097: Redis 저장 데이터는 pages 메타데이터가 없으므로 pages_fetched를 기록하지
    # 않는다 — 다음 호출에서 pages 부족(0)으로 취급되어 안전한 방향(재조회)으로 수렴한다.
    if stock_code not in _price_cache.data:
        try:
            from app.cache import cache_get
            redis_data = await cache_get(f"stock:{stock_code}:prices")
            if redis_data and isinstance(redis_data, list):
                _price_cache.data[stock_code] = [PriceRecord(**item) for item in redis_data]
                _price_cache.last_updated[stock_code] = now
                return _price_cache.data[stock_code]
        except Exception:
            pass

    def _parse_page_html(content_bytes: bytes) -> list[PriceRecord]:
        """HTML 바이트에서 가격 레코드 파싱 (동기)."""
        content = content_bytes.decode("euc-kr", errors="replace")
        soup = BeautifulSoup(content, "html.parser")
        records: list[PriceRecord] = []
        for row in soup.select("table.type2 tr"):
            cols = row.select("td")
            if len(cols) < 7:
                continue
            date_text = cols[0].get_text(strip=True)
            if not date_text or "." not in date_text:
                continue
            close = _parse_int_safe(cols[1].get_text())
            open_price = _parse_int_safe(cols[3].get_text())
            high = _parse_int_safe(cols[4].get_text())
            low = _parse_int_safe(cols[5].get_text())
            volume = _parse_int_safe(cols[6].get_text())
            if close > 0:
                records.append(PriceRecord(
                    date=date_text,
                    close=close,
                    open=open_price,
                    high=high,
                    low=low,
                    volume=volume,
                ))
        return records

    results: list[PriceRecord] = []
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            # 모든 페이지를 병렬로 동시 요청 (순차 → 병렬로 성능 개선)
            urls = [SISE_DAY_URL.format(code=stock_code, page=pg) for pg in range(1, pages + 1)]
            responses = await asyncio.gather(
                *[client.get(url, headers=HEADERS) for url in urls],
                return_exceptions=True,
            )
            for resp in responses:
                if isinstance(resp, Exception):
                    continue
                try:
                    resp.raise_for_status()
                    results.extend(_parse_page_html(resp.content))
                except Exception:
                    continue

        if results:
            # SPEC-AI-067 REQ-008: 인메모리 eviction도 장중 인지형 TTL 사용 (max-size/의미 불변).
            _price_cache.evict_expired(_cache_ttl(), PRICE_CACHE_MAX_SIZE)
            _price_cache.data[stock_code] = results
            _price_cache.last_updated[stock_code] = now
            _price_cache.pages_fetched[stock_code] = pages
            # Redis write-through (TTL=PRICE_CACHE_TTL초, 인메모리 TTL과 독립)
            try:
                from app.cache import cache_set
                from dataclasses import asdict
                await cache_set(f"stock:{stock_code}:prices", [asdict(r) for r in results], ttl=PRICE_CACHE_TTL)
            except Exception:
                pass
            logger.info(f"Fetched {len(results)} daily prices for {stock_code}")

        return results

    except Exception as e:
        logger.error(f"Failed to fetch price history for {stock_code}: {e}")
        return _price_cache.data.get(stock_code, [])


def _parse_sise_day_html(content_bytes: bytes) -> list[PriceRecord]:
    """Naver sise_day.naver HTML 바이트에서 일봉 레코드 파싱 (동기, 모듈 레벨)."""
    content = content_bytes.decode("euc-kr", errors="replace")
    soup = BeautifulSoup(content, "html.parser")
    records: list[PriceRecord] = []
    for row in soup.select("table.type2 tr"):
        cols = row.select("td")
        if len(cols) < 7:
            continue
        date_text = cols[0].get_text(strip=True)
        if not date_text or "." not in date_text:
            continue
        close = _parse_int_safe(cols[1].get_text())
        open_price = _parse_int_safe(cols[3].get_text())
        high = _parse_int_safe(cols[4].get_text())
        low = _parse_int_safe(cols[5].get_text())
        volume = _parse_int_safe(cols[6].get_text())
        if close > 0:
            records.append(PriceRecord(
                date=date_text,
                close=close,
                open=open_price,
                high=high,
                low=low,
                volume=volume,
            ))
    return records


def fetch_stock_price_history_sync(stock_code: str, pages: int = 3) -> list[PriceRecord]:
    """Naver sise_day.naver에서 일봉 OHLCV를 동기적으로 가져온다.

    동기 컨텍스트(급등 탐지기 _get_volume_history)에서 거래량 데이터가 필요할 때 사용.
    캐시 히트 시 즉시 반환, 미스 시 httpx.Client 동기 요청 후 _price_cache에 저장.
    pages=3 → 약 30 거래일(volume_baseline_days=20 충족).
    """
    now = time.time()
    # SPEC-AI-067 REQ-008: 장중 인지형 TTL (_cache_ttl) — 형제 캐시와 일관.
    # SPEC-AI-097 REQ-003: pages 인지형 조건을 기존 TTL 판정에 AND로 추가.
    if _price_cache.is_fresh_hit(stock_code, pages, _cache_ttl()):
        return _price_cache.data[stock_code]

    results: list[PriceRecord] = []
    try:
        with httpx.Client(timeout=5, follow_redirects=True) as client:
            for page in range(1, pages + 1):
                url = SISE_DAY_URL.format(code=stock_code, page=page)
                resp = client.get(url, headers=HEADERS)
                resp.raise_for_status()
                results.extend(_parse_sise_day_html(resp.content))
    except Exception as e:
        logger.debug("fetch_stock_price_history_sync %s 실패: %s", stock_code, e)

    if results:
        _price_cache.data[stock_code] = results
        _price_cache.last_updated[stock_code] = now
        _price_cache.pages_fetched[stock_code] = pages
        logger.debug("[가격캐시] %s %d개 일봉 동기 캐싱 완료(pages=%d)", stock_code, len(results), pages)

    return results


def fetch_stock_price_history_batch_sync(
    stock_codes: list[str],
    pages: int = 3,
    batch_size: int = 10,
    delay_sec: float = 0.5,
) -> dict[str, list[PriceRecord]]:
    """N개 종목의 가격이력을 배치 단위로 동시 조회한다 (SPEC-AI-097 REQ-002).

    concurrent.futures.ThreadPoolExecutor로 배치당 batch_size개를 동시에 조회하고
    배치 사이에 delay_sec만큼 대기한다 — fetch_current_prices_batch(SPEC-AI-016, asyncio
    기반)와 동일한 배치/딜레이 패턴을 동기 시그니처로 재현한다. surge_detector.py 전체가
    동기 함수이므로(spec.md Decision D1) asyncio.gather 대신 스레드풀을 사용한다.

    워커 스레드는 종목당 fetch_stock_price_history_sync를 그대로 호출한다(중복 구현
    없음) — 이 함수 자체가 캐시 히트 판정 + HTTP 조회 + 캐시 갱신을 이미 담당하므로,
    기존 fetch_stock_price_history_sync를 대상으로 한 테스트 mock과의 호환성도
    자연히 유지된다(AC-097-005).

    스레드 안전성: 이 함수 호출 1회 안에서 stock_codes는 중복 제거되므로, 어떤 두
    스레드도 동일한 stock_code(=동일 캐시 dict 키)를 동시에 쓰지 않는다. 서로 다른
    키에 대한 dict 쓰기는 CPython GIL 하에서 개별 연산이 원자적이므로 잠금 없이도
    경합이 발생하지 않는다(AC-097-007). evict_expired()는 스레드 스폰 이전에 메인
    스레드에서 1회만 수행한다.

    개별 종목 조회 실패는 예외를 전파하지 않고 빈 리스트로 결과에 포함한다(기존
    fetch_stock_price_history_sync의 실패 격리 관례를 승계).

    Args:
        stock_codes: 조회할 종목 코드 목록.
        pages: 종목별 요청 페이지 수.
        batch_size: 배치당 동시 조회 종목 수.
        delay_sec: 배치 간 대기 시간(초).

    Returns:
        {stock_code: list[PriceRecord]} — 실패하거나 데이터가 없는 종목은 빈 리스트.
    """
    _measure_start = time.time()
    ttl = _cache_ttl()

    # 순서 보존 dedup — 동일 종목이 두 스레드에 동시 배정되는 것을 원천 차단한다.
    codes = list(dict.fromkeys(stock_codes))
    # SPEC-AI-097 REQ-005 측정용: 캐시 히트 vs HTTP 조회 필요 종목 수를 사전 구분한다
    # (실제 조회/캐시갱신은 fetch_stock_price_history_sync가 스레드 내부에서 재수행).
    cache_hit_count = sum(1 for c in codes if _price_cache.is_fresh_hit(c, pages, ttl))

    if not codes:
        return {}

    _price_cache.evict_expired(ttl, PRICE_CACHE_MAX_SIZE)

    results: dict[str, list[PriceRecord]] = {}
    for batch_start in range(0, len(codes), batch_size):
        batch = codes[batch_start: batch_start + batch_size]
        with ThreadPoolExecutor(max_workers=len(batch)) as executor:
            future_to_code = {
                executor.submit(fetch_stock_price_history_sync, code, pages): code
                for code in batch
            }
            for future in as_completed(future_to_code):
                code = future_to_code[future]
                try:
                    results[code] = future.result()
                except Exception as e:
                    logger.debug("배치 가격이력 조회 실패 %s: %s", code, e)
                    results[code] = []

        if batch_start + batch_size < len(codes):
            time.sleep(delay_sec)

    # SPEC-AI-097 REQ-005: 캐시 히트를 제외한 HTTP 조회 종목 수 + 조회 단계 소요시간(초) 기록.
    logger.info(
        "[가격이력배치] %d개 종목 조회 완료 (캐시히트 %d, HTTP조회 %d, 소요 %.2f초)",
        len(codes), cache_hit_count, len(codes) - cache_hit_count,
        time.time() - _measure_start,
    )

    return results


def fetch_volume_leaders_sync(limit: int = 50, max_pages: int = 1) -> list[str]:
    """Naver 거래량 순위 페이지에서 당일 거래량 상위 종목 코드를 동기적으로 반환한다.

    KOSPI + KOSDAQ 각 limit개씩 조회하여 중복 없이 합산 반환.
    탐지기 실행 시점(장 중 또는 장 마감 후)에 따라 당일 누적 거래량 기준.

    SPEC-AI-074 REQ-002: 단일 페이지 행 수(~50)를 초과하는 limit을 채우려면 max_pages(> 1)를
    지정한다 — market별 추가 페이지(&page=N)를 순차 조회하는 유계 오버페치다. 기존 호출부
    (detect_volume_breakout, SPEC-AI-062/063/066)는 max_pages 기본값 1로 단일 페이지 거동을
    그대로 유지하여 거동 diff가 없다(SPEC-AI-074 Exclusion 3).

    Args:
        limit: market(KOSPI/KOSDAQ)별 최대 반환 종목 수.
        max_pages: market별 최대 조회 페이지 수 (기본 1 = 기존 단일 페이지 거동, 하위 호환).
    """
    from bs4 import BeautifulSoup

    codes: list[str] = []
    seen: set[str] = set()

    for sosok in (0, 1):  # 0=KOSPI, 1=KOSDAQ
        count = 0
        for page in range(1, max(1, max_pages) + 1):
            if count >= limit:
                break
            url = f"https://finance.naver.com/sise/sise_quant.naver?sosok={sosok}"
            if page > 1:
                url = f"{url}&page={page}"
            try:
                with httpx.Client(timeout=10, follow_redirects=True) as client:
                    resp = client.get(url, headers=HEADERS)
                    resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")
                rows = soup.select("a.tltle[href*='code=']")
                if not rows:
                    break  # 더 이상 페이지 없음
                new_on_page = 0
                for a_tag in rows:
                    import re as _re
                    m = _re.search(r"code=(\d{6})", a_tag.get("href", ""))
                    if not m:
                        continue
                    code = m.group(1)
                    if code not in seen:
                        seen.add(code)
                        codes.append(code)
                        count += 1
                        new_on_page += 1
                    if count >= limit:
                        break
                if new_on_page == 0:
                    break  # 신규 코드 없음(중복만 있거나 목록 끝) → 추가 페이지 무의미
            except Exception as e:
                logger.warning("거래량 순위 조회 실패 (sosok=%d, page=%d): %s", sosok, page, e)
                break

    return codes


def fetch_current_price_with_change_sync(stock_code: str) -> dict | None:
    """특정 종목의 현재가 + 등락률을 동기적으로 반환 (Naver 모바일 API).

    동기 컨텍스트(_fetch_price_change_sync)에서 현재가 조회가 필요할 때 사용.
    asyncio.run() 없이 httpx.Client로 직접 호출하여 이벤트 루프 충돌을 방지한다.

    엔드포인트: /api/stock/{code}/price (리스트 반환)
    이전 /integration 엔드포인트는 stockInfo: {} 빈 객체를 반환하여 폐기.
    """
    # @MX:ANCHOR: [AUTO] price_at_signal 주입 경로 — fund_manager, disclosure_impact_scorer 등 다수 호출
    # @MX:REASON: [AUTO] /integration → /price 엔드포인트 교체 (2026-06-16). 반환 형식이 dict→list로 변경.
    mobile_url = f"https://m.stock.naver.com/api/stock/{stock_code}/price"
    try:
        with httpx.Client(timeout=5, follow_redirects=True) as client:
            resp = client.get(mobile_url, headers=HEADERS)
            resp.raise_for_status()
        data = resp.json()
        if not data or not isinstance(data, list):
            return None
        item = data[0]
        price_str = item.get("closePrice", "")
        rate_str = item.get("fluctuationsRatio", "0")
        if price_str:
            try:
                rate = float(str(rate_str).replace(",", ""))
            except (ValueError, TypeError):
                rate = 0.0
            return {
                "current_price": _parse_comma_int(str(price_str)),
                "change_rate": rate,
            }
    except Exception as e:
        logger.debug("fetch_current_price_with_change_sync %s 실패: %s", stock_code, e)
    return None


def fetch_live_today_volume_sync(stock_code: str) -> Optional[int]:
    """당일 실시간 누적 거래량(accumulatedTradingVolume)을 동기적으로 반환 (SPEC-AI-067 REQ-001).

    Naver 모바일 API /api/stock/{code}/price 엔드포인트(비동기 _fetch_fundamentals_mobile,
    동기 fetch_current_price_with_change_sync가 이미 사용 중)의 accumulatedTradingVolume
    필드를 동기 경로에서 추출한다. sise_day "오늘" 행이 장중에 지연(최대 4.0x 과소계상)되는
    문제를 교정하기 위한 공유 소스.

    실패/미존재/필드부재 시 None을 반환하여 호출부(surge_detector._resolve_today_volume)가
    sise_day 값으로 fail-open 폴백하게 한다.
    """
    mobile_url = f"https://m.stock.naver.com/api/stock/{stock_code}/price"
    try:
        with httpx.Client(timeout=5, follow_redirects=True) as client:
            resp = client.get(mobile_url, headers=HEADERS)
            resp.raise_for_status()
        return _extract_accumulated_volume(resp.json())
    except Exception as e:
        logger.debug("fetch_live_today_volume_sync %s 실패: %s", stock_code, e)
        return None


MARKET_CAP_URL = "https://finance.naver.com/sise/sise_market_sum.naver?sosok={sosok}&page={page}"


@dataclass
class MarketCapItem:
    """Stock info from Naver market cap ranking page."""
    rank: int
    stock_code: str
    name: str
    current_price: int = 0
    price_change: int = 0
    change_rate: float = 0.0
    market_cap: int = 0            # 시가총액 (억원)
    volume: int = 0
    market: str = ""               # KOSPI or KOSDAQ


@dataclass
class _MarketCapCache:
    data: list[MarketCapItem] = field(default_factory=list)
    last_updated: float = 0.0


_market_cap_cache = _MarketCapCache()


async def _fetch_market_cap_page(
    client: httpx.AsyncClient,
    sosok: int,
    market_name: str,
    page: int,
) -> list[MarketCapItem]:
    """Fetch a single market cap ranking page. Used for parallel fetching."""
    url = MARKET_CAP_URL.format(sosok=sosok, page=page)
    try:
        resp = await client.get(url, headers=HEADERS)
        resp.raise_for_status()

        content = resp.content.decode("euc-kr", errors="replace")
        soup = BeautifulSoup(content, "html.parser")

        table = soup.select_one("table.type_2")
        if not table:
            return []

        items: list[MarketCapItem] = []
        for row in table.select("tr"):
            cols = row.select("td")
            if len(cols) < 10:
                continue

            rank_text = cols[0].get_text(strip=True)
            if not rank_text.isdigit():
                continue

            link = cols[1].select_one("a[href*='code=']")
            if not link:
                continue
            name = link.get_text(strip=True)
            href = link.get("href", "")
            code = href.split("code=")[-1].split("&")[0].strip()
            if not code or len(code) != 6:
                continue

            current_price = _parse_int_safe(cols[2].get_text())

            change_text = cols[3].get_text(strip=True)
            change_num = re.sub(r"[^\d]", "", change_text)
            change_abs = int(change_num) if change_num else 0

            change_rate = _parse_change_rate(cols[4].get_text(strip=True))
            if change_rate < 0:
                change_abs = -change_abs

            market_cap = _parse_int_safe(cols[6].get_text())
            volume = _parse_int_safe(cols[9].get_text())

            items.append(MarketCapItem(
                rank=int(rank_text),
                stock_code=code,
                name=name,
                current_price=current_price,
                price_change=change_abs,
                change_rate=change_rate,
                market_cap=market_cap,
                volume=volume,
                market=market_name,
            ))

        return items

    except Exception as e:
        logger.error(f"Failed to fetch market cap page {market_name} p{page}: {e}")
        return []


async def fetch_market_cap_rankings(
    max_pages_per_market: int = 3,
) -> list[MarketCapItem]:
    """Fetch stocks ranked by market cap from Naver Finance.

    Scrapes sise_market_sum.naver for both KOSPI (sosok=0) and KOSDAQ (sosok=1).
    Default 3 pages per market = top ~150 stocks per market (300 total).
    All pages fetched in parallel for speed. Uses 5-min cache.
    """
    now = time.time()
    if _market_cap_cache.data and (now - _market_cap_cache.last_updated) < _cache_ttl():
        return _market_cap_cache.data

    # 인메모리 비어있으면 Redis 복구 시도
    if not _market_cap_cache.data:
        try:
            from app.cache import cache_get
            redis_data = await cache_get("market:caps")
            if redis_data and isinstance(redis_data, list):
                _market_cap_cache.data = [MarketCapItem(**item) for item in redis_data]
                _market_cap_cache.last_updated = now
                return _market_cap_cache.data
        except Exception:
            pass

    import asyncio

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        # Build all page fetch tasks (both markets, all pages) for parallel execution
        tasks = []
        for sosok, market_name in [(0, "KOSPI"), (1, "KOSDAQ")]:
            for page in range(1, max_pages_per_market + 1):
                tasks.append(_fetch_market_cap_page(client, sosok, market_name, page))

        page_results = await asyncio.gather(*tasks)

    # Flatten and maintain order (KOSPI first, then KOSDAQ, each by rank)
    results: list[MarketCapItem] = []
    for items in page_results:
        results.extend(items)

    if results:
        _market_cap_cache.data = results
        _market_cap_cache.last_updated = now
        # Redis write-through
        try:
            from app.cache import cache_set
            from dataclasses import asdict
            await cache_set("market:caps", [asdict(item) for item in results], ttl=_cache_ttl())
        except Exception:
            pass
        logger.info(f"Fetched market cap rankings: {len(results)} stocks")

    return _market_cap_cache.data if _market_cap_cache.data else results


NAVER_MOBILE_API_URL = "https://m.stock.naver.com/api/stocks/marketValue/{market}?page={page}&pageSize={page_size}"


@dataclass
class NaverStockItem:
    """Stock data from Naver Mobile API (real-time, JSON)."""
    stock_code: str
    name: str
    current_price: int = 0
    price_change: int = 0
    change_rate: float = 0.0
    market_cap: int = 0          # 시가총액 (억원)
    volume: int = 0
    trading_value: int = 0       # 거래대금 (백만원)
    market: str = ""             # KOSPI or KOSDAQ


@dataclass
class _NaverStockListCache:
    data: dict[str, list[NaverStockItem]] = field(default_factory=dict)  # key = "KOSPI:1:50"
    last_updated: dict[str, float] = field(default_factory=dict)


_naver_stock_list_cache = _NaverStockListCache()


def _parse_comma_int(s: str) -> int:
    """Parse comma-formatted number string like '187,400' to int."""
    try:
        return int(s.replace(",", ""))
    except (ValueError, TypeError):
        return 0


async def fetch_naver_stock_list(
    market: str = "KOSPI",
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[NaverStockItem], int]:
    """Fetch stock list from Naver Mobile API (JSON, real-time).

    Returns (items, total_count). Lightweight JSON endpoint, no HTML scraping.
    Cache TTL adapts to market hours (10s open, 300s closed).
    """
    cache_key = f"{market}:{page}:{page_size}"
    now = time.time()
    if (cache_key in _naver_stock_list_cache.data
            and (now - _naver_stock_list_cache.last_updated.get(cache_key, 0)) < _cache_ttl()):
        # Return cached data; total_count is stored as first element's rank hack — just return len
        cached = _naver_stock_list_cache.data[cache_key]
        return cached, 0  # total_count not cached, but router caches full response anyway

    url = NAVER_MOBILE_API_URL.format(market=market, page=page, page_size=page_size)
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=HEADERS)
            resp.raise_for_status()

        data = resp.json()
        total_count = data.get("totalCount", 0)
        stocks = data.get("stocks", [])

        items: list[NaverStockItem] = []
        for s in stocks:
            code = s.get("itemCode", "")
            if not code:
                continue

            # Parse price change (compareToPreviousClosePrice is a signed string like "-5,000")
            change_str = s.get("compareToPreviousClosePrice", "0")
            price_change = _parse_comma_int(change_str)

            # Parse change rate
            try:
                change_rate = float(s.get("fluctuationsRatio", 0) or 0)
            except (ValueError, TypeError):
                change_rate = 0.0

            # compareToPreviousPrice.name: RISING/FALLING/FLAT
            direction = s.get("compareToPreviousPrice", {})
            if isinstance(direction, dict) and direction.get("name") == "FALLING":
                if change_rate > 0:
                    change_rate = -change_rate

            items.append(NaverStockItem(
                stock_code=code,
                name=s.get("stockName", ""),
                current_price=_parse_comma_int(s.get("closePrice", "0")),
                price_change=price_change,
                change_rate=change_rate,
                market_cap=_parse_comma_int(s.get("marketValue", "0")),
                volume=_parse_comma_int(s.get("accumulatedTradingVolume", "0")),
                trading_value=_parse_comma_int(s.get("accumulatedTradingValue", "0")),
                market=market,
            ))

        if items:
            _naver_stock_list_cache.data[cache_key] = items
            _naver_stock_list_cache.last_updated[cache_key] = now

        return items, total_count

    except Exception as e:
        logger.error(f"Failed to fetch Naver stock list {market} p{page}: {e}")
        cached = _naver_stock_list_cache.data.get(cache_key, [])
        return cached, 0


async def fetch_top_movers_codes(market: str = "KOSDAQ", limit: int = 30) -> list[str]:
    """상승률 상위 종목 코드 목록 반환 (네이버 금융 sise_rise 스크래핑).

    Args:
        market: "KOSPI" 또는 "KOSDAQ"
        limit: 반환할 최대 종목 수 (기본 30)

    Returns:
        종목코드 문자열 리스트 (예: ["005930", "000660", ...])
    """
    market_type = "0" if market.upper() == "KOSPI" else "1"
    url = f"https://finance.naver.com/sise/sise_rise.naver?sosok={market_type}"
    codes: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=HEADERS)
            resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        # 2026-05-20 HTML 구조 변경: td.name → a.tltle (CSS 클래스명 변경)
        # 순위 tr 내의 종목 링크 파싱
        for a_tag in soup.select("a.tltle[href*='code=']"):
            href = a_tag.get("href", "")
            code_match = re.search(r"code=(\d{6})", href)
            if code_match:
                codes.append(code_match.group(1))
            if len(codes) >= limit:
                break
    except Exception as e:
        logger.error("상승률 상위 종목 조회 실패 (%s): %s", market, e)

    return codes


async def fetch_current_price(stock_code: str) -> int | None:
    """특정 종목의 현재가 반환 (SPEC-AI-004).

    KOSPI/KOSDAQ 통합 검색으로 현재가를 반환한다.
    """
    for market in ("KOSPI", "KOSDAQ"):
        try:
            items, _ = await fetch_naver_stock_list(market=market, page=1, page_size=50)
            for item in items:
                if item.stock_code == stock_code:
                    return item.current_price
        except Exception:
            continue

    # 모바일 API fallback: 개별 종목 조회
    mobile_url = (
        f"https://m.stock.naver.com/api/stock/{stock_code}/integration"
    )
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(mobile_url, headers=HEADERS)
            resp.raise_for_status()
        data = resp.json()
        price_str = (
            data.get("dealTrendInfos", [{}])[0].get("closePrice", "")
            or data.get("stockInfo", {}).get("closePrice", "")
        )
        if price_str:
            return _parse_comma_int(str(price_str))
    except Exception as e:
        logger.debug("fetch_current_price fallback 실패 (%s): %s", stock_code, e)

    return None


async def fetch_current_price_with_change(stock_code: str) -> dict | None:
    """특정 종목의 현재가 + 등락률 반환 (SPEC-AI-004).

    Returns:
        {"current_price": int, "change_rate": float} 또는 None
    """
    for market in ("KOSPI", "KOSDAQ"):
        try:
            items, _ = await fetch_naver_stock_list(market=market, page=1, page_size=50)
            for item in items:
                if item.stock_code == stock_code:
                    return {
                        "current_price": item.current_price,
                        "change_rate": item.change_rate,
                    }
        except Exception:
            continue

    # 모바일 API fallback (/integration 폐기 → /price 엔드포인트, 2026-06-16)
    mobile_url = (
        f"https://m.stock.naver.com/api/stock/{stock_code}/price"
    )
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(mobile_url, headers=HEADERS)
            resp.raise_for_status()
        data = resp.json()
        if data and isinstance(data, list):
            item = data[0]
            price_str = item.get("closePrice", "")
            rate_str = item.get("fluctuationsRatio", "0")
            if price_str:
                try:
                    rate = float(str(rate_str).replace(",", ""))
                except (ValueError, TypeError):
                    rate = 0.0
                return {
                    "current_price": _parse_comma_int(str(price_str)),
                    "change_rate": rate,
                }
    except Exception as e:
        logger.debug("fetch_current_price_with_change fallback 실패 (%s): %s", stock_code, e)

    # 가격 히스토리 fallback: stockInfo 없는 중소형주 대응 (Naver 내림차순: prices[0]=최신)
    try:
        history = await fetch_stock_price_history(stock_code, pages=1)
        if history and len(history) >= 2:
            latest = float(history[0].close)
            prev = float(history[1].close)
            if prev > 0:
                change_rate = round((latest - prev) / prev * 100, 2)
                return {
                    "current_price": int(latest),
                    "change_rate": change_rate,
                }
    except Exception as e:
        logger.debug("fetch_current_price_with_change history fallback 실패 (%s): %s", stock_code, e)

    return None


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


# ---------------------------------------------------------------------------
# 투자자별 매매동향 (외국인/기관 순매수)
# ---------------------------------------------------------------------------

@dataclass
class InvestorTrading:
    """일별 투자자 매매동향."""
    date: str  # YYYY.MM.DD
    foreign_net: int = 0  # 외국인 순매수 (주)
    institution_net: int = 0  # 기관 순매수 (주)
    individual_net: int = 0  # 개인 순매수 (주)


async def fetch_investor_trading(stock_code: str, days: int = 5) -> list[InvestorTrading]:
    """네이버 금융에서 종목의 투자자별 매매동향을 가져온다.

    https://finance.naver.com/item/frgn.naver?code={stock_code}
    """
    url = f"https://finance.naver.com/item/frgn.naver?code={stock_code}&page=1"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=HEADERS)
            if resp.status_code != 200:
                return []

        soup = BeautifulSoup(resp.text, "html.parser")

        # 매매동향 테이블 파싱
        # frgn.naver 페이지에는 table.type2가 2개 존재:
        # - 첫 번째: 증권사별 순위 테이블 (날짜 없음)
        # - 두 번째: 날짜별 투자자 매매동향 테이블 (날짜 있음) ← 이것을 사용
        tables = soup.select("table.type2")
        table = None
        for t in tables:
            first_row_tds = t.select("tr td")
            if first_row_tds and "." in first_row_tds[0].get_text(strip=True):
                table = t
                break
        if not table:
            return []

        results: list[InvestorTrading] = []
        rows = table.select("tr")

        for row in rows:
            cols = row.select("td")
            if len(cols) < 6:
                continue

            date_text = cols[0].get_text(strip=True)
            if not date_text or "." not in date_text:
                continue

            def _parse_int(text: str) -> int:
                text = text.strip().replace(",", "").replace("+", "")
                if not text or text == "0":
                    return 0
                try:
                    return int(text)
                except ValueError:
                    return 0

            # 컬럼 순서: 날짜, 종가, 전일비, 거래량, 기관순매매, 외국인순매매
            try:
                trading = InvestorTrading(
                    date=date_text,
                    institution_net=_parse_int(cols[4].get_text()),
                    foreign_net=_parse_int(cols[5].get_text()),
                )
                # 개인 = -(기관 + 외국인) 근사치
                trading.individual_net = -(trading.institution_net + trading.foreign_net)
                results.append(trading)

                if len(results) >= days:
                    break
            except (IndexError, ValueError):
                continue

        return results

    except Exception as e:
        logger.debug(f"Investor trading fetch failed for {stock_code}: {e}")
        return []


# KOSPI/KOSDAQ 지수 일별 시세 URL
INDEX_DAY_URL = "https://finance.naver.com/sise/sise_index_day.naver?code={code}&page={page}"


async def fetch_index_price_history(index_code: str = "KOSPI", pages: int = 2) -> list[dict]:
    """네이버 금융에서 시장 지수(KOSPI/KOSDAQ)의 일별 시세를 가져온다.

    Args:
        index_code: 지수 코드 ("KOSPI" 또는 "KOSDAQ")
        pages: 조회할 페이지 수 (1페이지 = 약 10거래일)

    Returns:
        [{"date": "YYYY.MM.DD", "close": float}, ...] 최신순 정렬
    """
    results: list[dict] = []

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            urls = [INDEX_DAY_URL.format(code=index_code, page=pg) for pg in range(1, pages + 1)]
            responses = await asyncio.gather(
                *[client.get(url, headers=HEADERS) for url in urls],
                return_exceptions=True,
            )

        for resp in responses:
            if isinstance(resp, Exception):
                continue
            try:
                resp.raise_for_status()
            except Exception:
                continue

            content = resp.content.decode("euc-kr", errors="replace")
            soup = BeautifulSoup(content, "html.parser")
            table = soup.select_one("table.type_1")
            if not table:
                continue

            for row in table.select("tr"):
                cols = row.select("td")
                if len(cols) < 2:
                    continue
                date_text = cols[0].get_text(strip=True)
                close_text = cols[1].get_text(strip=True).replace(",", "")
                if not date_text or "." not in date_text:
                    continue
                try:
                    results.append({"date": date_text, "close": float(close_text)})
                except ValueError:
                    continue

    except Exception as e:
        logger.debug(f"Index price history fetch failed for {index_code}: {e}")

    return results


# @MX:ANCHOR: [AUTO] 배치 가격 조회 — 매수 사이클 진입점 (SPEC-AI-016)
# @MX:REASON: [AUTO] execute_buy_orders에서 N개 종목 일괄 조회에 사용. 향후 매도/평가 사이클 확장 시 fan_in 증가 예상
# @MX:SPEC: SPEC-AI-016 REQ-004
async def fetch_current_prices_batch(
    stock_codes: list[str],
    batch_size: int = 10,
    delay_sec: float = 0.5,
    retry_count: int = 1,
) -> dict[str, dict | None]:
    """N개 종목의 현재가+등락률을 배치 단위로 조회 (Naver Finance 레이트 리미트 회피).

    각 배치는 asyncio.gather()로 동시 조회, 배치 사이에 delay_sec 대기.
    종목별 실패 시 retry_count 회 재시도 후 None 반환 (예외 전파 없음).

    Args:
        stock_codes: 조회할 종목 코드 목록
        batch_size: 배치당 동시 조회 종목 수 (기본 10)
        delay_sec: 배치 간 대기 시간(초) (기본 0.5)
        retry_count: 종목별 실패 시 재시도 횟수 (기본 1)

    Returns:
        {stock_code: {"current_price": int, "change_rate": float} | None}
    """
    async def _fetch_one_with_retry(code: str) -> tuple[str, dict | None]:
        """단일 종목 조회 + retry_count 재시도."""
        for attempt in range(retry_count + 1):
            try:
                result = await fetch_current_price_with_change(code)
                if result is not None:
                    return code, result
            except Exception as e:
                logger.debug("배치 가격 조회 실패 %s (시도 %d/%d): %s", code, attempt + 1, retry_count + 1, e)
        return code, None

    results: dict[str, dict | None] = {}

    # 배치 분할 처리
    for batch_start in range(0, len(stock_codes), batch_size):
        batch = stock_codes[batch_start: batch_start + batch_size]
        # 배치 내 동시 조회
        batch_results = await asyncio.gather(*[_fetch_one_with_retry(code) for code in batch])
        for code, data in batch_results:
            results[code] = data

        # 마지막 배치가 아닌 경우 레이트 리미트 회피 대기
        if batch_start + batch_size < len(stock_codes):
            await asyncio.sleep(delay_sec)

    return results
