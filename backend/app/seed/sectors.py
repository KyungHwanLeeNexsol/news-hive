import logging

from sqlalchemy.orm import Session

from app.models.sector import Sector

logger = logging.getLogger(__name__)


def seed_sectors(db: Session) -> None:
    """Seed/update sectors from Naver Finance live data.

    Always tries live fetch to keep naver_code up to date.
    Falls back to static snapshot only on first run when live fails.
    """
    from app.models.stock import Stock
    from app.models.news_relation import NewsStockRelation

    # Always try live fetch to keep codes current
    sectors_data = _try_fetch_live()
    if not sectors_data:
        # Use snapshot: for first seed OR to fix corrupted data
        logger.info("Live fetch failed, using static snapshot for seed/correction")
        sectors_data = [
            {"name": name, "code": code}
            for name, code in _SNAPSHOT.items()
        ]

    if sectors_data:
        # Build lookup for existing sectors
        existing_by_code = {
            s.naver_code: s for s in db.query(Sector).all() if s.naver_code
        }
        existing_by_name = {s.name: s for s in db.query(Sector).all()}

        added = 0
        updated = 0
        live_codes = set()
        for item in sectors_data:
            name, code = item["name"], item["code"]
            live_codes.add(code)

            if code in existing_by_code:
                sector = existing_by_code[code]
                if sector.name != name:
                    # Name mismatch = wrong sector classification (e.g. old KRX code reused)
                    # Delete incorrectly mapped stocks so they get re-mapped on next stock sync
                    old_stock_ids = [
                        s.id for s in db.query(Stock.id).filter(Stock.sector_id == sector.id).all()
                    ]
                    if old_stock_ids:
                        db.query(NewsStockRelation).filter(
                            NewsStockRelation.stock_id.in_(old_stock_ids)
                        ).delete(synchronize_session=False)
                        db.query(Stock).filter(Stock.sector_id == sector.id).delete(
                            synchronize_session=False
                        )
                        logger.info(
                            f"Sector '{sector.name}' → '{name}': cleared {len(old_stock_ids)} "
                            f"incorrectly mapped stocks"
                        )
                    sector.name = name
                    updated += 1
                continue

            if name in existing_by_name:
                sector = existing_by_name[name]
                if sector.naver_code != code:
                    sector.naver_code = code
                    updated += 1
                continue

            db.add(Sector(name=name, naver_code=code, is_custom=False))
            added += 1

        # Remove sectors whose naver_code is stale (not in live data)
        if live_codes:
            stale = (
                db.query(Sector)
                .filter(
                    Sector.naver_code.isnot(None),
                    Sector.naver_code.notin_(live_codes),
                    Sector.is_custom == False,
                )
                .all()
            )
            for sector in stale:
                stock_ids = [s.id for s in db.query(Stock.id).filter(Stock.sector_id == sector.id).all()]
                db.query(NewsStockRelation).filter(NewsStockRelation.sector_id == sector.id).delete()
                if stock_ids:
                    db.query(NewsStockRelation).filter(NewsStockRelation.stock_id.in_(stock_ids)).delete()
                db.query(Stock).filter(Stock.sector_id == sector.id).delete()
                db.delete(sector)
                updated += 1
            if stale:
                logger.info(f"Removed {len(stale)} stale sectors with outdated naver_code")

        db.commit()
        logger.info(f"Sector seed: {added} added, {updated} updated")

    # Clean up: remove old sectors that have no naver_code (and their stocks)
    old_sectors = (
        db.query(Sector)
        .filter(Sector.naver_code.is_(None), Sector.is_custom == False)
        .all()
    )
    removed = 0
    for sector in old_sectors:
        stock_ids = [s.id for s in db.query(Stock.id).filter(Stock.sector_id == sector.id).all()]
        db.query(NewsStockRelation).filter(NewsStockRelation.sector_id == sector.id).delete()
        if stock_ids:
            db.query(NewsStockRelation).filter(NewsStockRelation.stock_id.in_(stock_ids)).delete()
        db.query(Stock).filter(Stock.sector_id == sector.id).delete()
        db.delete(sector)
        removed += 1
    if removed:
        db.commit()
        logger.info(f"Removed {removed} old sectors without naver_code (and their stocks)")


def _try_fetch_live() -> list[dict]:
    """Synchronously fetch Naver sector list (avoids event loop conflicts with uvloop)."""
    try:
        import httpx
        from bs4 import BeautifulSoup

        url = "https://finance.naver.com/sise/sise_group.naver?type=upjong"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()

        content = resp.content.decode("euc-kr", errors="replace")
        soup = BeautifulSoup(content, "html.parser")

        table = soup.select_one("table.type_1")
        if not table:
            return []

        # Naver codes to exclude (기타 = mostly ETF/ETN, not useful for sector tracking)
        _EXCLUDE_CODES = {"25"}

        sectors = []
        for row in table.select("tr"):
            link = row.select_one("td a")
            if not link:
                continue
            name = link.get_text(strip=True)
            href = link.get("href", "")
            if "no=" in href:
                code = href.split("no=")[-1].split("&")[0].strip()
                if name and code and code not in _EXCLUDE_CODES:
                    sectors.append({"name": name, "code": code})

        logger.info(f"Live fetch: found {len(sectors)} sectors from Naver Finance")
        return sectors
    except Exception as e:
        logger.warning(f"Live sector fetch failed: {e}")
        return []


# Static fallback snapshot — only used when DB is empty AND live fetch fails
# Source: https://finance.naver.com/sise/sise_group.naver?type=upjong (2026-02-24)
_SNAPSHOT = {
    "제약": "261",
    "생명과학도구및서비스": "262",
    "게임엔터테인먼트": "263",
    "백화점과일반상점": "264",
    "판매업체": "265",
    "화장품": "266",
    "IT서비스": "267",
    "식품": "268",
    "디스플레이장비및부품": "269",
    "자동차부품": "270",
    "레저용장비와제품": "271",
    "화학": "272",
    "자동차": "273",
    "섬유,의류,신발,호화품": "274",
    "담배": "275",
    "복합기업": "276",
    "창업투자": "277",
    "반도체와반도체장비": "278",
    "건설": "279",
    "부동산": "280",
    "건강관리장비와용품": "281",
    "전자장비와기기": "282",
    "전기제품": "283",
    "우주항공과국방": "284",
    "방송과엔터테인먼트": "285",
    "생물공학": "286",
    "소프트웨어": "287",
    "건강관리기술": "288",
    "건축자재": "289",
    "교육서비스": "290",
    "조선": "291",
    "핸드셋": "292",
    "컴퓨터와주변기기": "293",
    "통신장비": "294",
    "에너지장비및서비스": "295",
    "운송인프라": "296",
    "가정용품": "297",
    "가정용기기와용품": "298",
    "기계": "299",
    "양방향미디어와서비스": "300",
    "은행": "301",
    "식품과기본식료품소매": "302",
    "가구": "303",
    "철강": "304",
    "항공사": "305",
    "전기장비": "306",
    "전자제품": "307",
    "인터넷과카탈로그소매": "308",
    "음료": "309",
    "광고": "310",
    "포장재": "311",
    "가스유틸리티": "312",
    "석유와가스": "313",
    "출판": "314",
    "손해보험": "315",
    "건강관리업체및서비스": "316",
    "호텔,레스토랑,레저": "317",
    "종이와목재": "318",
    "기타금융": "319",
    "건축제품": "320",
    "증권": "321",
    "비철금속": "322",
    "해운사": "323",
    "상업서비스와공급품": "324",
    "전기유틸리티": "325",
    "항공화물운송과물류": "326",
    "디스플레이패널": "327",
    "전문소매": "328",
    "도로와철도운송": "329",
    "생명보험": "330",
    "복합유틸리티": "331",
    "문구류": "332",
    "무선통신서비스": "333",
    "무역회사와판매업체": "334",
    "다각화된통신서비스": "336",
    "카드": "337",
    "사무용전자제품": "338",
    "다각화된소비자서비스": "339",
}
