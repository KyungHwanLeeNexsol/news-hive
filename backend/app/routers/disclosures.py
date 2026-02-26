from fastapi import APIRouter, BackgroundTasks, Depends, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.models.disclosure import Disclosure
from app.models.stock import Stock

router = APIRouter(prefix="/api", tags=["disclosures"])


@router.get("/disclosures")
async def list_disclosures(
    stock_id: int = Query(default=0, description="Filter by stock ID"),
    report_type: str = Query(default="", description="Filter by report type"),
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


@router.post("/disclosures/refresh")
async def refresh_disclosures():
    """Manually trigger DART disclosure crawl with debug info."""
    import traceback
    from app.services.dart_crawler import fetch_dart_disclosures
    from app.config import settings

    if not settings.DART_API_KEY:
        return {"message": "DART_API_KEY not set", "saved": 0}

    db = SessionLocal()
    try:
        count = await fetch_dart_disclosures(db, days=7)
        # Count total disclosures in DB
        total = db.query(Disclosure).count()
        with_stock = db.query(Disclosure).filter(Disclosure.stock_id.isnot(None)).count()
        return {
            "message": "DART crawl completed",
            "saved": count,
            "total_in_db": total,
            "matched_to_stock": with_stock,
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
