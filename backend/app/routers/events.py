from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.economic_event import EconomicEvent

router = APIRouter(prefix="/api", tags=["events"])


@router.get("/events")
async def list_events(
    days: int = Query(default=30, ge=1, le=365, description="앞으로 N일 이벤트"),
    past_days: int = Query(default=7, ge=0, le=30, description="지난 N일 이벤트"),
    category: str = Query(default=""),
    db: Session = Depends(get_db),
):
    """경제 이벤트 캘린더 조회."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=past_days)
    end = now + timedelta(days=days)

    query = db.query(EconomicEvent).filter(
        and_(EconomicEvent.event_date >= start, EconomicEvent.event_date <= end)
    )
    if category:
        query = query.filter(EconomicEvent.category == category)

    events = query.order_by(EconomicEvent.event_date.asc()).all()

    items = []
    for e in events:
        items.append({
            "id": e.id,
            "title": e.title,
            "description": e.description,
            "event_date": str(e.event_date),
            "category": e.category,
            "importance": e.importance,
            "country": e.country,
        })
    return items


@router.post("/events")
async def create_event(
    body: dict = Body(...),
    db: Session = Depends(get_db),
):
    """이벤트 수동 추가."""
    title = body.get("title", "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")

    event_date_str = body.get("event_date", "")
    try:
        event_date = datetime.fromisoformat(event_date_str)
        if event_date.tzinfo is None:
            event_date = event_date.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid event_date (ISO format required)")

    event = EconomicEvent(
        title=title,
        description=body.get("description", ""),
        event_date=event_date,
        category=body.get("category", "custom"),
        importance=body.get("importance", "medium"),
        country=body.get("country", "KR"),
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    return {
        "id": event.id,
        "title": event.title,
        "event_date": str(event.event_date),
        "category": event.category,
        "importance": event.importance,
        "country": event.country,
    }


@router.delete("/events/{event_id}")
async def delete_event(
    event_id: int,
    db: Session = Depends(get_db),
):
    """이벤트 삭제."""
    event = db.query(EconomicEvent).filter(EconomicEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    db.delete(event)
    db.commit()
    return {"ok": True}


@router.post("/events/seed")
async def seed_default_events(
    db: Session = Depends(get_db),
):
    """2026년 주요 경제 이벤트 시드 데이터 추가."""
    from app.seed.economic_events import seed_economic_events
    count = seed_economic_events(db)
    return {"seeded": count}
