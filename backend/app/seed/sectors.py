import logging

from sqlalchemy.orm import Session

from app.models.sector import Sector

logger = logging.getLogger(__name__)


def seed_sectors(db: Session) -> None:
    """Seed sectors from static snapshot (fast, no network required).

    Uses a clean rebuild approach: deletes all non-custom sectors and recreates
    them from authoritative data to avoid stale cache / ID mismatch bugs.
    Live Naver fetch is skipped on startup to avoid cold start delays.
    """
    from app.models.stock import Stock
    from app.models.news_relation import NewsStockRelation

    # Use static snapshot directly (fast, no network latency)
    sectors_data = [
        {"name": name, "code": code}
        for name, code in _SNAPSHOT.items()
    ]

    if not sectors_data:
        logger.error("No sector data available")
        return

    # Build target: naver_code → name
    target = {item["code"]: item["name"] for item in sectors_data}

    # Check if existing data already matches (skip rebuild if so)
    existing = {
        s.naver_code: s.name
        for s in db.query(Sector).filter(
            Sector.naver_code.isnot(None), Sector.is_custom == False
        ).all()
    }
    if existing == target:
        logger.info(f"Sectors already up to date ({len(existing)} sectors)")
        return

    # --- Clean rebuild of non-custom sectors ---
    logger.info(
        f"Rebuilding sectors: {len(existing)} existing → {len(target)} target"
    )

    # 1. Delete all stocks + relations for non-custom sectors
    non_custom_ids = [
        s.id for s in db.query(Sector.id).filter(Sector.is_custom == False).all()
    ]
    if non_custom_ids:
        stock_ids = [
            s.id for s in db.query(Stock.id).filter(
                Stock.sector_id.in_(non_custom_ids)
            ).all()
        ]
        if stock_ids:
            db.query(NewsStockRelation).filter(
                NewsStockRelation.stock_id.in_(stock_ids)
            ).delete(synchronize_session=False)
        db.query(NewsStockRelation).filter(
            NewsStockRelation.sector_id.in_(non_custom_ids)
        ).delete(synchronize_session=False)
        db.query(Stock).filter(
            Stock.sector_id.in_(non_custom_ids)
        ).delete(synchronize_session=False)
        db.query(Sector).filter(
            Sector.id.in_(non_custom_ids)
        ).delete(synchronize_session=False)

    # 2. Create fresh sectors
    for code, name in target.items():
        db.add(Sector(name=name, naver_code=code, is_custom=False))

    db.commit()
    logger.info(f"Sector rebuild complete: {len(target)} sectors created")


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


# Static fallback snapshot — authoritative Naver GICS sector codes
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
