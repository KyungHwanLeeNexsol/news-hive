"""Korea Investment & Securities (KIS) Open API client.

Provides real-time stock data with richer fields than Naver:
- 52-week high/low, PER, PBR, foreign ownership ratio, market cap, etc.
- Market cap ranking (top 30 per request)

Token is cached and auto-refreshed (expires after ~24h).
Rate limit: 20 req/sec.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://openapi.koreainvestment.com:9443"
TOKEN_URL = f"{BASE_URL}/oauth2/tokenP"
PRICE_URL = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-price"
MARKET_CAP_RANK_URL = f"{BASE_URL}/uapi/domestic-stock/v1/ranking/market-cap"

CACHE_TTL = 300  # 5 minutes per-stock cache


@dataclass
class _TokenCache:
    access_token: str = ""
    expires_at: float = 0.0


_token_cache = _TokenCache()


async def _get_access_token(client: httpx.AsyncClient) -> str:
    """Get or refresh the KIS API access token."""
    now = time.time()
    if _token_cache.access_token and now < _token_cache.expires_at - 60:
        return _token_cache.access_token

    resp = await client.post(TOKEN_URL, json={
        "grant_type": "client_credentials",
        "appkey": settings.KIS_APP_KEY,
        "appsecret": settings.KIS_APP_SECRET,
    })
    resp.raise_for_status()
    data = resp.json()

    _token_cache.access_token = data["access_token"]
    _token_cache.expires_at = now + data.get("expires_in", 86400)
    logger.info("KIS API token refreshed")
    return _token_cache.access_token


def _auth_headers(token: str) -> dict:
    return {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": settings.KIS_APP_KEY,
        "appsecret": settings.KIS_APP_SECRET,
        "custtype": "P",
    }


@dataclass
class KISStockPrice:
    """Detailed stock price data from KIS API."""
    stock_code: str
    current_price: int = 0
    price_change: int = 0
    change_rate: float = 0.0
    open_price: int = 0
    high_price: int = 0
    low_price: int = 0
    volume: int = 0
    trading_value: int = 0
    high_52w: int = 0
    low_52w: int = 0
    market_cap: int = 0          # 시가총액 (억원)
    per: float = 0.0
    pbr: float = 0.0
    eps: int = 0
    bps: int = 0
    foreign_ratio: float = 0.0  # 외국인소진율 (%)
    upper_limit: int = 0         # 상한가
    lower_limit: int = 0         # 하한가


@dataclass
class _StockPriceCache:
    data: dict[str, KISStockPrice] = field(default_factory=dict)
    last_updated: dict[str, float] = field(default_factory=dict)


_price_cache = _StockPriceCache()


def _safe_int(val: str) -> int:
    try:
        return int(float(val or 0))
    except (ValueError, TypeError):
        return 0


def _safe_float(val: str) -> float:
    try:
        return float(val or 0)
    except (ValueError, TypeError):
        return 0.0


async def fetch_kis_stock_price(stock_code: str) -> Optional[KISStockPrice]:
    """Fetch detailed stock price from KIS API.

    Returns KISStockPrice or None if KIS keys are not configured.
    Uses 5-min per-stock cache.
    """
    if not settings.KIS_APP_KEY or not settings.KIS_APP_SECRET:
        return None

    now = time.time()
    if (stock_code in _price_cache.data
            and (now - _price_cache.last_updated.get(stock_code, 0)) < CACHE_TTL):
        return _price_cache.data[stock_code]

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            token = await _get_access_token(client)
            headers = _auth_headers(token)
            headers["tr_id"] = "FHKST01010100"

            resp = await client.get(PRICE_URL, headers=headers, params={
                "fid_cond_mrkt_div_code": "J",
                "fid_input_iscd": stock_code,
            })
            resp.raise_for_status()
            data = resp.json()

            if data.get("rt_cd") != "0":
                logger.warning(f"KIS price query failed for {stock_code}: {data.get('msg1')}")
                return _price_cache.data.get(stock_code)

            o = data.get("output", {})
            result = KISStockPrice(
                stock_code=stock_code,
                current_price=_safe_int(o.get("stck_prpr")),
                price_change=_safe_int(o.get("prdy_vrss")),
                change_rate=_safe_float(o.get("prdy_ctrt")),
                open_price=_safe_int(o.get("stck_oprc")),
                high_price=_safe_int(o.get("stck_hgpr")),
                low_price=_safe_int(o.get("stck_lwpr")),
                volume=_safe_int(o.get("acml_vol")),
                trading_value=_safe_int(o.get("acml_tr_pbmn")),
                high_52w=_safe_int(o.get("w52_hgpr")),
                low_52w=_safe_int(o.get("w52_lwpr")),
                market_cap=_safe_int(o.get("hts_avls")),
                per=_safe_float(o.get("per")),
                pbr=_safe_float(o.get("pbr")),
                eps=_safe_int(o.get("eps")),
                bps=_safe_int(o.get("bps")),
                foreign_ratio=_safe_float(o.get("hts_frgn_ehrt")),
                upper_limit=_safe_int(o.get("stck_mxpr")),
                lower_limit=_safe_int(o.get("stck_llam")),
            )

            _price_cache.data[stock_code] = result
            _price_cache.last_updated[stock_code] = now
            return result

    except Exception as e:
        logger.error(f"KIS API error for {stock_code}: {e}")
        return _price_cache.data.get(stock_code)
