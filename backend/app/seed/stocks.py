import io
import logging
import ssl
import time
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



def _parse_fields(part2: bytes, field_specs: list[tuple[str, int]]) -> dict[str, str]:
    """Parse fixed-width fields from part2 BYTES (all ASCII)."""
    result = {}
    offset = 0
    for name, width in field_specs:
        result[name] = part2[offset:offset + width].decode("ascii", errors="replace").strip()
        offset += width
    return result


# ETF/ETN/ETP 브랜드명 (대문자로 비교)
_ETP_NAME_KEYWORDS = [
    "ETF", "ETN", "ELW",
    "KODEX", "TIGER", "KBSTAR", "ARIRANG", "HANARO",
    "SOL ", "ACE ", "KOSEF", "KINDEX", "TIMEFOLIO",
    "PLUS ", "RISE ", "히어로즈",
    "1Q ", "마이티",
    "스팩",
    # 상품형 키워드
    "액티브", "패시브", "레버리지", "인버스", "선물", "옵션",
    "채권", "국고", "통안", "회사채", "금리",
    "인덱스", "배당성장", "고배당",
    "(H)", "(합성)", "(UH)",
]


def _download_and_parse_mst(url: str, market: str) -> list[dict]:
    """Download KIS master file and parse stock codes + names.

    The .mst file format (cp949 encoded, BYTE-based fixed-width):
    KOSPI: each row = variable-length part1 (code+name) + 228 BYTES part2
    KOSDAQ: each row = variable-length part1 (code+name) + 222 BYTES part2

    IMPORTANT: part2 field widths are in BYTES. Since cp949 Korean chars are
    2 bytes each, we must parse part2 as raw bytes, not decoded characters.
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
        # Parse line by line in RAW BYTES to ensure correct field alignment
        for line_bytes in mst_bytes.split(b"\n"):
            line_bytes = line_bytes.rstrip(b"\r")
            if len(line_bytes) <= tail_len:
                continue

            # Part 2: last tail_len BYTES (all ASCII flags/numbers)
            part2_bytes = line_bytes[-tail_len:]
            fields = _parse_fields(part2_bytes, field_specs)

            # Part 1: remaining bytes — 단축코드(9B) + 표준코드(12B) + 한글명(cp949)
            part1_bytes = line_bytes[:-tail_len]
            short_code = part1_bytes[0:9].decode("ascii", errors="replace").strip()
            name = part1_bytes[21:].decode("cp949", errors="replace").strip()

            grp = fields.get("그룹코드", "")

            # === FILTER 1: Group code ===
            # 'ST' = stock, 'EF' = ETF, 'EN' = ETN, 'EW' = ELW, 'BC' = BC
            if not grp.startswith("ST"):
                continue

            # === FILTER 2: ETP상품구분코드 ===
            # Non-empty = ETP product (ETF/ETN/ELW)
            etp_code = fields.get("ETP상품구분코드", "")
            if etp_code and etp_code != "00":
                continue

            # === FILTER 3: 6-digit numeric code ===
            if not short_code or len(short_code) != 6 or not short_code.isdigit():
                continue
            if not name:
                continue

            # === FILTER 4: SPAC ===
            if fields.get(spac_field) == "Y":
                continue

            # === FILTER 5: Name pattern (safety net) ===
            name_upper = name.upper()
            if any(kw in name_upper for kw in _ETP_NAME_KEYWORDS):
                continue

            stocks.append({
                "code": short_code,
                "name": name,
                "market": market,
            })
    except Exception as e:
        logger.error(f"Failed to parse {market} master file: {e}")
        return []

    logger.info(f"Parsed {len(stocks)} stocks from {market} master file")
    return stocks


def _fetch_sector_stock_codes_sync(naver_code: str) -> list[str]:
    """Synchronously fetch stock codes from a Naver sector detail page."""
    import httpx
    from bs4 import BeautifulSoup

    url = f"https://finance.naver.com/sise/sise_group_detail.naver?type=upjong&no={naver_code}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()

        content = resp.content.decode("euc-kr", errors="replace")

        # Detect error/redirect pages (Naver auth or CAPTCHA)
        if "로그인" in content and "비밀번호" in content:
            logger.warning(f"Naver sector {naver_code}: got login page, skipping")
            return []
        if "sise_group_detail" not in content:
            logger.warning(f"Naver sector {naver_code}: unexpected page content, skipping")
            return []

        soup = BeautifulSoup(content, "html.parser")

        stock_codes = []
        for link in soup.select("a[href*='code=']"):
            href = link.get("href", "")
            if "/item/" not in href:
                continue
            code = href.split("code=")[-1].split("&")[0].strip()
            if code and len(code) == 6 and code.isdigit():
                stock_codes.append(code)

        return list(set(stock_codes))
    except Exception as e:
        logger.error(f"Failed to fetch stocks for Naver sector {naver_code}: {e}")
        return []


def _build_naver_stock_mapping(db: Session) -> dict[str, int]:
    """Build stock_code → sector_id mapping from Naver sector detail pages.

    Uses synchronous HTTP to avoid event loop conflicts with uvloop.
    Takes ~24 seconds for ~80 sectors (0.3s delay between requests).
    """
    sectors = db.query(Sector).filter(Sector.naver_code.isnot(None)).all()
    if not sectors:
        logger.warning("No sectors with naver_code found")
        return {}

    mapping: dict[str, int] = {}
    failed_sectors = 0
    for sector in sectors:
        try:
            codes = _fetch_sector_stock_codes_sync(sector.naver_code)
            if not codes:
                failed_sectors += 1
                logger.warning(f"Sector '{sector.name}' ({sector.naver_code}): 0 stocks (may be blocked)")
            else:
                for code in codes:
                    mapping[code] = sector.id
                logger.debug(
                    f"Sector '{sector.name}' ({sector.naver_code}): {len(codes)} stocks"
                )
        except Exception as e:
            failed_sectors += 1
            logger.warning(f"Failed to fetch stocks for sector {sector.name}: {e}")
        time.sleep(0.3)

    # If too many sectors failed, fall back to static snapshot
    if failed_sectors > len(sectors) * 0.3:
        logger.warning(
            f"Naver mapping unreliable: {failed_sectors}/{len(sectors)} sectors failed. "
            f"Falling back to static snapshot."
        )
        return _load_snapshot_mapping(db)

    logger.info(f"Built Naver stock mapping: {len(mapping)} stocks across {len(sectors)} sectors ({failed_sectors} failed)")
    return mapping


def _load_snapshot_mapping(db: Session) -> dict[str, int]:
    """Load static stock_code → sector_id mapping from snapshot file.

    The snapshot maps stock_code → naver_sector_code. We convert to sector_id
    using the sectors table.
    """
    import json
    from pathlib import Path

    snapshot_path = Path(__file__).parent / "stock_sector_snapshot.json"
    if not snapshot_path.exists():
        logger.error("Stock sector snapshot file not found")
        return {}

    try:
        raw: dict[str, str] = json.loads(snapshot_path.read_text())
    except Exception as e:
        logger.error(f"Failed to load stock sector snapshot: {e}")
        return {}

    # Build naver_code → sector_id lookup
    code_to_id = {
        s.naver_code: s.id
        for s in db.query(Sector).filter(Sector.naver_code.isnot(None)).all()
    }

    mapping: dict[str, int] = {}
    for stock_code, naver_code in raw.items():
        sector_id = code_to_id.get(naver_code)
        if sector_id:
            mapping[stock_code] = sector_id

    logger.info(f"Loaded snapshot mapping: {len(mapping)} stocks from {len(raw)} entries")
    return mapping


def seed_all_stocks(db: Session, force: bool = False) -> int:
    """Fetch all KOSPI/KOSDAQ stocks from KIS master files and map to Naver sectors."""
    existing_count = db.query(Stock).count()
    if not force and existing_count > 100:
        logger.info(f"Already have {existing_count} stocks, skipping seed.")
        return 0

    # Primary: use static snapshot (reliable, pre-verified)
    # Live scraping is unreliable on cloud hosts (Render/Vercel) due to Naver blocking
    naver_mapping = _load_snapshot_mapping(db)
    if not naver_mapping:
        if existing_count > 0:
            logger.warning("All mapping sources failed but stocks exist. Keeping current data.")
            return 0
        logger.error("No stock mapping available. Ensure sectors are seeded first.")
        return 0

    # Fetch from KIS master files
    all_stocks: list[dict] = []
    for market, url in [("KOSPI", KOSPI_MST_URL), ("KOSDAQ", KOSDAQ_MST_URL)]:
        fetched = _download_and_parse_mst(url, market)
        all_stocks.extend(fetched)

    if not all_stocks:
        logger.warning("No stocks fetched from KIS master files.")
        return 0

    logger.info(f"Total stocks fetched: {len(all_stocks)}")

    # If force, update existing stocks' sector mappings + add new ones
    if force:
        existing_by_code = {s.stock_code: s for s in db.query(Stock).all()}
        updated = 0
        added = 0
        skipped = 0
        sector_names = {s.id: s.name for s in db.query(Sector).all()}

        kis_codes = {s["code"] for s in all_stocks}

        for stock_data in all_stocks:
            sector_id = naver_mapping.get(stock_data["code"])
            if not sector_id:
                skipped += 1
                continue

            if stock_data["code"] in existing_by_code:
                stock = existing_by_code[stock_data["code"]]
                if stock.sector_id != sector_id:
                    old_sector = sector_names.get(stock.sector_id, "?")
                    new_sector = sector_names.get(sector_id, "?")
                    logger.info(f"Remapping {stock.name}: {old_sector} → {new_sector}")
                    stock.sector_id = sector_id
                    updated += 1
            else:
                stock = Stock(
                    sector_id=sector_id,
                    name=stock_data["name"],
                    stock_code=stock_data["code"],
                    keywords=None,
                )
                db.add(stock)
                added += 1

        db.commit()
        logger.info(f"Force sync: {added} added, {updated} remapped, {skipped} unmapped")
        return added + updated

    # Normal seed: only add missing stocks
    existing_codes = {s.stock_code for s in db.query(Stock.stock_code).all()}
    added = 0
    skipped = 0
    sector_stats: dict[str, int] = {}
    sector_names = {s.id: s.name for s in db.query(Sector).all()}

    for stock_data in all_stocks:
        if stock_data["code"] in existing_codes:
            continue

        sector_id = naver_mapping.get(stock_data["code"])
        if not sector_id:
            skipped += 1
            continue

        sector_name = sector_names.get(sector_id, "unknown")
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
    logger.info(f"Seeded {added} stocks, skipped {skipped} unmapped. Distribution: {sector_stats}")
    return added
