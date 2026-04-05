"""WiseReport scraper for stock valuation and financial statement data.

Sources:
- c1010001.aspx: PER, PBR, 시가총액, 배당수익률, 외국인비율 (static HTML)
- cF1001.aspx: 연간/분기 재무제표 (AJAX HTML)
- cF1002.aspx: 컨센서스 추정치 (연간 실적 + 추정)
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
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
WISEREPORT_CONSENSUS_URL = (
    "https://navercomp.wisereport.co.kr/v2/company/cF1002.aspx"
    "?cmp_cd={code}&cn=&frq=0"
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

    # 인메모리 미스 시 Redis 복구 시도
    if stock_code not in _valuation_cache.data:
        try:
            from app.cache import cache_get
            redis_data = await cache_get(f"stock:{stock_code}:valuation")
            if redis_data and isinstance(redis_data, dict):
                _valuation_cache.data[stock_code] = StockValuation(**redis_data)
                _valuation_cache.last_updated[stock_code] = now
                return _valuation_cache.data[stock_code]
        except Exception:
            pass

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
        # Redis write-through (TTL=300초)
        try:
            from app.cache import cache_set
            from dataclasses import asdict
            await cache_set(f"stock:{stock_code}:valuation", asdict(result), ttl=300)
        except Exception:
            pass
        return result

    except Exception as e:
        logger.error(f"Failed to fetch valuation for {stock_code}: {e}")
        return _valuation_cache.data.get(stock_code)


@dataclass
class FinancialPeriod:
    """One period of financial data (annual or quarterly)."""
    period: str              # "2024/12" or "2025/09"
    period_type: str         # "annual" | "quarter"
    is_estimate: bool = False                # True for consensus estimates (E)
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


def _parse_financial_table(soup: BeautifulSoup) -> dict:
    """Parse WiseReport financial table — returns {"annual": [...], "quarter": [...]}.

    The cF1001.aspx page has ONE table with both annual and quarterly data.
    Header row 0 has "연간" (colspan=N) and "분기" (colspan=N) — typically N=4.
    Header row 1 has period labels in 4 groups of 5: annual-consolidated,
    annual-individual, quarterly-consolidated, quarterly-individual.
    But data rows only have 8 TD cells: 4 annual + 4 quarterly.

    We use the first N period headers for annual and the headers at offset
    2*N+1 (skipping individual group) for quarterly, where N = annual colspan.
    """
    result: dict[str, list[FinancialPeriod]] = {"annual": [], "quarter": []}

    # Table class is "gHead all-width" (not "gHead01")
    table = soup.select_one("table.gHead")
    if not table:
        # Fallback: try any table with enough rows
        tables = soup.select("table")
        for t in tables:
            if len(t.select("tr")) >= 10:
                table = t
                break
    if not table:
        return result

    thead = table.select_one("thead")
    header_rows = thead.select("tr") if thead else table.select("tr")[:2]
    if len(header_rows) < 2:
        return result

    # Determine annual/quarterly column counts from header row 0's colspan
    # Row 0 has cells like: "주요재무정보" (rowspan=2), "연간" (colspan=4), "분기" (colspan=4)
    annual_cols = 4  # default
    quarter_cols = 4
    for cell in header_rows[0].select("th, td"):
        text = cell.get_text(strip=True)
        colspan = int(cell.get("colspan", 1))
        if "연간" in text:
            annual_cols = colspan
        elif "분기" in text:
            quarter_cols = colspan

    # Parse ALL period headers from header row 1
    all_headers: list[str] = []
    for th in header_rows[1].select("th, td"):
        text = th.get_text(strip=True)
        if text and re.search(r"\d{4}", text):
            # Normalize: "2024/12(E)" → "2024/12"
            clean = re.sub(r"\(.*?\)", "", text).strip()
            all_headers.append(clean)

    if not all_headers:
        return result

    # Header row 1 has 4 groups: each group has (annual_cols+1) or (quarter_cols+1) headers
    # (extra 1 for estimate column). But some stocks may have fewer.
    #
    # Group A: annual consolidated   [0 .. annual_cols-1] (skip estimate at annual_cols)
    # Group B: annual individual     (skip entirely)
    # Group C: quarterly consolidated (skip Groups A+B)
    # Group D: quarterly individual  (skip entirely)
    #
    # Group size = cols + 1 (one estimate column per group)
    annual_group_size = annual_cols + 1  # typically 5
    _ = quarter_cols  # quarter_group_size는 현재 사용하지 않으나 향후 분기별 파싱에 필요

    # Annual headers: first annual_cols from Group A (skip the estimate)
    annual_headers = all_headers[:annual_cols]

    # Quarterly headers: skip Groups A and B, take first quarter_cols from Group C
    quarter_offset = annual_group_size * 2  # skip Group A + Group B
    quarter_headers = all_headers[quarter_offset:quarter_offset + quarter_cols]

    # Fallback: if we don't have enough headers, try simpler split
    # (e.g., table has exactly 8 headers without group structure)
    if len(annual_headers) < annual_cols and len(all_headers) == annual_cols + quarter_cols:
        annual_headers = all_headers[:annual_cols]
        quarter_headers = all_headers[annual_cols:]

    # Row label → key mapping (first match wins)
    label_map = [
        ("매출액", "revenue"),
        ("영업이익률", "operating_margin"),
        ("영업이익", "operating_profit"),  # Must come after 영업이익률
        ("당기순이익", "net_income"),
        ("EPS", "eps"),
        ("BPS", "bps"),
        ("ROE", "roe"),
        ("배당성향", "dividend_payout"),
    ]

    # Parse data rows: each row has 8 <td> cells (4 annual + 4 quarterly)
    row_map: dict[str, list[str]] = {}
    tbody = table.select_one("tbody") or table

    for tr in tbody.select("tr"):
        th = tr.select_one("th")
        if not th:
            continue
        label = th.get_text(strip=True)

        key = None
        for keyword, k in label_map:
            if keyword in label:
                # Avoid 영업이익 matching 영업이익률
                if k == "operating_profit" and "률" in label:
                    continue
                key = k
                break

        if key and key not in row_map:  # First match only
            cells = [td.get_text(strip=True) for td in tr.select("td")]
            row_map[key] = cells

    # Build annual periods (data cells 0..annual_cols-1)
    for i, period_label in enumerate(annual_headers):
        fp = FinancialPeriod(period=period_label, period_type="annual")
        for key, cells in row_map.items():
            if i >= len(cells):
                continue
            val_text = cells[i]
            if not val_text or val_text == "-" or val_text.strip() == "":
                continue
            if key in ("operating_margin", "roe", "dividend_payout"):
                setattr(fp, key, _parse_float(val_text))
            else:
                setattr(fp, key, _parse_int_kr(val_text))
        result["annual"].append(fp)

    # Build quarterly periods (data cells annual_cols..annual_cols+quarter_cols-1)
    for qi, period_label in enumerate(quarter_headers):
        col_idx = annual_cols + qi  # data cell index (4, 5, 6, 7)
        fp = FinancialPeriod(period=period_label, period_type="quarter")
        for key, cells in row_map.items():
            if col_idx >= len(cells):
                continue
            val_text = cells[col_idx]
            if not val_text or val_text == "-" or val_text.strip() == "":
                continue
            if key in ("operating_margin", "roe", "dividend_payout"):
                setattr(fp, key, _parse_float(val_text))
            else:
                setattr(fp, key, _parse_int_kr(val_text))
        result["quarter"].append(fp)

    return result


def _parse_consensus_table(soup: BeautifulSoup) -> list[FinancialPeriod]:
    """Parse cF1002.aspx consensus table into FinancialPeriod list.

    The table has 12 TD cells per row:
    [0] 회계년도  [1] 매출액(억)  [2] 매출액 YoY%  [3] 영업이익(억)
    [4] 당기순이익(억)  [5] EPS(원)  [6] PER(배)  [7] PBR(배)
    [8] ROE(%)  [9] EV/EBITDA  [10] 부채비율  [11] 재무제표기준

    Rows like: 2024(A), 2025(E), 2026(E) — we only take (E) estimate rows.
    """
    table = soup.select_one("table.gHead01")
    if not table:
        return []

    current_year = datetime.now().year

    results: list[FinancialPeriod] = []
    for tr in table.select("tr"):
        tds = tr.select("td")
        if len(tds) < 9:
            continue

        year_text = tds[0].get_text(strip=True)
        if "(E)" not in year_text:
            continue

        # Extract year: "2025(E)" → "2025/12"
        year_match = re.search(r"(\d{4})", year_text)
        if not year_match:
            continue

        year = int(year_match.group(1))
        if year > current_year:
            continue

        period = f"{year}/12"

        revenue_text = tds[1].get_text(strip=True)
        op_profit_text = tds[3].get_text(strip=True)
        net_income_text = tds[4].get_text(strip=True)
        eps_text = tds[5].get_text(strip=True)
        roe_text = tds[8].get_text(strip=True) if len(tds) > 8 else ""

        fp = FinancialPeriod(period=period, period_type="annual", is_estimate=True)
        fp.revenue = _parse_int_kr(revenue_text) if revenue_text else None
        fp.operating_profit = _parse_int_kr(op_profit_text) if op_profit_text else None
        fp.net_income = _parse_int_kr(net_income_text) if net_income_text else None
        fp.eps = _parse_int_kr(eps_text) if eps_text else None
        fp.roe = _parse_float(roe_text) if roe_text else None

        # Calculate operating margin if we have both
        if fp.revenue and fp.operating_profit and fp.revenue != 0:
            fp.operating_margin = round(fp.operating_profit / fp.revenue * 100, 1)

        results.append(fp)

    return results


async def fetch_stock_financials(stock_code: str) -> dict:
    """Fetch annual + quarterly financials from WiseReport AJAX.

    Returns {"annual": list[FinancialPeriod], "quarter": list[FinancialPeriod]}.
    Both annual and quarterly are in the same HTML response (single table).
    Consensus estimates (E) are fetched from cF1002.aspx and appended.
    24-hour cache.
    """
    now = time.time()
    if (stock_code in _financial_cache.data
            and (now - _financial_cache.last_updated.get(stock_code, 0)) < FINANCIAL_CACHE_TTL):
        return _financial_cache.data[stock_code]

    # 인메모리 미스 시 Redis 복구 시도
    if stock_code not in _financial_cache.data:
        try:
            from app.cache import cache_get
            redis_data = await cache_get(f"stock:{stock_code}:financials")
            if redis_data and isinstance(redis_data, dict):
                _financial_cache.data[stock_code] = {
                    "annual": [FinancialPeriod(**fp) for fp in redis_data.get("annual", [])],
                    "quarter": [FinancialPeriod(**fp) for fp in redis_data.get("quarter", [])],
                }
                _financial_cache.last_updated[stock_code] = now
                return _financial_cache.data[stock_code]
        except Exception:
            pass

    empty = {"annual": [], "quarter": []}

    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            # Fetch actual financials and consensus estimates in parallel
            url_fin = WISEREPORT_FINANCIAL_URL.format(code=stock_code, freq=0)
            url_est = WISEREPORT_CONSENSUS_URL.format(code=stock_code)
            resp_fin, resp_est = await asyncio.gather(
                client.get(url_fin, headers=HEADERS),
                client.get(url_est, headers=HEADERS),
                return_exceptions=True,
            )

        result = empty

        # Parse actual financials
        if not isinstance(resp_fin, Exception) and resp_fin.status_code == 200:
            soup = BeautifulSoup(resp_fin.text, "html.parser")
            result = _parse_financial_table(soup)

        # Parse and append consensus estimates to annual data
        if not isinstance(resp_est, Exception) and resp_est.status_code == 200:
            est_soup = BeautifulSoup(resp_est.text, "html.parser")
            estimates = _parse_consensus_table(est_soup)
            existing_periods = {fp.period for fp in result["annual"]}
            for est in estimates:
                if est.period not in existing_periods and est.revenue is not None:
                    result["annual"].append(est)

        if result["annual"] or result["quarter"]:
            _financial_cache.data[stock_code] = result
            _financial_cache.last_updated[stock_code] = now
            # Redis write-through (TTL=86400초=24시간)
            try:
                from app.cache import cache_set
                from dataclasses import asdict
                serializable = {
                    "annual": [asdict(fp) for fp in result["annual"]],
                    "quarter": [asdict(fp) for fp in result["quarter"]],
                }
                await cache_set(f"stock:{stock_code}:financials", serializable, ttl=86400)
            except Exception:
                pass
            logger.info(
                f"Fetched financials for {stock_code}: "
                f"{len(result['annual'])} annual, {len(result['quarter'])} quarterly periods"
            )

        return result

    except Exception as e:
        logger.error(f"Failed to fetch financials for {stock_code}: {e}")
        return _financial_cache.data.get(stock_code, empty)
