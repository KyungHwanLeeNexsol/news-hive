import io
import logging
import ssl
import urllib.request
import zipfile

from sqlalchemy.orm import Session

from app.models.sector import Sector
from app.models.stock import Stock

logger = logging.getLogger(__name__)

# KIS master file URLs (publicly accessible, no API key needed)
KOSPI_MST_URL = "https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip"
KOSDAQ_MST_URL = "https://new.real.download.dws.co.kr/common/master/kosdaq_code.mst.zip"

# KOSPI field specs for part2 (228 bytes total, 그룹코드 = 3 bytes)
# Derived from KIS sample code with corrected 그룹코드 width
KOSPI_FIELD_SPECS = [
    ("그룹코드", 3), ("시가총액규모", 1), ("지수업종대분류", 4), ("지수업종중분류", 4),
    ("지수업종소분류", 4), ("제조업여부", 1), ("저유동성", 1), ("KRX300", 1),
    ("KOSPI200", 1), ("KOSPI100", 1), ("KOSPI50", 1), ("KRX배당", 1),
    ("KRX자동차", 1), ("KRX반도체", 1), ("KRX바이오", 1), ("KRX은행", 1),
    ("KRX에너지화학", 1), ("KRX철강", 1), ("KRX미디어통신", 1), ("KRX건설", 1),
    ("KRX증권", 1), ("KRX선박", 1), ("KRX보험", 1), ("KRX운송", 1),
    ("KOSPI200중소형주", 1), ("KOSPI200초대형주", 1), ("KOSPI200건설", 1),
    ("KOSPI200중공업", 1), ("KOSPI200IT", 1), ("SPAC", 1), ("KRX300제외", 1),
    ("주식기준가", 9), ("정규시장매매수량단위", 5), ("시간외매매수량단위", 5),
    ("거래정지", 1), ("정리매매", 1), ("관리종목", 1), ("시장경고코드", 2),
    ("시장경고위험예고", 1), ("불성실공시여부", 1), ("백도어상장여부", 1),
    ("매매수량단위변경", 2), ("ETP상품구분코드", 2), ("입회일자", 2),
    ("지수이름코드", 3), ("KOSPI200섹터여부", 1), ("업종코드", 3),
    ("단축코드일련번호", 12), ("증권그룹일련번호", 12), ("일련번호", 8),
    ("표준코드", 15), ("종목영문약명", 21), ("수량주문형태", 2),
    ("배당구분코드", 7), ("ETF관련종목코드", 1), ("발행기관코드", 1),
    ("VC관련", 1), ("SRI관련", 1), ("해외주식관련", 1),
    ("가격변경전기준가", 9), ("조건부자본증권여부", 9), ("기타", 9),
    ("정규시장가격단위", 5), ("시간외가격단위", 9), ("거래량관련", 8),
    ("시가총액관련", 9), ("기타2", 3), ("플래그1", 1), ("플래그2", 1), ("플래그3", 1),
]

# KOSDAQ field specs for part2 (222 bytes total, 그룹코드 = 4 bytes)
KOSDAQ_FIELD_SPECS = [
    ("그룹코드", 4), ("시가총액규모", 1), ("지수업종대분류", 4), ("지수업종중분류", 4),
    ("지수업종소분류", 4), ("벤처기업", 1), ("저유동성", 1), ("KRX300", 1),
    ("KOSTAR", 1), ("KRX자동차", 1), ("KRX반도체", 1), ("KRX바이오", 1),
    ("KRX은행", 1), ("KRX에너지화학", 1), ("KRX철강", 1), ("KRX미디어통신", 1),
    ("KRX건설", 1), ("KRX증권", 1), ("KRX선박", 1), ("KRX보험", 1),
    ("KRX운송", 1), ("KOSDAQ150", 1), ("KRX300제외", 1), ("KRX배당", 1),
    ("기업인수목적회사여부", 1),
    ("주식기준가", 9), ("정규시장매매수량단위", 5), ("시간외매매수량단위", 5),
    ("거래정지", 1), ("정리매매", 1), ("관리종목", 1), ("시장경고코드", 2),
    ("시장경고위험예고", 1), ("불성실공시여부", 1), ("백도어상장여부", 1),
    ("매매수량단위변경", 2), ("ETP상품구분코드", 2), ("입회일자", 2),
    ("지수이름코드", 3), ("KOSDAQ150섹터여부", 1), ("업종코드", 3),
    ("단축코드일련번호", 12), ("증권그룹일련번호", 12), ("일련번호", 8),
    ("표준코드", 15), ("종목영문약명", 21), ("수량주문형태", 2),
    ("배당구분코드", 7), ("ETF관련종목코드", 1), ("발행기관코드", 1),
    ("VC관련", 1), ("해외주식관련", 1),
    ("가격변경전기준가", 9), ("조건부자본증권여부", 9), ("기타", 9),
    ("정규시장가격단위", 5), ("시간외가격단위", 9), ("거래량관련", 8),
    ("시가총액관련", 9), ("기타2", 3), ("플래그1", 1), ("플래그2", 1), ("플래그3", 1),
]

# KRX sector flag → our sector name mapping
KRX_SECTOR_FLAG_MAP = {
    "KRX자동차": "자동차",
    "KRX반도체": "반도체",
    "KRX바이오": "바이오/제약",
    "KRX은행": "금융",
    "KRX에너지화학": "화학",
    "KRX철강": "철강",
    "KRX미디어통신": "통신",
    "KRX건설": "건설/부동산",
    "KRX증권": "금융",
    "KRX선박": "조선",
    "KRX보험": "금융",
    "KRX운송": "운송/물류",
}

# Fallback: match stock name patterns to sectors
KEYWORD_SECTOR_MAP = {
    "반도체": "반도체",
    "전자": "반도체",
    "바이오": "바이오/제약",
    "제약": "바이오/제약",
    "약품": "바이오/제약",
    "건설": "건설/부동산",
    "에너지": "에너지",
    "화학": "화학",
    "철강": "철강",
    "자동차": "자동차",
    "금융": "금융",
    "증권": "금융",
    "은행": "금융",
    "보험": "금융",
    "캐피탈": "금융",
    "통신": "통신",
    "엔터": "엔터테인먼트",
    "게임": "엔터테인먼트",
    "미디어": "엔터테인먼트",
    "조선": "조선",
    "해운": "운송/물류",
    "항공": "방산/항공",
    "방산": "방산/항공",
    "식품": "음식료",
    "음료": "음식료",
    "유통": "유통/소비재",
    "소프트": "IT/소프트웨어",
    "정보": "IT/소프트웨어",
    "전지": "2차전지",
    "배터리": "2차전지",
    "리튬": "2차전지",
    "섬유": "섬유/의류",
    "의류": "섬유/의류",
    "패션": "섬유/의류",
    "물류": "운송/물류",
    "택배": "운송/물류",
    "부동산": "건설/부동산",
}


def _parse_fields(part2: str, field_specs: list[tuple[str, int]]) -> dict[str, str]:
    """Parse fixed-width fields from part2 string."""
    result = {}
    offset = 0
    for name, width in field_specs:
        result[name] = part2[offset:offset + width].strip()
        offset += width
    return result


def _download_and_parse_mst(url: str, market: str) -> list[dict]:
    """Download KIS master file and parse stock codes + names.

    The .mst file format (cp949 encoded, fixed-width):
    KOSPI: each row = variable-length part1 (code+name) + 228 chars part2 (details)
    KOSDAQ: each row = variable-length part1 (code+name) + 222 chars part2 (details)
    """
    tail_len = 228 if market == "KOSPI" else 222
    field_specs = KOSPI_FIELD_SPECS if market == "KOSPI" else KOSDAQ_FIELD_SPECS
    spac_field = "SPAC" if market == "KOSPI" else "기업인수목적회사여부"

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

    try:
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            mst_filename = zf.namelist()[0]
            mst_bytes = zf.read(mst_filename)
    except Exception as e:
        logger.error(f"Failed to extract {market} zip: {e}")
        return []

    stocks = []
    try:
        text = mst_bytes.decode("cp949")
        for row in text.strip().split("\n"):
            row = row.rstrip("\r")
            if len(row) <= tail_len:
                continue

            # Part 1: variable length — 단축코드(9) + 표준코드(12) + 한글명(rest)
            part1 = row[: len(row) - tail_len]
            short_code = part1[0:9].strip()
            name = part1[21:].strip()

            # Part 2: fixed width — parse all fields
            part2 = row[-tail_len:]
            fields = _parse_fields(part2, field_specs)

            grp = fields.get("그룹코드", "")

            # === FILTER: Only keep actual stocks ===
            # Group code: 'ST' = KOSPI stock, 'ST1'/'ST3'/etc = KOSDAQ stock
            # 'EF' = ETF, 'EN' = ETN, 'FS' = foreign stock
            if not grp.startswith("ST"):
                continue

            # Filter: only 6-digit numeric codes
            if not short_code or len(short_code) != 6 or not short_code.isdigit():
                continue
            if not name:
                continue

            # Skip SPAC
            if fields.get(spac_field) == "Y":
                continue

            # Skip by name pattern (additional safety net)
            name_upper = name.upper()
            if any(kw in name_upper for kw in [
                "ETF", "ETN", "KODEX", "TIGER", "KBSTAR", "ARIRANG",
                "HANARO", "SOL ", "ACE ", "KOSEF", "KINDEX", "스팩",
                "PLUS ", "RISE ", "TIMEFOLIO",
            ]):
                continue

            # Determine sector via KRX flags
            krx_sectors = []
            for flag_name, sector_name in KRX_SECTOR_FLAG_MAP.items():
                if fields.get(flag_name) == "Y":
                    krx_sectors.append(sector_name)

            stocks.append({
                "code": short_code,
                "name": name,
                "market": market,
                "krx_sectors": krx_sectors,
            })
    except Exception as e:
        logger.error(f"Failed to parse {market} master file: {e}")
        return []

    logger.info(f"Parsed {len(stocks)} stocks from {market} master file")
    return stocks


def _map_sector(stock_data: dict, sector_lookup: dict[str, int]) -> int | None:
    """Map stock to our sector using KRX flags first, then name keywords."""
    # Try KRX sector flags (most reliable)
    for sector_name in stock_data.get("krx_sectors", []):
        if sector_name in sector_lookup:
            return sector_lookup[sector_name]

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

    # If force, clear all existing non-custom stocks and re-seed
    if force:
        deleted = db.query(Stock).delete()
        db.commit()
        logger.info(f"Cleared {deleted} existing stocks for re-seed.")

    # Fetch from KIS master files
    all_stocks: list[dict] = []
    for market, url in [("KOSPI", KOSPI_MST_URL), ("KOSDAQ", KOSDAQ_MST_URL)]:
        fetched = _download_and_parse_mst(url, market)
        all_stocks.extend(fetched)

    if not all_stocks:
        logger.warning("No stocks fetched from KIS master files.")
        return 0

    logger.info(f"Total stocks fetched: {len(all_stocks)}")

    # Deduplicate by code
    existing_codes = {s.stock_code for s in db.query(Stock.stock_code).all()}
    added = 0
    sector_stats: dict[str, int] = {}

    for stock_data in all_stocks:
        if stock_data["code"] in existing_codes:
            continue

        sector_id = _map_sector(stock_data, sector_lookup)
        if not sector_id:
            sector_id = fallback_sector_id

        # Track stats
        sector_name = next(
            (s.name for s in sectors if s.id == sector_id), "unknown"
        )
        sector_stats[sector_name] = sector_stats.get(sector_name, 0) + 1

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
    logger.info(f"Seeded {added} stocks. Distribution: {sector_stats}")
    return added
