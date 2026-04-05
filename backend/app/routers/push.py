"""Web Push 구독 관련 API 라우터.

푸시 알림 구독/해제 및 VAPID 공개키 조회 엔드포인트를 제공한다.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.user import PushSubscription, User, UserPreferences
from app.routers.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/push", tags=["push"])


# ═══════════════════════════════════════════════════════
# Pydantic 요청 스키마
# ═══════════════════════════════════════════════════════


class PushSubscribeKeys(BaseModel):
    """Web Push 구독 키 정보."""

    p256dh: str
    auth: str


class PushSubscribeRequest(BaseModel):
    """푸시 알림 구독 요청."""

    endpoint: str
    keys: PushSubscribeKeys


class PushUnsubscribeRequest(BaseModel):
    """푸시 알림 구독 해제 요청."""

    endpoint: str


# ═══════════════════════════════════════════════════════
# 엔드포인트
# ═══════════════════════════════════════════════════════


# @MX:ANCHOR: VAPID 공개키 조회 — 클라이언트 Web Push 구독 초기화의 진입점
# @MX:REASON: 프런트엔드에서 ServiceWorker.pushManager.subscribe() 전 반드시 호출됨
@router.get("/vapid-public-key")
async def get_vapid_public_key() -> dict:
    """VAPID 공개키를 반환한다. 인증 불필요."""
    if not settings.VAPID_PUBLIC_KEY:
        raise HTTPException(status_code=503, detail="VAPID 공개키가 설정되지 않았습니다.")
    return {"public_key": settings.VAPID_PUBLIC_KEY}


@router.post("/subscribe")
async def subscribe_push(
    body: PushSubscribeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Web Push 구독을 등록한다.

    동일 endpoint가 이미 존재하면 키 정보를 업데이트(upsert)한다.
    구독 성공 시 user_preferences.push_enabled를 True로 설정한다.
    """
    # endpoint 기준 upsert
    existing = (
        db.query(PushSubscription)
        .filter(PushSubscription.endpoint == body.endpoint)
        .first()
    )

    if existing:
        # 키 정보 업데이트 (디바이스 재등록 등 대응)
        existing.p256dh_key = body.keys.p256dh
        existing.auth_key = body.keys.auth
        existing.user_id = current_user.id
    else:
        subscription = PushSubscription(
            user_id=current_user.id,
            endpoint=body.endpoint,
            p256dh_key=body.keys.p256dh,
            auth_key=body.keys.auth,
        )
        db.add(subscription)

    # push_enabled 활성화
    prefs = (
        db.query(UserPreferences)
        .filter(UserPreferences.user_id == current_user.id)
        .first()
    )
    if prefs is None:
        prefs = UserPreferences(user_id=current_user.id, push_enabled=True)
        db.add(prefs)
    else:
        prefs.push_enabled = True

    db.commit()
    return {"message": "푸시 알림 구독 완료"}


@router.delete("/subscribe")
async def unsubscribe_push(
    body: PushUnsubscribeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Web Push 구독을 해제한다.

    해당 사용자의 구독이 모두 제거되면 push_enabled를 False로 설정한다.
    """
    subscription = (
        db.query(PushSubscription)
        .filter(
            PushSubscription.endpoint == body.endpoint,
            PushSubscription.user_id == current_user.id,
        )
        .first()
    )

    if subscription is None:
        raise HTTPException(status_code=404, detail="해당 구독 정보를 찾을 수 없습니다.")

    db.delete(subscription)
    db.flush()

    # 잔여 구독이 없으면 push_enabled 비활성화
    remaining = (
        db.query(PushSubscription)
        .filter(PushSubscription.user_id == current_user.id)
        .count()
    )
    if remaining == 0:
        prefs = (
            db.query(UserPreferences)
            .filter(UserPreferences.user_id == current_user.id)
            .first()
        )
        if prefs:
            prefs.push_enabled = False

    db.commit()
    return {"message": "푸시 알림 구독 해제"}
