"""원자재 가격 추적 및 뉴스 API 라우터."""

import logging
import math

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select

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


def _safe_float(v: float | None) -> float | None:
    """nan/inf를 None으로 변환 (JSON 직렬화 오류 방지)."""
    return None if v is None or (isinstance(v, float) and not math.isfinite(v)) else v


@router.get("", response_model=list[CommodityResponse])
async def list_commodities(db: Session = Depends(get_db)):
    """전체 원자재 목록 + 최신 가격 조회."""
    commodities = db.query(Commodity).order_by(Commodity.category, Commodity.name_ko).all()
    if not commodities:
        return []

    # 최신 가격 단일 쿼리 — commodity_id별 max recorded_at 서브쿼리로 N+1 제거
    commodity_ids = [c.id for c in commodities]
    latest_subq = (
        select(
            CommodityPrice.commodity_id,
            func.max(CommodityPrice.recorded_at).label("max_at"),
        )
        .where(CommodityPrice.commodity_id.in_(commodity_ids))
        .group_by(CommodityPrice.commodity_id)
        .subquery()
    )
    latest_prices_q = (
        db.query(CommodityPrice)
        .join(
            latest_subq,
            (CommodityPrice.commodity_id == latest_subq.c.commodity_id)
            & (CommodityPrice.recorded_at == latest_subq.c.max_at),
        )
    )
    latest_map: dict[int, CommodityPrice] = {lp.commodity_id: lp for lp in latest_prices_q}

    results = []
    for commodity in commodities:
        latest = latest_map.get(commodity.id)
        results.append(CommodityResponse(
            id=commodity.id,
            symbol=commodity.symbol,
            name_ko=commodity.name_ko,
            name_en=commodity.name_en,
            category=commodity.category,
            unit=commodity.unit,
            currency=commodity.currency,
            created_at=commodity.created_at,
            latest_price=_safe_float(latest.price if latest else None),
            change_pct=_safe_float(latest.change_pct if latest else None),
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

    # 원자재 관계 정보를 배치로 로드하여 N+1 제거
    article_ids = [a.id for a in articles]
    all_rels = (
        db.query(NewsCommodityRelation)
        .filter(NewsCommodityRelation.news_id.in_(article_ids))
        .all()
    ) if article_ids else []

    # 원자재 정보 한 번에 로드
    rel_commodity_ids = list({r.commodity_id for r in all_rels})
    commodity_map: dict[int, Commodity] = {}
    if rel_commodity_ids:
        for c in db.query(Commodity).filter(Commodity.id.in_(rel_commodity_ids)).all():
            commodity_map[c.id] = c

    # news_id → relations 그룹핑
    rels_by_news: dict[int, list[NewsCommodityRelation]] = {}
    for r in all_rels:
        rels_by_news.setdefault(r.news_id, []).append(r)

    result = []
    for article in articles:
        article_dict = format_articles([article])[0].model_dump()
        commodity_info = []
        for cr in rels_by_news.get(article.id, []):
            c = commodity_map.get(cr.commodity_id)
            if c:
                commodity_info.append({
                    "commodity_id": c.id,
                    "name_ko": c.name_ko,
                    "symbol": c.symbol,
                    "relevance": cr.relevance,
                    "impact_direction": cr.impact_direction,
                })
        article_dict["commodity_relations"] = commodity_info
        result.append(article_dict)

    data = jsonable_encoder({"articles": result, "total": total})
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

    data = jsonable_encoder({"articles": format_articles(articles), "total": total})
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
            latest_price=_safe_float(latest.price if latest else None),
            change_pct=_safe_float(latest.change_pct if latest else None),
        ))

    return results
