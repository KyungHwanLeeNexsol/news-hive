from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.macro_alert import MacroAlert

router = APIRouter(prefix="/api", tags=["alerts"])


@router.get("/alerts")
async def list_alerts(
    active_only: bool = Query(default=True),
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """활성 매크로 리스크 알림 목록 (키워드별 최신 1개만)."""
    from sqlalchemy import func

    query = db.query(MacroAlert)
    if active_only:
        query = query.filter(MacroAlert.is_active == True)  # noqa: E712

    # Deduplicate: only show the latest alert per keyword
    latest_ids = (
        db.query(func.max(MacroAlert.id))
        .filter(MacroAlert.is_active == True)  # noqa: E712
        .group_by(MacroAlert.keyword)
        .subquery()
    )
    alerts = (
        db.query(MacroAlert)
        .filter(MacroAlert.id.in_(latest_ids))
        .order_by(desc(MacroAlert.created_at))
        .limit(limit)
        .all()
    )

    items = []
    for a in alerts:
        items.append({
            "id": a.id,
            "level": a.level,
            "keyword": a.keyword,
            "title": a.title,
            "description": a.description,
            "article_count": a.article_count,
            "is_active": a.is_active,
            "created_at": str(a.created_at),
        })
    return items


@router.post("/alerts/{alert_id}/dismiss")
async def dismiss_alert(
    alert_id: int,
    db: Session = Depends(get_db),
):
    """알림 비활성화 (사용자가 닫기)."""
    alert = db.query(MacroAlert).filter(MacroAlert.id == alert_id).first()
    if alert:
        alert.is_active = False
        db.commit()
    return {"ok": True}
