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
        # Only use snapshot if DB is empty (first deploy with Naver blocked)
        existing_count = db.query(Sector).count()
        if existing_count > 0:
            logger.info("Live fetch failed but DB already has sectors, skipping.")
        else:
            logger.info("Using static sector snapshot as fallback for first seed")
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

        sectors = []
        for row in table.select("tr"):
            link = row.select_one("td a")
            if not link:
                continue
            name = link.get_text(strip=True)
            href = link.get("href", "")
            if "no=" in href:
                code = href.split("no=")[-1].split("&")[0].strip()
                if name and code:
                    sectors.append({"name": name, "code": code})

        logger.info(f"Live fetch: found {len(sectors)} sectors from Naver Finance")
        return sectors
    except Exception as e:
        logger.warning(f"Live sector fetch failed: {e}")
        return []


# Static fallback snapshot — only used when DB is empty AND live fetch fails
_SNAPSHOT = {
    "종이목재": "263", "음식료업": "264", "비금속광물": "265",
    "철강금속": "266", "기계": "267", "전기전자": "268",
    "의료정밀": "269", "운수장비": "270", "유통업": "271",
    "전기가스업": "272", "건설업": "273", "운수창고": "274",
    "통신업": "275", "금융업": "276", "은행": "277",
    "증권": "278", "보험": "279", "서비스업": "280",
    "제조업": "281",
}
