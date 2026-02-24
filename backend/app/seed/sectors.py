import asyncio
import logging

from sqlalchemy.orm import Session

from app.models.sector import Sector

logger = logging.getLogger(__name__)

# Static fallback: Naver Finance sector snapshot (name → naver_code)
# Used when live scraping fails (e.g., during CI, first deploy, Naver down)
NAVER_SECTORS_SNAPSHOT = {
    "종이목재": "263", "음식료업": "264", "비금속광물": "265",
    "철강금속": "266", "기계": "267", "전기전자": "268",
    "의료정밀": "269", "운수장비": "270", "유통업": "271",
    "전기가스업": "272", "건설업": "273", "운수창고": "274",
    "통신업": "275", "금융업": "276", "은행": "277",
    "증권": "278", "보험": "279", "서비스업": "280",
    "제조업": "281", "섬유의복": "300", "의약품": "301",
    "화학": "302", "비철금속": "306",
    "소프트웨어": "326", "전자제품": "327",
    "전자장비와기기": "328", "생명보험": "329", "전기장비": "330",
    "디스플레이패널": "331", "창업투자": "332",
    "인터넷과카탈로그소매": "333", "섬유,의류,신발,호화품": "334",
    "항공사": "336", "생명과학도구및서비스": "337",
    "음료": "338", "식품": "339", "건축자재": "340",
    "출판": "341", "가구": "342", "식품과기본식료품소매": "343",
    "자동차": "344", "생물공학": "345", "건설": "346",
    "사무용전자제품": "347", "문구류": "348",
    "백화점과일반상점": "349", "핸드셋": "350",
    "상업서비스와공급품": "351", "화장품": "352", "제약": "353",
    "다각화된금융": "354", "석유와가스": "355",
    "전자장비와부품": "356", "호텔,레스토랑,레저": "357",
    "카드": "358", "포장재": "359", "복합유틸리티": "360",
    "해운사": "361", "광고": "362", "항공화물운송과물류": "363",
    "반도체와반도체장비": "364", "무역회사와판매업체": "365",
    "IT서비스": "366", "조선": "367",
    "운송인프라": "368", "철강": "369", "양방향미디어와서비스": "370",
    "무선통신서비스": "371", "에너지장비및서비스": "372",
    "종합부동산": "373", "교육서비스": "374",
    "미디어": "375", "가정용기기와용품": "376",
    "자동차부품": "377", "복합기업": "378",
    "기계장비": "379", "건강관리기술": "380",
    "건강관리장비와용품": "381", "손해보험": "382",
}


def seed_sectors(db: Session) -> None:
    """Seed sectors from Naver Finance or static fallback."""
    from app.models.stock import Stock

    # If we already have Naver sectors, skip seeding but still clean up
    existing_naver = db.query(Sector).filter(Sector.naver_code.isnot(None)).count()
    if existing_naver <= 30:
        # Try live fetch first
        sectors_data = _try_fetch_live()
        if not sectors_data:
            logger.info("Using static sector snapshot as fallback")
            sectors_data = [
                {"name": name, "code": code}
                for name, code in NAVER_SECTORS_SNAPSHOT.items()
            ]

        # Build lookup for existing sectors
        existing_by_code = {
            s.naver_code: s for s in db.query(Sector).all() if s.naver_code
        }
        existing_by_name = {s.name: s for s in db.query(Sector).all()}

        added = 0
        updated = 0
        for item in sectors_data:
            name, code = item["name"], item["code"]

            if code in existing_by_code:
                sector = existing_by_code[code]
                if sector.name != name:
                    sector.name = name
                    updated += 1
                continue

            if name in existing_by_name:
                sector = existing_by_name[name]
                sector.naver_code = code
                updated += 1
                continue

            db.add(Sector(name=name, naver_code=code, is_custom=False))
            added += 1

        db.commit()
        logger.info(f"Sector seed: {added} added, {updated} updated")
    else:
        logger.info(f"Already have {existing_naver} Naver sectors, skipping seed.")

    # Clean up: remove old sectors that have no naver_code and no stocks
    old_sectors = (
        db.query(Sector)
        .filter(Sector.naver_code.is_(None), Sector.is_custom == False)
        .all()
    )
    removed = 0
    for sector in old_sectors:
        stock_count = db.query(Stock).filter(Stock.sector_id == sector.id).count()
        if stock_count == 0:
            db.delete(sector)
            removed += 1
    if removed:
        db.commit()
        logger.info(f"Removed {removed} old sectors without naver_code and no stocks")


def _try_fetch_live() -> list[dict]:
    """Attempt synchronous fetch of Naver sector list."""
    try:
        from app.services.naver_finance import fetch_all_naver_sectors

        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(fetch_all_naver_sectors())
        loop.close()
        return result
    except Exception as e:
        logger.warning(f"Live sector fetch failed: {e}")
        return []
