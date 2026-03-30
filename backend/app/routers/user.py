"""사용자 관련 API 라우터.

관심 종목(watchlist), 사용자 설정(preferences), 개인화 피드(feed) 엔드포인트를 제공한다.
모든 엔드포인트는 JWT 인증이 필요하다.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.news import NewsArticle
from app.models.news_relation import NewsStockRelation
from app.models.stock import Stock
from app.models.user import User, UserPreferences, UserWatchlist
from app.routers.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/user", tags=["user"])


# ═══════════════════════════════════════════════════════
# Pydantic 요청/응답 스키마
# ═══════════════════════════════════════════════════════


class WatchlistAddRequest(BaseModel):
    """관심 종목 추가 요청."""

    stock_id: int


class WatchlistSyncRequest(BaseModel):
    """관심 종목 동기화 요청 (localStorage 병합용)."""

    stock_ids: list[int]


class PreferencesUpdateRequest(BaseModel):
    """사용자 설정 부분 업데이트 요청."""

    notification_enabled: Optional[bool] = None
    followed_sector_ids: Optional[list[int]] = None
    followed_stock_ids: Optional[list[int]] = None
    alert_level_threshold: Optional[str] = None
    push_enabled: Optional[bool] = None


# ═══════════════════════════════════════════════════════
# 헬퍼 함수
# ═══════════════════════════════════════════════════════


def _get_or_create_preferences(user: User, db: Session) -> UserPreferences:
    """사용자 설정을 조회하거나 기본값으로 생성해 반환한다."""
    prefs = db.query(UserPreferences).filter(UserPreferences.user_id == user.id).first()
    if prefs is None:
        prefs = UserPreferences(user_id=user.id)
        db.add(prefs)
        db.commit()
        db.refresh(prefs)
    return prefs


# ═══════════════════════════════════════════════════════
# 관심 종목 엔드포인트
# ═══════════════════════════════════════════════════════


# @MX:ANCHOR: 관심 종목 목록 조회 — 인증된 사용자의 watchlist 피드 기준 데이터
# @MX:REASON: 프런트엔드 watchlist 화면·개인화 피드 모두 이 API를 사용함
@router.get("/watchlist")
async def get_watchlist(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    """사용자의 관심 종목 목록을 종목 상세 정보와 함께 반환한다."""
    items = (
        db.query(UserWatchlist)
        .options(joinedload(UserWatchlist.stock).joinedload(Stock.sector))
        .filter(UserWatchlist.user_id == current_user.id)
        .all()
    )
    return [
        {
            "stock_id": item.stock_id,
            "stock_code": item.stock.stock_code if item.stock else None,
            "stock_name": item.stock.name if item.stock else None,
            "sector_name": item.stock.sector.name if item.stock and item.stock.sector else None,
        }
        for item in items
    ]


@router.post("/watchlist")
async def add_watchlist(
    body: WatchlistAddRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """관심 종목을 추가한다. 이미 추가된 종목이면 409를 반환한다."""
    # 종목 존재 확인
    stock = db.query(Stock).filter(Stock.id == body.stock_id).first()
    if stock is None:
        raise HTTPException(status_code=404, detail="종목을 찾을 수 없습니다.")

    # 중복 추가 방지
    existing = (
        db.query(UserWatchlist)
        .filter(
            UserWatchlist.user_id == current_user.id,
            UserWatchlist.stock_id == body.stock_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="이미 관심 종목에 추가된 종목입니다.")

    item = UserWatchlist(user_id=current_user.id, stock_id=body.stock_id)
    db.add(item)
    db.commit()
    return {"message": "관심종목 추가됨", "stock_id": body.stock_id}


@router.delete("/watchlist/{stock_id}")
async def remove_watchlist(
    stock_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """관심 종목을 삭제한다. 목록에 없는 종목이면 404를 반환한다."""
    item = (
        db.query(UserWatchlist)
        .filter(
            UserWatchlist.user_id == current_user.id,
            UserWatchlist.stock_id == stock_id,
        )
        .first()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="관심 종목 목록에 해당 종목이 없습니다.")

    db.delete(item)
    db.commit()
    return {"message": "관심종목 삭제됨"}


@router.post("/watchlist/sync")
async def sync_watchlist(
    body: WatchlistSyncRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """localStorage 관심 종목 목록을 서버와 병합한다 (합집합, 중복 제거).

    이미 서버에 있는 종목은 건너뛰고, 없는 종목만 추가한다.
    """
    if not body.stock_ids:
        # 추가할 항목이 없으면 현재 총 개수만 반환
        total = (
            db.query(UserWatchlist)
            .filter(UserWatchlist.user_id == current_user.id)
            .count()
        )
        return {"added": 0, "total": total}

    # 서버에 이미 존재하는 stock_id 집합
    existing_ids = {
        row.stock_id
        for row in db.query(UserWatchlist.stock_id)
        .filter(UserWatchlist.user_id == current_user.id)
        .all()
    }

    # DB에 실재하는 종목만 필터링
    valid_stocks = (
        db.query(Stock.id)
        .filter(Stock.id.in_(body.stock_ids))
        .all()
    )
    valid_ids = {row.id for row in valid_stocks}

    to_add = [sid for sid in body.stock_ids if sid in valid_ids and sid not in existing_ids]

    added = 0
    for stock_id in to_add:
        db.add(UserWatchlist(user_id=current_user.id, stock_id=stock_id))
        added += 1

    if added:
        db.commit()

    total = (
        db.query(UserWatchlist)
        .filter(UserWatchlist.user_id == current_user.id)
        .count()
    )
    return {"added": added, "total": total}


# ═══════════════════════════════════════════════════════
# 사용자 설정 엔드포인트
# ═══════════════════════════════════════════════════════


@router.get("/preferences")
async def get_preferences(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """사용자 설정을 반환한다. 설정이 없으면 기본값으로 생성 후 반환한다."""
    prefs = _get_or_create_preferences(current_user, db)
    return {
        "notification_enabled": prefs.notification_enabled,
        "followed_sector_ids": prefs.followed_sector_ids or [],
        "followed_stock_ids": prefs.followed_stock_ids or [],
        "alert_level_threshold": prefs.alert_level_threshold,
        "push_enabled": prefs.push_enabled,
    }


@router.put("/preferences")
async def update_preferences(
    body: PreferencesUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """사용자 설정을 부분 업데이트한다. 전달된 필드만 변경한다."""
    prefs = _get_or_create_preferences(current_user, db)

    if body.notification_enabled is not None:
        prefs.notification_enabled = body.notification_enabled
    if body.followed_sector_ids is not None:
        prefs.followed_sector_ids = body.followed_sector_ids
    if body.followed_stock_ids is not None:
        prefs.followed_stock_ids = body.followed_stock_ids
    if body.alert_level_threshold is not None:
        # 허용 값 검증
        allowed = {"info", "warning", "danger"}
        if body.alert_level_threshold not in allowed:
            raise HTTPException(
                status_code=422,
                detail=f"alert_level_threshold는 {allowed} 중 하나여야 합니다.",
            )
        prefs.alert_level_threshold = body.alert_level_threshold
    if body.push_enabled is not None:
        prefs.push_enabled = body.push_enabled

    db.commit()
    db.refresh(prefs)

    return {
        "notification_enabled": prefs.notification_enabled,
        "followed_sector_ids": prefs.followed_sector_ids or [],
        "followed_stock_ids": prefs.followed_stock_ids or [],
        "alert_level_threshold": prefs.alert_level_threshold,
        "push_enabled": prefs.push_enabled,
    }


# ═══════════════════════════════════════════════════════
# 개인화 뉴스 피드 엔드포인트
# ═══════════════════════════════════════════════════════


@router.get("/feed")
async def get_personalized_feed(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """개인화된 뉴스 피드를 반환한다.

    관심 종목/섹터가 설정된 경우 해당 뉴스를 우선 반환하고,
    설정이 없으면 전체 뉴스를 반환한다.
    """
    from sqlalchemy import or_
    from app.routers.utils import format_articles

    prefs = db.query(UserPreferences).filter(UserPreferences.user_id == current_user.id).first()

    followed_stock_ids: list[int] = []
    followed_sector_ids: list[int] = []

    if prefs:
        followed_stock_ids = prefs.followed_stock_ids or []
        followed_sector_ids = prefs.followed_sector_ids or []

    personalized = bool(followed_stock_ids or followed_sector_ids)

    from sqlalchemy.orm import selectinload

    if personalized:
        # 관심 종목·섹터 관련 뉴스 조회 (NewsStockRelation 경유)
        relation_filters = []
        if followed_stock_ids:
            relation_filters.append(NewsStockRelation.stock_id.in_(followed_stock_ids))
        if followed_sector_ids:
            relation_filters.append(NewsStockRelation.sector_id.in_(followed_sector_ids))

        # 관련 뉴스 ID 서브쿼리
        related_news_ids_subq = (
            db.query(NewsStockRelation.news_id)
            .filter(or_(*relation_filters))
            .distinct()
            .subquery()
        )

        total = (
            db.query(NewsArticle)
            .filter(NewsArticle.id.in_(db.query(related_news_ids_subq)))
            .count()
        )

        articles = (
            db.query(NewsArticle)
            .options(
                selectinload(NewsArticle.relations).selectinload(NewsStockRelation.stock),
                selectinload(NewsArticle.relations).selectinload(NewsStockRelation.sector),
            )
            .filter(NewsArticle.id.in_(db.query(related_news_ids_subq)))
            .order_by(NewsArticle.published_at.desc().nullslast())
            .offset(offset)
            .limit(limit)
            .all()
        )
    else:
        # 전체 뉴스 반환 (개인화 설정 없음)
        total = db.query(NewsArticle).count()
        articles = (
            db.query(NewsArticle)
            .options(
                selectinload(NewsArticle.relations).selectinload(NewsStockRelation.stock),
                selectinload(NewsArticle.relations).selectinload(NewsStockRelation.sector),
            )
            .order_by(NewsArticle.published_at.desc().nullslast())
            .offset(offset)
            .limit(limit)
            .all()
        )

    formatted = format_articles(articles)
    return {
        "articles": formatted,
        "total": total,
        "personalized": personalized,
    }
