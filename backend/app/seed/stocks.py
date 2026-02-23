import io
import logging
import ssl
import tempfile
import urllib.request
import zipfile

from sqlalchemy.orm import Session

from app.models.sector import Sector
from app.models.stock import Stock

logger = logging.getLogger(__name__)

# KIS master file URLs (publicly accessible, no API key needed)
KOSPI_MST_URL = "https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip"
KOSDAQ_MST_URL = "https://new.real.download.dws.co.kr/common/master/kosdaq_code.mst.zip"

# Sector code mapping — KIS 지수업종 대분류 코드 (2자리) → our sector name
# These codes come from the master file's fixed-width "지수업종대분류" field
SECTOR_CODE_MAP_KOSPI = {
    "01": "음식료",
    "02": "섬유/의류",
    "03": "기계/장비",       # 종이목재
    "04": "화학",
    "05": "바이오/제약",     # 의약품
    "06": "화학",            # 비금속광물
    "07": "철강",            # 철강금속
    "08": "기계/장비",       # 기계
    "09": "반도체",          # 전기전자
    "10": "바이오/제약",     # 의료정밀
    "11": "자동차",          # 운수장비
    "12": "유통/소비재",     # 유통업
    "13": "에너지",          # 전기가스업
    "14": "건설/부동산",     # 건설업
    "15": "운송/물류",       # 운수창고업
    "16": "통신",            # 통신업
    "17": "금융",            # 금융업
    "18": "금융",            # 은행
    "19": "금융",            # 증권
    "20": "금융",            # 보험
    "21": "IT/소프트웨어",   # 서비스업
    "22": "기계/장비",       # 제조업
}

# Fallback: match stock name patterns to sectors
KEYWORD_SECTOR_MAP = {
    "반도체": "반도체",
    "전자": "반도체",
    "바이오": "바이오/제약",
    "제약": "바이오/제약",
    "건설": "건설/부동산",
    "에너지": "에너지",
    "화학": "화학",
    "철강": "철강",
    "자동차": "자동차",
    "금융": "금융",
    "증권": "금융",
    "은행": "금융",
    "보험": "금융",
    "통신": "통신",
    "엔터": "엔터테인먼트",
    "게임": "엔터테인먼트",
    "미디어": "엔터테인먼트",
}


def _download_and_parse_mst(url: str, market: str) -> list[dict]:
    """Download KIS master file and parse stock codes + names.

    The .mst file format (cp949 encoded, fixed-width):
    KOSPI: each row = variable-length part1 (code+name) + 228 chars part2 (details)
    KOSDAQ: each row = variable-length part1 (code+name) + 222 chars part2 (details)
    """
    tail_len = 228 if market == "KOSPI" else 222

    try:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, context=ssl_ctx, timeout=30) as resp:
            zip_data = resp.read()
    except Exception as e:
        logger.error(f"Failed to download {market} master file: {e}")
        return []

    # Extract zip in memory
    try:
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            mst_filename = zf.namelist()[0]
            mst_bytes = zf.read(mst_filename)
    except Exception as e:
        logger.error(f"Failed to extract {market} zip: {e}")
        return []

    # Parse the mst file
    stocks = []
    try:
        text = mst_bytes.decode("cp949")
        for row in text.strip().split("\n"):
            if len(row) <= tail_len:
                continue

            # Part 1: variable length — 단축코드(9) + 표준코드(12) + 한글명(rest)
            part1 = row[: len(row) - tail_len]
            short_code = part1[0:9].strip()
            name = part1[21:].strip()

            # Part 2: fixed width — extract sector code
            part2 = row[-tail_len:]
            # group_code(2) + cap_size(1) + sector_large(4) + sector_mid(4) + sector_small(4)
            sector_large = part2[3:7].strip()

            # Filter: only actual stocks (6-digit numeric codes)
            if not short_code or len(short_code) != 6:
                continue
            if not short_code.isdigit():
                continue
            if not name:
                continue

            stocks.append({
                "code": short_code,
                "name": name,
                "sector_code": sector_large,
                "market": market,
            })
    except Exception as e:
        logger.error(f"Failed to parse {market} master file: {e}")
        return []

    return stocks


def _map_sector(stock_data: dict, sector_lookup: dict[str, int]) -> int | None:
    """Map stock to our sector using sector code and name keywords."""
    # Try sector code mapping
    code = stock_data.get("sector_code", "")
    if code and code[:2] in SECTOR_CODE_MAP_KOSPI:
        mapped_name = SECTOR_CODE_MAP_KOSPI[code[:2]]
        if mapped_name in sector_lookup:
            return sector_lookup[mapped_name]

    # Try keyword matching on stock name
    name = stock_data.get("name", "")
    for keyword, sector_name in KEYWORD_SECTOR_MAP.items():
        if keyword in name:
            if sector_name in sector_lookup:
                return sector_lookup[sector_name]

    return None


def seed_all_stocks(db: Session, force: bool = False) -> int:
    """Fetch all KOSPI/KOSDAQ stocks from KIS master files and insert into DB."""
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

    # Fetch from KIS master files
    all_stocks: list[dict] = []
    for market, url in [("KOSPI", KOSPI_MST_URL), ("KOSDAQ", KOSDAQ_MST_URL)]:
        fetched = _download_and_parse_mst(url, market)
        logger.info(f"Fetched {len(fetched)} stocks from {market}")
        all_stocks.extend(fetched)

    if not all_stocks:
        logger.warning("No stocks fetched from KIS master files.")
        return 0

    # Deduplicate by code
    existing_codes = {s.stock_code for s in db.query(Stock.stock_code).all()}
    added = 0

    for stock_data in all_stocks:
        if stock_data["code"] in existing_codes:
            continue

        sector_id = _map_sector(stock_data, sector_lookup)
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
    logger.info(f"Seeded {added} stocks from KIS master files.")
    return added
