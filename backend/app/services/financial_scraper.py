"""WiseReport scraper for stock valuation and financial statement data.

Sources:
- c1010001.aspx: PER, PBR, 시가총액, 배당수익률, 외국인비율 (static HTML)
- cF1001.aspx: 연간/분기 재무제표 (AJAX HTML)
"""

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

WISEREPORT_OVERVIEW_URL = (
    "https://navercomp.wisereport.co.kr/v2/company/c1010001.aspx?cmp_cd={code}"
)
WISEREPORT_FINANCIAL_URL = (
    "https://navercomp.wisereport.co.kr/v2/company/cF1001.aspx"
    "?cmp_cd={code}&cn=&frq={freq}"  # freq=0 annual, freq=1 quarter
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://navercomp.wisereport.co.kr/",
}

CACHE_TTL_SECONDS = 300        # 5 min for valuation
FINANCIAL_CACHE_TTL = 86400    # 24 hours for financial statements


def _parse_float(text: str) -> float:
    """Parse float from Korean financial text, handling commas and whitespace."""
    cleaned = re.sub(r"[^\d.\-]", "", text.strip())
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _parse_int_kr(text: str) -> int:
    """Parse integer from Korean format (e.g. '12,046,463')."""
    cleaned = re.sub(r"[^\d\-]", "", text.strip())
    try:
        return int(cleaned)
    except ValueError:
        return 0


@dataclass
class StockValuation:
    """Valuation metrics from WiseReport overview page."""
    per: float = 0.0                # PER
    pbr: float = 0.0                # PBR
    market_cap: int = 0             # 시가총액 (억원)
    dividend_yield: float = 0.0     # 배당수익률 (%)
    foreign_ratio: float = 0.0      # 외국인비율 (%)
    industry_per: float = 0.0       # 업종 PER


@dataclass
class _ValuationCache:
    data: dict[str, StockValuation] = field(default_factory=dict)
    last_updated: dict[str, float] = field(default_factory=dict)


_valuation_cache = _ValuationCache()


async def fetch_stock_valuation(stock_code: str) -> Optional[StockValuation]:
    """Scrape PER/PBR/시총/배당률/외국인비율 from WiseReport overview.

    Returns StockValuation or None. 5-min cache.
    """
    now = time.time()
    if (stock_code in _valuation_cache.data
            and (now - _valuation_cache.last_updated.get(stock_code, 0)) < CACHE_TTL_SECONDS):
        return _valuation_cache.data[stock_code]

    url = WISEREPORT_OVERVIEW_URL.format(code=stock_code)
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=HEADERS)
            resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        result = StockValuation()

        # Parse the overview table with class "gHead01" or similar
        # PER, PBR are in dt/dd or table cells with specific labels
        for dt in soup.select("dt"):
            label = dt.get_text(strip=True)
            # Find corresponding value (next sibling or nested <b>)
            value_el = dt.select_one("b.num, em")
            if not value_el:
                # Try next dd sibling
                dd = dt.find_next_sibling("dd")
                if dd:
                    value_el = dd.select_one("b.num, em") or dd
                else:
                    continue

            value_text = value_el.get_text(strip=True)

            if "PER" in label and "업종" not in label:
                result.per = _parse_float(value_text)
            elif "업종PER" in label or "업종 PER" in label:
                result.industry_per = _parse_float(value_text)
            elif "PBR" in label:
                result.pbr = _parse_float(value_text)
            elif "배당수익률" in label:
                result.dividend_yield = _parse_float(value_text)

        # Market cap and foreign ratio from table#cTB11 or similar summary table
        for td in soup.select("td"):
            text = td.get_text(strip=True)
            prev_th = td.find_previous_sibling("th")
            if not prev_th:
                # Check parent row for th
                tr = td.parent
                if tr:
                    prev_th = tr.select_one("th")
            if not prev_th:
                continue

            th_text = prev_th.get_text(strip=True)
            if "시가총액" in th_text:
                # Value might be like "12,046,463억원" or just number
                raw = re.sub(r"[^\d]", "", text)
                if raw:
                    result.market_cap = int(raw)
            elif "외국인지분율" in th_text or "외국인" in th_text:
                result.foreign_ratio = _parse_float(text)

        # Also try the "종합정보" section which has a different layout
        for td in soup.select("td.td0301"):
            inner_html = str(td)
            if "PER" in inner_html:
                for b in td.select("b.num"):
                    val = _parse_float(b.get_text(strip=True))
                    if val > 0 and result.per == 0:
                        result.per = val
            if "PBR" in inner_html:
                for b in td.select("b.num"):
                    val = _parse_float(b.get_text(strip=True))
                    if val > 0 and result.pbr == 0:
                        result.pbr = val

        _valuation_cache.data[stock_code] = result
        _valuation_cache.last_updated[stock_code] = now
        return result

    except Exception as e:
        logger.error(f"Failed to fetch valuation for {stock_code}: {e}")
        return _valuation_cache.data.get(stock_code)


@dataclass
class FinancialPeriod:
    """One period of financial data (annual or quarterly)."""
    period: str              # "2024" or "2024/09"
    period_type: str         # "annual" | "quarter"
    revenue: Optional[int] = None            # 매출액 (억원)
    operating_profit: Optional[int] = None   # 영업이익
    operating_margin: Optional[float] = None # 영업이익률 (%)
    net_income: Optional[int] = None         # 순이익
    eps: Optional[int] = None
    bps: Optional[int] = None
    roe: Optional[float] = None
    dividend_payout: Optional[float] = None  # 배당성향 (%)


@dataclass
class _FinancialCache:
    data: dict[str, dict] = field(default_factory=dict)  # {stock_code: {"annual": [...], "quarter": [...]}}
    last_updated: dict[str, float] = field(default_factory=dict)


_financial_cache = _FinancialCache()


def _parse_financial_table(soup: BeautifulSoup, period_type: str) -> list[FinancialPeriod]:
    """Parse WiseReport financial AJAX table into FinancialPeriod list."""
    results: list[FinancialPeriod] = []

    table = soup.select_one("table.gHead01")
    if not table:
        return results

    # Parse column headers to get period labels
    headers: list[str] = []
    thead = table.select_one("thead")
    if thead:
        for th in thead.select("tr th"):
            text = th.get_text(strip=True)
            if text and re.search(r"\d{4}", text):
                # Normalize: "2024/12(E)" → "2024/12", "2024(E)" → "2024"
                clean = re.sub(r"\(.*?\)", "", text).strip()
                headers.append(clean)

    if not headers:
        return results

    # Parse row data
    # Row labels we care about: 매출액, 영업이익, 영업이익률, 당기순이익, EPS, BPS, ROE, 배당성향
    row_map: dict[str, list[str]] = {}
    tbody = table.select_one("tbody")
    if not tbody:
        tbody = table

    for tr in tbody.select("tr"):
        th = tr.select_one("th")
        if not th:
            continue
        label = th.get_text(strip=True)
        # Normalize label
        key = None
        if "매출액" in label:
            key = "revenue"
        elif "영업이익률" in label:
            key = "operating_margin"
        elif "영업이익" in label and "률" not in label:
            key = "operating_profit"
        elif "당기순이익" in label or "순이익" in label:
            key = "net_income"
        elif label.strip() == "EPS" or "EPS(원)" in label:
            key = "eps"
        elif label.strip() == "BPS" or "BPS(원)" in label:
            key = "bps"
        elif "ROE" in label:
            key = "roe"
        elif "배당성향" in label:
            key = "dividend_payout"

        if key:
            cells = [td.get_text(strip=True) for td in tr.select("td")]
            row_map[key] = cells

    # Build FinancialPeriod objects for each column
    for i, period_label in enumerate(headers):
        fp = FinancialPeriod(period=period_label, period_type=period_type)

        for key, cells in row_map.items():
            if i >= len(cells):
                continue
            val_text = cells[i]
            if not val_text or val_text == "-":
                continue

            if key in ("operating_margin", "roe", "dividend_payout"):
                setattr(fp, key, _parse_float(val_text))
            elif key in ("eps", "bps"):
                setattr(fp, key, _parse_int_kr(val_text))
            else:
                setattr(fp, key, _parse_int_kr(val_text))

        results.append(fp)

    return results


async def fetch_stock_financials(stock_code: str) -> dict:
    """Fetch annual + quarterly financials from WiseReport AJAX.

    Returns {"annual": list[FinancialPeriod], "quarter": list[FinancialPeriod]}.
    24-hour cache.
    """
    now = time.time()
    if (stock_code in _financial_cache.data
            and (now - _financial_cache.last_updated.get(stock_code, 0)) < FINANCIAL_CACHE_TTL):
        return _financial_cache.data[stock_code]

    result = {"annual": [], "quarter": []}

    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            # Fetch annual (freq=0) and quarterly (freq=1) in parallel
            annual_url = WISEREPORT_FINANCIAL_URL.format(code=stock_code, freq=0)
            quarter_url = WISEREPORT_FINANCIAL_URL.format(code=stock_code, freq=1)

            annual_resp, quarter_resp = await client.get(annual_url, headers=HEADERS), None
            quarter_resp = await client.get(quarter_url, headers=HEADERS)

        if annual_resp.status_code == 200:
            soup = BeautifulSoup(annual_resp.text, "html.parser")
            result["annual"] = _parse_financial_table(soup, "annual")

        if quarter_resp and quarter_resp.status_code == 200:
            soup = BeautifulSoup(quarter_resp.text, "html.parser")
            result["quarter"] = _parse_financial_table(soup, "quarter")

        if result["annual"] or result["quarter"]:
            _financial_cache.data[stock_code] = result
            _financial_cache.last_updated[stock_code] = now
            logger.info(
                f"Fetched financials for {stock_code}: "
                f"{len(result['annual'])} annual, {len(result['quarter'])} quarterly periods"
            )

        return result

    except Exception as e:
        logger.error(f"Failed to fetch financials for {stock_code}: {e}")
        return _financial_cache.data.get(stock_code, result)
