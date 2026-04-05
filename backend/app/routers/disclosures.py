from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db, SessionLocal
from app.models.disclosure import Disclosure
from app.models.stock import Stock

router = APIRouter(prefix="/api", tags=["disclosures"])


@router.get("/disclosures")
async def list_disclosures(
    stock_id: int = Query(default=0, description="Filter by stock ID"),
    report_type: str = Query(default="", description="Filter by report type"),
    q: str = Query(default="", description="Search by report name or stock/corp name"),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """List recent disclosures with optional filters."""
    query = db.query(Disclosure).outerjoin(Stock, Disclosure.stock_id == Stock.id)

    if stock_id:
        query = query.filter(Disclosure.stock_id == stock_id)

    if report_type:
        query = query.filter(Disclosure.report_type == report_type)

    if q:
        keyword = f"%{q}%"
        query = query.filter(
            or_(
                Disclosure.report_name.ilike(keyword),
                Disclosure.corp_name.ilike(keyword),
                Stock.name.ilike(keyword),
            )
        )

    total = query.count()

    disclosures = (
        query.order_by(Disclosure.rcept_dt.desc(), Disclosure.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    items = []
    for d in disclosures:
        items.append({
            "id": d.id,
            "corp_code": d.corp_code,
            "corp_name": d.corp_name,
            "stock_code": d.stock_code,
            "stock_id": d.stock_id,
            "stock_name": d.stock.name if d.stock else None,
            "report_name": d.report_name,
            "report_type": d.report_type,
            "rcept_no": d.rcept_no,
            "rcept_dt": d.rcept_dt,
            "url": d.url,
            "created_at": str(d.created_at),
        })

    return JSONResponse(
        content=jsonable_encoder(items),
        headers={
            "X-Total-Count": str(total),
            "Access-Control-Expose-Headers": "X-Total-Count",
        },
    )


@router.post("/disclosures/{disclosure_id}/summary")
async def generate_disclosure_summary_endpoint(
    disclosure_id: int,
    db: Session = Depends(get_db),
):
    """Generate AI summary for a disclosure (lazy, cached in DB)."""
    disc = db.query(Disclosure).filter(Disclosure.id == disclosure_id).first()
    if not disc:
        raise HTTPException(status_code=404, detail="Disclosure not found")

    if not disc.ai_summary:
        from app.services.ai_classifier import generate_disclosure_summary

        ai_summary = await generate_disclosure_summary(
            report_name=disc.report_name,
            report_type=disc.report_type,
            corp_name=disc.corp_name,
        )
        if ai_summary:
            disc.ai_summary = ai_summary
            db.commit()
            db.refresh(disc)

    return {
        "id": disc.id,
        "corp_name": disc.corp_name,
        "report_name": disc.report_name,
        "report_type": disc.report_type,
        "rcept_no": disc.rcept_no,
        "rcept_dt": disc.rcept_dt,
        "url": disc.url,
        "ai_summary": disc.ai_summary,
    }


@router.post("/disclosures/push")
async def push_disclosures(
    body: dict,
    x_push_secret: str = Header(default=""),
):
    """Receive disclosure data pushed from GitHub Actions (DART is blocked on this server).

    Expects: {"items": [{"corp_code", "corp_name", "report_name", "rcept_no", "rcept_dt", "market"}, ...]}
    """
    if not settings.DART_PUSH_SECRET or x_push_secret != settings.DART_PUSH_SECRET:
        raise HTTPException(status_code=403, detail="Invalid push secret")

    from app.services.dart_crawler import _classify_report_type, backfill_disclosure_stock_ids

    items = body.get("items", [])
    if not items:
        return {"saved": 0, "total": 0}

    db = SessionLocal()
    try:
        # Pre-load existing rcept_no set
        existing = {r[0] for r in db.query(Disclosure.rcept_no).all()}

        # Build name -> stock_id mapping
        stocks = db.query(Stock).filter(Stock.stock_code.isnot(None)).all()
        name_to_id = {s.name: s.id for s in stocks}

        saved = 0
        for item in items:
            rcept_no = item.get("rcept_no", "")
            if not rcept_no or rcept_no in existing:
                continue

            corp_name = item.get("corp_name", "")
            report_name = item.get("report_name", "")

            disclosure = Disclosure(
                corp_code=item.get("corp_code", ""),
                corp_name=corp_name,
                stock_code=None,
                stock_id=name_to_id.get(corp_name),
                report_name=report_name,
                report_type=_classify_report_type(report_name),
                rcept_no=rcept_no,
                rcept_dt=item.get("rcept_dt", ""),
                url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
            )
            db.add(disclosure)
            existing.add(rcept_no)
            saved += 1

        if saved:
            db.commit()

        # Backfill any unlinked disclosures
        backfill_disclosure_stock_ids(db)

        total = db.query(Disclosure).count()
        return {"saved": saved, "total": total}
    finally:
        db.close()


@router.post("/disclosures/refresh")
async def refresh_disclosures():
    """Manually trigger DART disclosure crawl (web scraping) + backfill."""
    import traceback
    from app.services.dart_crawler import fetch_dart_disclosures, backfill_disclosure_stock_ids, backfill_disclosure_report_types

    db = SessionLocal()
    try:
        count = await fetch_dart_disclosures(db, days=7)
        backfilled = backfill_disclosure_stock_ids(db)
        types_backfilled = backfill_disclosure_report_types(db)
        total = db.query(Disclosure).count()
        with_stock = db.query(Disclosure).filter(Disclosure.stock_id.isnot(None)).count()
        return {
            "message": "DART crawl completed",
            "saved": count,
            "backfilled": backfilled,
            "types_backfilled": types_backfilled,
            "total_in_db": total,
            "matched_to_stock": with_stock,
            "unmatched": total - with_stock,
        }
    except Exception as e:
        return {"message": f"DART crawl failed: {e}", "traceback": traceback.format_exc(), "saved": 0}
    finally:
        db.close()


@router.get("/stocks/{stock_id}/disclosures")
async def get_stock_disclosures(
    stock_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Get disclosures for a specific stock."""
    query = db.query(Disclosure).filter(Disclosure.stock_id == stock_id)
    total = query.count()

    disclosures = (
        query.order_by(Disclosure.rcept_dt.desc(), Disclosure.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    items = []
    for d in disclosures:
        items.append({
            "id": d.id,
            "corp_name": d.corp_name,
            "report_name": d.report_name,
            "report_type": d.report_type,
            "rcept_no": d.rcept_no,
            "rcept_dt": d.rcept_dt,
            "url": d.url,
        })

    return JSONResponse(
        content=jsonable_encoder(items),
        headers={
            "X-Total-Count": str(total),
            "Access-Control-Expose-Headers": "X-Total-Count",
        },
    )
