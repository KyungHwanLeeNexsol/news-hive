"""DART (전자공시) disclosure crawler.

Uses DART Open API (opendart.fss.or.kr) to fetch recent corporate disclosures
and map them to stocks in the database.
"""

import logging
from datetime import datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models.disclosure import Disclosure
from app.models.stock import Stock

logger = logging.getLogger(__name__)

DART_OPEN_API_URL = "https://opendart.fss.or.kr/api/list.json"

# DART corp_cls → market label
_CORP_CLS_MAP = {
    "Y": "KOSPI",   # 유가증권시장
    "K": "KOSDAQ",  # 코스닥시장
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


def _classify_report_type(report_name: str) -> str:
    """Classify a DART report name into a short type label."""
    for pattern, label in _REPORT_TYPE_PATTERNS:
        if pattern in report_name:
            return label
    return "기타공시"


async def fetch_dart_disclosures(
    db: Session,
    days: int = 3,
) -> int:
    """Fetch recent DART disclosures via DART Open API and save to database.

    Args:
        db: Database session
        days: How many days back to fetch (default 3)

    Returns:
        Number of new disclosures saved
    """
    if not settings.DART_API_KEY:
        logger.warning("DART_API_KEY not set, skipping disclosure fetch")
        return 0

    # Build corp_name / stock_code → stock_id mapping
    stocks = db.query(Stock).filter(Stock.stock_code.isnot(None)).all()
    name_to_id: dict[str, int] = {s.name: s.id for s in stocks}
    code_to_id: dict[str, int] = {s.stock_code.strip(): s.id for s in stocks}
    logger.info(f"DART: {len(name_to_id)} stock names for mapping")

    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    bgn_de = start_date.strftime("%Y%m%d")
    end_de = end_date.strftime("%Y%m%d")
    logger.info(f"DART: fetching disclosures from {bgn_de} to {end_de}")

    # Pre-load existing rcept_no set to skip duplicates
    existing_rcepts: set[str] = {row[0] for row in db.query(Disclosure.rcept_no).all()}
    logger.info(f"DART: {len(existing_rcepts)} existing disclosures in DB")

    saved = 0
    name_matched = 0
    page_no = 1
    page_count = 100

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            params = {
                "crtfc_key": settings.DART_API_KEY,
                "bgn_de": bgn_de,
                "end_de": end_de,
                "sort": "date",
                "sort_mth": "desc",
                "page_no": str(page_no),
                "page_count": str(page_count),
            }

            try:
                resp = await client.get(DART_OPEN_API_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.error(f"DART API request failed (page {page_no}): {e}")
                break

            status = data.get("status", "")
            if status == "013":
                # No more data (정상 종료)
                break
            if status != "000":
                logger.warning(
                    f"DART API error: status={status}, "
                    f"message={data.get('message', '')}"
                )
                break

            items = data.get("list", [])
            if not items:
                break

            total_page = data.get("total_page", 1)
            logger.info(f"DART: page {page_no}/{total_page}, {len(items)} items")

            for item in items:
                # KOSPI/KOSDAQ만 처리
                corp_cls = item.get("corp_cls", "")
                if corp_cls not in _CORP_CLS_MAP:
                    continue

                rcept_no = item.get("rcept_no", "")
                if not rcept_no or rcept_no in existing_rcepts:
                    continue

                corp_name = item.get("corp_name", "")
                stock_code = (item.get("stock_code") or "").strip()
                report_name = item.get("report_nm", "")
                rcept_dt = item.get("rcept_dt", "")
                corp_code = item.get("corp_code", "")

                # stock_id 매핑: 종목코드 우선, 없으면 회사명
                stock_id = code_to_id.get(stock_code) or name_to_id.get(corp_name)
                if stock_id:
                    name_matched += 1

                report_type = _classify_report_type(report_name)

                disclosure = Disclosure(
                    corp_code=corp_code,
                    corp_name=corp_name,
                    stock_code=stock_code or None,
                    stock_id=stock_id,
                    report_name=report_name,
                    report_type=report_type,
                    rcept_no=rcept_no,
                    rcept_dt=rcept_dt,
                    url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
                )
                db.add(disclosure)
                existing_rcepts.add(rcept_no)
                saved += 1

            if page_no >= total_page:
                break
            page_no += 1

    if saved:
        db.commit()
        logger.info(
            f"Saved {saved} new DART disclosures "
            f"({name_matched} matched to stocks)"
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
