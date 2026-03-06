"""DART (전자공시) disclosure crawler.

Scrapes the DART website (dart.fss.or.kr) to fetch recent corporate
disclosures and map them to stocks in the database.
No API key required — uses the public search page.
"""

import logging
import re
from datetime import datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from app.models.disclosure import Disclosure
from app.models.stock import Stock

logger = logging.getLogger(__name__)

DART_SEARCH_URL = "https://dart.fss.or.kr/dsab007/detailSearch.ax"
DART_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/x-www-form-urlencoded",
    "Referer": "https://dart.fss.or.kr/dsab007/main.do",
    "X-Requested-With": "XMLHttpRequest",
}

# Report type classification based on common report name patterns
_REPORT_TYPE_PATTERNS: list[tuple[str, str]] = [
    # 정기공시
    ("사업보고서", "정기공시"),
    ("반기보고서", "정기공시"),
    ("분기보고서", "정기공시"),
    ("감사보고서", "정기공시"),
    # 주요사항보고
    ("주요사항보고서", "주요사항보고"),
    ("매출액또는손익구조", "실적변동"),
    ("소송", "주요사항보고"),
    ("주식병합", "주요사항보고"),
    ("주식분할", "주요사항보고"),
    ("투자판단관련", "주요사항보고"),
    # 발행공시
    ("유상증자", "발행공시"),
    ("무상증자", "발행공시"),
    ("전환사채", "발행공시"),
    ("신주인수권", "발행공시"),
    ("교환사채", "발행공시"),
    ("파생결합증권", "발행공시"),
    ("파생결합사채", "발행공시"),
    ("일괄신고추가서류", "발행공시"),
    ("증권신고서", "발행공시"),
    ("청정신고서", "발행공시"),
    # 지분공시
    ("주식등의대량보유", "지분공시"),
    ("임원ㆍ주요주주", "지분공시"),
    ("최대주주", "지분공시"),
    ("자기주식", "지분공시"),
    ("타법인주식", "지분공시"),
    # 기업지배구조
    ("합병", "기업지배구조"),
    ("분할", "기업지배구조"),
    ("주주총회", "기업지배구조"),
    ("의결권", "기업지배구조"),
    ("배당", "기업지배구조"),
    # 기업집단공시
    ("대규모기업집단", "기업집단공시"),
    ("기업집단", "기업집단공시"),
    # 기업지배구조 (추가)
    ("사외이사", "기업지배구조"),
    ("대표이사", "기업지배구조"),
    ("임원", "기업지배구조"),
    # 기타공시
    ("해외투자", "기타공시"),
    ("공개매수", "기타공시"),
    ("자산양수도", "기타공시"),
    ("영업양수도", "기타공시"),
    ("효력발생", "발행공시"),
    ("투자설명서", "발행공시"),
    ("증권발행실적", "발행공시"),
    ("중대재해", "기타공시"),
    ("생산중단", "주요사항보고"),
    ("영업정지", "주요사항보고"),
    ("기업가치제고", "기타공시"),
    ("단일판매", "주요사항보고"),
    ("단일공급", "주요사항보고"),
    ("공급계약", "주요사항보고"),
]

# Market type CSS class → readable label
_MARKET_MAP = {
    "kospi": "KOSPI",
    "kosdaq": "KOSDAQ",
}


def _classify_report_type(report_name: str) -> str:
    """Classify a DART report name into a short type label."""
    for pattern, label in _REPORT_TYPE_PATTERNS:
        if pattern in report_name:
            return label
    return "기타공시"


def _parse_dart_html(html: str) -> list[dict]:
    """Parse DART search result HTML into disclosure dicts."""
    items = []
    rows = re.findall(r"<tr>(.*?)</tr>", html, re.DOTALL)

    for row in rows:
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        if len(tds) < 5:
            continue

        # Market type (kospi/kosdaq/etc)
        market_match = re.search(r'class="tagCom_(\w+)"', tds[1])
        market_cls = market_match.group(1) if market_match else ""
        # Only keep KOSPI and KOSDAQ
        if market_cls not in _MARKET_MAP:
            continue

        # Corp code
        corp_code_match = re.search(r"openCorpInfoNew\('(\d+)'", tds[1])
        corp_code = corp_code_match.group(1) if corp_code_match else ""

        # Corp name
        corp_name_match = re.search(
            r"openCorpInfoNew.*?>\s*([^<]+?)\s*</a>", tds[1], re.DOTALL
        )
        corp_name = corp_name_match.group(1).strip() if corp_name_match else ""

        # Report name + rcept_no
        report_match = re.search(
            r'rcpNo=(\d+).*?>\s*(.+?)\s*</a>', tds[2], re.DOTALL
        )
        if not report_match:
            continue
        rcept_no = report_match.group(1)
        # Clean report name (remove extra whitespace, newlines)
        report_name = re.sub(r"\s+", " ", report_match.group(2)).strip()

        # Date (2026.03.06 → 20260306)
        date_match = re.search(r"(\d{4})\.(\d{2})\.(\d{2})", tds[4])
        rcept_dt = (
            f"{date_match.group(1)}{date_match.group(2)}{date_match.group(3)}"
            if date_match
            else ""
        )

        items.append({
            "corp_code": corp_code,
            "corp_name": corp_name,
            "report_name": report_name,
            "rcept_no": rcept_no,
            "rcept_dt": rcept_dt,
            "market": _MARKET_MAP.get(market_cls, ""),
        })

    return items


def _parse_total_pages(html: str) -> int:
    """Extract total page count from DART pagination."""
    # Pattern: [1/271] [총 4,060건]
    m = re.search(r"\[\d+/(\d+)\]", html)
    return int(m.group(1)) if m else 1


async def fetch_dart_disclosures(
    db: Session,
    days: int = 3,
) -> int:
    """Fetch recent DART disclosures via web scraping and save to database.

    Args:
        db: Database session
        days: How many days back to fetch (default 3)

    Returns:
        Number of new disclosures saved
    """
    # Build corp_name → stock_id mapping from DB
    stocks = db.query(Stock).filter(Stock.stock_code.isnot(None)).all()
    name_to_id: dict[str, int] = {s.name: s.id for s in stocks}
    logger.info(f"DART: {len(name_to_id)} stock names for mapping")

    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    bgn_de = start_date.strftime("%Y%m%d")
    end_de = end_date.strftime("%Y%m%d")
    logger.info(f"DART: scraping disclosures from {bgn_de} to {end_de}")

    # Pre-load existing rcept_no set
    existing_rcepts: set[str] = set()
    for row in db.query(Disclosure.rcept_no).all():
        existing_rcepts.add(row[0])
    logger.info(f"DART: {len(existing_rcepts)} existing disclosures in DB")

    saved = 0
    name_matched = 0
    page_no = 1
    max_results = 100  # items per page

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        # Visit main page first to establish session cookies
        try:
            await client.get(
                "https://dart.fss.or.kr/dsab007/main.do",
                headers={"User-Agent": DART_HEADERS["User-Agent"]},
            )
        except Exception:
            pass  # Non-critical, continue with search

        while True:
            form_data = {
                "currentPage": str(page_no),
                "maxResults": str(max_results),
                "maxLinks": "5",
                "sort": "date",
                "series": "desc",
                "startDate": bgn_de,
                "endDate": end_de,
                "textCrpNm": "",
                "textCrpCik": "",
            }

            try:
                resp = await client.post(
                    DART_SEARCH_URL,
                    data=form_data,
                    headers=DART_HEADERS,
                )
                resp.raise_for_status()
                html = resp.text
            except Exception as e:
                logger.error(f"DART scrape failed (page {page_no}): {e}")
                break

            items = _parse_dart_html(html)
            if not items:
                if page_no == 1:
                    logger.info("DART: no disclosures found")
                break

            total_pages = _parse_total_pages(html)
            logger.info(
                f"DART: page {page_no}/{total_pages}, "
                f"{len(items)} items (KOSPI+KOSDAQ only)"
            )

            for item in items:
                rcept_no = item["rcept_no"]
                if rcept_no in existing_rcepts:
                    continue

                corp_name = item["corp_name"]
                stock_id = name_to_id.get(corp_name)
                if stock_id:
                    name_matched += 1

                report_name = item["report_name"]
                report_type = _classify_report_type(report_name)

                disclosure = Disclosure(
                    corp_code=item["corp_code"],
                    corp_name=corp_name,
                    stock_code=None,  # web scraping doesn't provide stock_code
                    stock_id=stock_id,
                    report_name=report_name,
                    report_type=report_type,
                    rcept_no=rcept_no,
                    rcept_dt=item["rcept_dt"],
                    url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
                )
                db.add(disclosure)
                existing_rcepts.add(rcept_no)
                saved += 1

            if page_no >= total_pages:
                break
            page_no += 1

    if saved:
        db.commit()
        logger.info(
            f"Saved {saved} new DART disclosures "
            f"({name_matched} name-matched to stocks)"
        )
    else:
        logger.info("No new DART disclosures found")

    return saved


def backfill_disclosure_stock_ids(db: Session) -> int:
    """Re-link existing disclosures that have NULL stock_id."""
    stocks = db.query(Stock).filter(Stock.stock_code.isnot(None)).all()
    code_to_id = {s.stock_code.strip(): s.id for s in stocks}
    name_to_id = {s.name: s.id for s in stocks}

    unlinked = db.query(Disclosure).filter(Disclosure.stock_id.is_(None)).all()
    if not unlinked:
        return 0

    fixed = 0
    for d in unlinked:
        stock_id = None
        if d.stock_code:
            stock_id = code_to_id.get(d.stock_code.strip())
        if not stock_id and d.corp_name:
            stock_id = name_to_id.get(d.corp_name.strip())
        if stock_id:
            d.stock_id = stock_id
            fixed += 1

    if fixed:
        db.commit()
        logger.info(f"Backfilled stock_id for {fixed}/{len(unlinked)} unlinked disclosures")

    return fixed


def backfill_disclosure_report_types(db: Session) -> int:
    """Re-classify report_type for disclosures that have NULL report_type."""
    untyped = db.query(Disclosure).filter(Disclosure.report_type.is_(None)).all()
    if not untyped:
        return 0

    fixed = 0
    for d in untyped:
        report_type = _classify_report_type(d.report_name)
        if report_type:
            d.report_type = report_type
            fixed += 1

    if fixed:
        db.commit()
        logger.info(f"Backfilled report_type for {fixed}/{len(untyped)} disclosures")

    return fixed
