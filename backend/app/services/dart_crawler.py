"""DART (전자공시) disclosure crawler.

Uses the DART Open API to fetch recent corporate disclosures and map them
to stocks in the database by stock_code.

API docs: https://opendart.fss.or.kr/guide/main.do
"""

import logging
from datetime import datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models.disclosure import Disclosure
from app.models.stock import Stock

logger = logging.getLogger(__name__)

DART_API_BASE = "https://opendart.fss.or.kr/api"

# Report type classification based on common report name patterns
_REPORT_TYPE_PATTERNS: list[tuple[str, str]] = [
    ("유상증자", "유상증자"),
    ("무상증자", "무상증자"),
    ("전환사채", "전환사채"),
    ("신주인수권", "신주인수권"),
    ("합병", "합병"),
    ("분할", "분할"),
    ("주식등의대량보유", "대량보유"),
    ("임원ㆍ주요주주", "임원변동"),
    ("사업보고서", "사업보고서"),
    ("반기보고서", "반기보고서"),
    ("분기보고서", "분기보고서"),
    ("감사보고서", "감사보고서"),
    ("매출액또는손익구조", "실적변동"),
    ("주요사항보고서", "주요사항"),
    ("자기주식", "자사주"),
    ("배당", "배당"),
    ("소송", "소송"),
    ("해외투자", "해외투자"),
    ("타법인주식", "타법인투자"),
    ("최대주주", "최대주주변경"),
]


def _classify_report_type(report_name: str) -> str | None:
    """Classify a DART report name into a short type label."""
    for pattern, label in _REPORT_TYPE_PATTERNS:
        if pattern in report_name:
            return label
    return None


async def fetch_dart_disclosures(
    db: Session,
    days: int = 3,
) -> int:
    """Fetch recent DART disclosures and save to database.

    Args:
        db: Database session
        days: How many days back to fetch (default 3)

    Returns:
        Number of new disclosures saved
    """
    if not settings.DART_API_KEY:
        logger.info("DART_API_KEY not set, skipping disclosure fetch")
        return 0

    # Build stock_code → stock_id mapping from DB
    stocks = db.query(Stock).filter(Stock.stock_code.isnot(None)).all()
    code_to_id: dict[str, int] = {s.stock_code: s.id for s in stocks}
    logger.info(f"DART: {len(code_to_id)} stocks in DB for mapping")

    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    bgn_de = start_date.strftime("%Y%m%d")
    end_de = end_date.strftime("%Y%m%d")
    logger.info(f"DART: fetching disclosures from {bgn_de} to {end_de}")

    # Pre-load existing rcept_no set to avoid per-item DB queries
    existing_rcepts: set[str] = set()
    existing_rows = db.query(Disclosure.rcept_no).all()
    for row in existing_rows:
        existing_rcepts.add(row[0])
    logger.info(f"DART: {len(existing_rcepts)} existing disclosures in DB")

    saved = 0
    matched = 0
    page_no = 1
    max_pages = 5  # 500 disclosures max per run

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Fetch listed companies only (Y=KOSPI, K=KOSDAQ)
        for corp_cls in ["Y", "K"]:
            page_no = 1
            while page_no <= max_pages:
                params = {
                    "crtfc_key": settings.DART_API_KEY,
                    "bgn_de": bgn_de,
                    "end_de": end_de,
                    "corp_cls": corp_cls,
                    "page_no": str(page_no),
                    "page_count": "100",
                }

                try:
                    resp = await client.get(f"{DART_API_BASE}/list.json", params=params)
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as e:
                    logger.error(f"DART API request failed (cls={corp_cls}, page {page_no}): {e}")
                    break

                status = data.get("status", "")
                if status == "013":
                    logger.info(f"DART: no data for corp_cls={corp_cls}")
                    break
                if status != "000":
                    logger.warning(f"DART API status {status}: {data.get('message', '')}")
                    break

                items = data.get("list", [])
                if not items:
                    break

                logger.info(f"DART: cls={corp_cls} page {page_no}, {len(items)} items, total_page={data.get('total_page')}")

                for item in items:
                    rcept_no = item.get("rcept_no", "")
                    if not rcept_no or rcept_no in existing_rcepts:
                        continue

                    stock_code = item.get("stock_code", "").strip()
                    stock_id = code_to_id.get(stock_code) if stock_code else None
                    if stock_id:
                        matched += 1

                    report_name = item.get("report_nm", "")
                    report_type = _classify_report_type(report_name)

                    disclosure = Disclosure(
                        corp_code=item.get("corp_code", ""),
                        corp_name=item.get("corp_name", ""),
                        stock_code=stock_code or None,
                        stock_id=stock_id,
                        report_name=report_name,
                        report_type=report_type,
                        rcept_no=rcept_no,
                        rcept_dt=item.get("rcept_dt", ""),
                        url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
                    )
                    db.add(disclosure)
                    existing_rcepts.add(rcept_no)
                    saved += 1

                total_page = data.get("total_page", 1)
                if page_no >= total_page:
                    break
                page_no += 1

    if saved:
        db.commit()
        logger.info(f"Saved {saved} new DART disclosures ({matched} matched to stocks)")
    else:
        logger.info("No new DART disclosures found")

    return saved
