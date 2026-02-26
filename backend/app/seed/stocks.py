"""Stock seeding from static snapshot.

Primary source: stock_snapshot.json — a pre-built file containing all
KOSPI/KOSDAQ common stocks with name, market, and sector mapping.
Generated locally from KIS master files + Naver sector data.

No network requests needed at runtime.
"""

import json
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.sector import Sector
from app.models.stock import Stock

logger = logging.getLogger(__name__)

_SNAPSHOT_PATH = Path(__file__).parent / "stock_snapshot.json"


def _load_stock_snapshot(db: Session) -> list[dict]:
    """Load stock data from snapshot, resolving naver_code → sector_id.

    Returns list of {code, name, market, sector_id}.
    """
    if not _SNAPSHOT_PATH.exists():
        logger.error("stock_snapshot.json not found")
        return []

    try:
        raw: dict[str, dict] = json.loads(_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"Failed to load stock snapshot: {e}")
        return []

    # Build naver_code → sector_id lookup
    naver_to_sector = {
        s.naver_code: s.id
        for s in db.query(Sector).filter(Sector.naver_code.isnot(None)).all()
    }

    stocks = []
    for code, info in raw.items():
        sector_id = naver_to_sector.get(info["sector"])
        if not sector_id:
            continue
        stocks.append({
            "code": code,
            "name": info["name"],
            "market": info["market"],
            "sector_id": sector_id,
        })

    logger.info(f"Loaded {len(stocks)} stocks from snapshot ({len(raw)} total entries)")
    return stocks


def seed_all_stocks(db: Session, force: bool = False) -> int:
    """Seed stocks from static snapshot (no network required).

    Args:
        force: If True, update existing stocks' sector/market mappings
               and add any missing stocks. If False, skip when >100 exist.
    """
    existing_count = db.query(Stock).count()
    if not force and existing_count > 100:
        logger.info(f"Already have {existing_count} stocks, skipping seed.")
        return 0

    snapshot = _load_stock_snapshot(db)
    if not snapshot:
        logger.error("No stocks in snapshot. Ensure sectors are seeded first.")
        return 0

    if force:
        existing_by_code = {s.stock_code: s for s in db.query(Stock).all()}
        added = 0
        updated = 0

        for s in snapshot:
            if s["code"] in existing_by_code:
                stock = existing_by_code[s["code"]]
                changed = False
                if stock.sector_id != s["sector_id"]:
                    stock.sector_id = s["sector_id"]
                    changed = True
                if stock.market != s["market"]:
                    stock.market = s["market"]
                    changed = True
                if stock.name != s["name"]:
                    stock.name = s["name"]
                    changed = True
                if changed:
                    updated += 1
            else:
                db.add(Stock(
                    sector_id=s["sector_id"],
                    name=s["name"],
                    stock_code=s["code"],
                    market=s["market"],
                    keywords=None,
                ))
                added += 1

        db.commit()
        logger.info(f"Force sync: {added} added, {updated} updated (from {len(snapshot)} snapshot)")
        return added + updated

    # Normal seed: only add missing
    existing_codes = {row[0] for row in db.query(Stock.stock_code).all()}
    added = 0

    for s in snapshot:
        if s["code"] in existing_codes:
            continue
        db.add(Stock(
            sector_id=s["sector_id"],
            name=s["name"],
            stock_code=s["code"],
            market=s["market"],
            keywords=None,
        ))
        existing_codes.add(s["code"])
        added += 1

    db.commit()
    logger.info(f"Seeded {added} stocks from snapshot")
    return added
