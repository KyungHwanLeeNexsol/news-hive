import logging

import httpx
from sqlalchemy.orm import Session

from app.models.sector import Sector
from app.models.stock import Stock

logger = logging.getLogger(__name__)

# KRX sector name → our sector name mapping
KRX_SECTOR_MAP = {
    "음식료품": "음식료",
    "섬유의복": "섬유/의류",
    "종이목재": "기계/장비",
    "화학": "화학",
    "의약품": "바이오/제약",
    "비금속광물": "화학",
    "철강금속": "철강",
    "기계": "기계/장비",
    "전기전자": "반도체",
    "의료정밀": "바이오/제약",
    "운수장비": "자동차",
    "유통업": "유통/소비재",
    "전기가스업": "에너지",
    "건설업": "건설/부동산",
    "운수창고업": "운송/물류",
    "통신업": "통신",
    "금융업": "금융",
    "은행": "금융",
    "증권": "금융",
    "보험": "금융",
    "서비스업": "IT/소프트웨어",
    "제조업": "기계/장비",
    "기타제조업": "기계/장비",
    "농업,임업및어업": "음식료",
    "광업": "에너지",
    "전문,과학및기술서비스업": "IT/소프트웨어",
    "정보통신업": "IT/소프트웨어",
    "소프트웨어": "IT/소프트웨어",
    "IT부품": "반도체",
    "IT서비스": "IT/소프트웨어",
    "반도체": "반도체",
    "디지털컨텐츠": "엔터테인먼트",
    "방송서비스": "엔터테인먼트",
    "인터넷": "IT/소프트웨어",
    "게임": "엔터테인먼트",
    "통신장비": "통신",
    "통신서비스": "통신",
    "오락,문화": "엔터테인먼트",
    "숙박,음식": "유통/소비재",
    "교육서비스업": "유통/소비재",
    "출판,매체복제": "엔터테인먼트",
    "건설": "건설/부동산",
    "금속": "철강",
    "화학물": "화학",
    "기타서비스": "유통/소비재",
    "운송": "운송/물류",
    "유틸리티": "에너지",
    "기타금융": "금융",
    "손해보험": "금융",
    "생명보험": "금융",
    "창투사": "금융",
    "부동산": "건설/부동산",
    "기계,장비": "기계/장비",
    "전기,전자": "반도체",
    "의료,정밀기기": "바이오/제약",
    "운송장비,부품": "자동차",
    "비금속": "화학",
    "섬유,의류": "섬유/의류",
    "음식료,담배": "음식료",
    "종이,목재": "기계/장비",
    "유통": "유통/소비재",
    "전기,가스,수도": "에너지",
    "제약": "바이오/제약",
}


def _fetch_krx_stocks(market: str) -> list[dict]:
    """Fetch stock listing from KRX open data."""
    url = "http://data.krx.co.kr/comm/bldAttend498/getJsonData.cmd"

    if market == "KOSPI":
        bld = "dbms/MDC/STAT/standard/MDCSTAT01501"
        mkt_id = "STK"
    else:
        bld = "dbms/MDC/STAT/standard/MDCSTAT01501"
        mkt_id = "KSQ"

    payload = {
        "bld": bld,
        "mktId": mkt_id,
        "share": "1",
        "csvxls_is498": "false",
    }
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "http://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId=MDC0201020101",
    }

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(url, data=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error(f"Failed to fetch KRX {market} data: {e}")
        return []

    stocks = []
    for item in data.get("OutBlock_1", []):
        stock_code = item.get("ISU_SRT_CD", "").strip()
        name = item.get("ISU_ABBRV", "").strip()
        sector_name = item.get("IDX_IND_NM", "").strip()

        if not stock_code or not name:
            continue
        # Skip ETF, ETN, etc (codes starting with non-digits or special)
        if not stock_code[:1].isdigit():
            continue

        stocks.append({
            "code": stock_code,
            "name": name,
            "sector": sector_name,
            "market": market,
        })

    return stocks


def _map_sector(krx_sector: str, sector_lookup: dict[str, int]) -> int | None:
    """Map KRX sector name to our sector ID."""
    mapped_name = KRX_SECTOR_MAP.get(krx_sector)
    if mapped_name and mapped_name in sector_lookup:
        return sector_lookup[mapped_name]

    # Try partial matching
    for krx_key, our_name in KRX_SECTOR_MAP.items():
        if krx_key in krx_sector or krx_sector in krx_key:
            if our_name in sector_lookup:
                return sector_lookup[our_name]

    return None


def seed_all_stocks(db: Session, force: bool = False) -> int:
    """Fetch all KOSPI/KOSDAQ stocks from KRX and insert into DB."""
    existing_count = db.query(Stock).count()
    if not force and existing_count > 100:
        logger.info(f"Already have {existing_count} stocks, skipping seed.")
        return 0

    # Build sector name → id lookup
    sectors = db.query(Sector).all()
    sector_lookup = {s.name: s.id for s in sectors}

    # Default fallback sector
    fallback_sector_id = sector_lookup.get("기계/장비")
    if not fallback_sector_id and sectors:
        fallback_sector_id = sectors[0].id

    if not fallback_sector_id:
        logger.error("No sectors found. Run seed_sectors first.")
        return 0

    # Fetch from KRX
    all_stocks: list[dict] = []
    for market in ["KOSPI", "KOSDAQ"]:
        fetched = _fetch_krx_stocks(market)
        logger.info(f"Fetched {len(fetched)} stocks from {market}")
        all_stocks.extend(fetched)

    if not all_stocks:
        logger.warning("No stocks fetched from KRX.")
        return 0

    # Deduplicate by code
    existing_codes = {s.stock_code for s in db.query(Stock).all()}
    added = 0

    for stock_data in all_stocks:
        if stock_data["code"] in existing_codes:
            continue

        sector_id = _map_sector(stock_data["sector"], sector_lookup)
        if not sector_id:
            sector_id = fallback_sector_id

        stock = Stock(
            sector_id=sector_id,
            name=stock_data["name"],
            stock_code=stock_data["code"],
            keywords=None,
        )
        db.add(stock)
        existing_codes.add(stock_data["code"])
        added += 1

    db.commit()
    logger.info(f"Seeded {added} stocks from KRX.")
    return added
