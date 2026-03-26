"""원자재 가격 추적 및 뉴스 API 라우터."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models.commodity import Commodity, CommodityPrice, SectorCommodityRelation
from app.models.news import NewsArticle
from app.models.news_commodity_relation import NewsCommodityRelation
from app.models.news_relation import NewsStockRelation
from app.models.sector import Sector
from app.routers.utils import format_articles
from app.schemas.commodity import (
    CommodityHistoryResponse,
    CommodityRefreshResponse,
    CommodityResponse,
    SectorCommodityResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/commodities", tags=["commodities"])


@router.get("", response_model=list[CommodityResponse])
async def list_commodities(db: Session = Depends(get_db)):
    """전체 원자재 목록 + 최신 가격 조회."""
    commodities = db.query(Commodity).order_by(Commodity.category, Commodity.name_ko).all()

    results = []
    for commodity in commodities:
        # 최신 가격 조회
        latest = (
            db.query(CommodityPrice)
            .filter(CommodityPrice.commodity_id == commodity.id)
            .order_by(CommodityPrice.recorded_at.desc())
            .first()
        )
        results.append(CommodityResponse(
            id=commodity.id,
            symbol=commodity.symbol,
            name_ko=commodity.name_ko,
            name_en=commodity.name_en,
            category=commodity.category,
            unit=commodity.unit,
            currency=commodity.currency,
            created_at=commodity.created_at,
            latest_price=latest.price if latest else None,
            change_pct=latest.change_pct if latest else None,
        ))

    return results


@router.get("/{commodity_id}/history", response_model=list[CommodityHistoryResponse])
async def get_commodity_history(
    commodity_id: int,
    period: str = "1mo",
    db: Session = Depends(get_db),
):
    """원자재 과거 가격 히스토리 (OHLCV)."""
    commodity = db.query(Commodity).filter(Commodity.id == commodity_id).first()
    if not commodity:
        raise HTTPException(status_code=404, detail="원자재를 찾을 수 없습니다")

    from app.services.commodity_service import fetch_commodity_history

    history = fetch_commodity_history(commodity.symbol, period=period)
    return [CommodityHistoryResponse(**item) for item in history]


@router.post("/refresh", response_model=CommodityRefreshResponse)
async def refresh_prices(db: Session = Depends(get_db)):
    """수동 원자재 가격 수집 트리거."""
    from app.services.commodity_service import fetch_commodity_prices, check_commodity_alerts

    updated = fetch_commodity_prices(db)
    alerts = check_commodity_alerts(db)

    message = f"{updated}개 원자재 가격 업데이트 완료"
    if alerts:
        message += f", {len(alerts)}개 급변 알림 생성"

    return CommodityRefreshResponse(updated_count=updated, message=message)


@router.get("/news")
async def list_commodity_news(
    limit: int = 30,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """전체 원자재 관련 뉴스 피드."""
    # news_commodity_relations를 통해 원자재 관련 뉴스 조회
    news_ids_subq = (
        db.query(NewsCommodityRelation.news_id)
        .distinct()
        .subquery()
    )

    total = db.query(func.count()).select_from(news_ids_subq).scalar()

    articles = (
        db.query(NewsArticle)
        .options(
            selectinload(NewsArticle.relations).selectinload(NewsStockRelation.stock),
            selectinload(NewsArticle.relations).selectinload(NewsStockRelation.sector),
        )
        .filter(NewsArticle.id.in_(news_ids_subq.select()))
        .order_by(NewsArticle.published_at.desc().nullslast())
        .offset(offset)
        .limit(limit)
        .all()
    )

    # 원자재 관계 정보를 추가하여 응답
    result = []
    for article in articles:
        article_data = format_articles([article])[0]
        # 원자재 관계 정보 추가
        commodity_rels = (
            db.query(NewsCommodityRelation)
            .filter(NewsCommodityRelation.news_id == article.id)
            .all()
        )
        commodity_info = []
        for cr in commodity_rels:
            commodity = db.query(Commodity).filter(Commodity.id == cr.commodity_id).first()
            if commodity:
                commodity_info.append({
                    "commodity_id": commodity.id,
                    "name_ko": commodity.name_ko,
                    "symbol": commodity.symbol,
                    "relevance": cr.relevance,
                    "impact_direction": cr.impact_direction,
                })
        # Pydantic 모델을 dict로 변환 후 commodity_relations 추가
        article_dict = article_data.model_dump()
        article_dict["commodity_relations"] = commodity_info
        result.append(article_dict)

    data = jsonable_encoder(result)
    return JSONResponse(
        content=data,
        headers={
            "X-Total-Count": str(total),
            "Access-Control-Expose-Headers": "X-Total-Count",
        },
    )


@router.get("/{commodity_id}/news")
async def get_commodity_news(
    commodity_id: int,
    limit: int = 30,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """특정 원자재 관련 뉴스 조회."""
    commodity = db.query(Commodity).filter(Commodity.id == commodity_id).first()
    if not commodity:
        raise HTTPException(status_code=404, detail="원자재를 찾을 수 없습니다")

    news_ids_subq = (
        db.query(NewsCommodityRelation.news_id)
        .filter(NewsCommodityRelation.commodity_id == commodity_id)
        .distinct()
        .subquery()
    )

    total = db.query(func.count()).select_from(news_ids_subq).scalar()

    articles = (
        db.query(NewsArticle)
        .options(
            selectinload(NewsArticle.relations).selectinload(NewsStockRelation.stock),
            selectinload(NewsArticle.relations).selectinload(NewsStockRelation.sector),
        )
        .filter(NewsArticle.id.in_(news_ids_subq.select()))
        .order_by(NewsArticle.published_at.desc().nullslast())
        .offset(offset)
        .limit(limit)
        .all()
    )

    data = jsonable_encoder(format_articles(articles))
    return JSONResponse(
        content=data,
        headers={
            "X-Total-Count": str(total),
            "Access-Control-Expose-Headers": "X-Total-Count",
        },
    )


# 섹터 라우터에 추가 엔드포인트 — 별도 라우터로 분리
sector_commodity_router = APIRouter(prefix="/api/sectors", tags=["sectors"])


@sector_commodity_router.get("/{sector_id}/commodities", response_model=list[SectorCommodityResponse])
async def get_sector_commodities(sector_id: int, db: Session = Depends(get_db)):
    """특정 섹터에 연관된 원자재 목록 + 최신 가격."""
    sector = db.query(Sector).filter(Sector.id == sector_id).first()
    if not sector:
        raise HTTPException(status_code=404, detail="섹터를 찾을 수 없습니다")

    relations = (
        db.query(SectorCommodityRelation)
        .filter(SectorCommodityRelation.sector_id == sector_id)
        .all()
    )

    results = []
    for rel in relations:
        commodity = db.query(Commodity).filter(Commodity.id == rel.commodity_id).first()
        if not commodity:
            continue

        # 최신 가격 조회
        latest = (
            db.query(CommodityPrice)
            .filter(CommodityPrice.commodity_id == commodity.id)
            .order_by(CommodityPrice.recorded_at.desc())
            .first()
        )

        results.append(SectorCommodityResponse(
            id=rel.id,
            commodity_id=commodity.id,
            symbol=commodity.symbol,
            name_ko=commodity.name_ko,
            name_en=commodity.name_en,
            category=commodity.category,
            correlation_type=rel.correlation_type,
            description=rel.description,
            latest_price=latest.price if latest else None,
            change_pct=latest.change_pct if latest else None,
        ))

    return results
