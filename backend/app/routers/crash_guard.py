"""코스피 폭락 경보 이력 조회 API (SPEC-AI-064 REQ-AI-064-013)."""

import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.crash_risk_alert import CrashRiskAlert

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/crash-guard", tags=["crash-guard"])


@router.get("/alerts")
def get_crash_alerts(
    limit: int = Query(50, ge=1, le=200),
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
) -> list[dict]:
    """최근 N일 폭락 경보 이력을 최신순으로 반환한다.

    Args:
        limit: 반환 최대 건수 (기본 50)
        days: 최근 N일 필터 (기본 7)

    Returns:
        경보 이력 목록 (triggered_signals는 파싱된 JSON 배열)
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        db.query(CrashRiskAlert)
        .filter(CrashRiskAlert.created_at >= cutoff)
        .order_by(CrashRiskAlert.created_at.desc())
        .limit(limit)
        .all()
    )

    result = []
    for row in rows:
        # triggered_signals JSON 문자열을 파싱하여 배열로 반환
        try:
            signals_parsed = json.loads(row.triggered_signals) if row.triggered_signals else []
        except (json.JSONDecodeError, TypeError):
            signals_parsed = []

        result.append({
            "id": row.id,
            "scan_type": row.scan_type,
            "risk_level": row.risk_level,
            "triggered_signals": signals_parsed,
            "kospi_change_pct": row.kospi_change_pct,
            "telegram_sent": row.telegram_sent,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        })

    return result
