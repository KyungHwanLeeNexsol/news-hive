from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, subqueryload

from app.database import get_db
from app.models.sector import Sector
from app.models.stock import Stock
from app.models.news import NewsArticle
from app.models.news_relation import NewsStockRelation
from app.schemas.sector import SectorCreate, SectorResponse, SectorDetailResponse
from app.schemas.news import NewsArticleResponse
from app.routers.utils import format_articles

router = APIRouter(prefix="/api/sectors", tags=["sectors"])


@router.get("", response_model=list[SectorResponse])
async def list_sectors(db: Session = Depends(get_db)):
    from app.services.naver_finance import fetch_sector_performances

    rows = (
        db.query(Sector, func.count(Stock.id).label("stock_count"))
        .outerjoin(Stock, Sector.id == Stock.sector_id)
        .group_by(Sector.id)
        .order_by(Sector.id)
        .all()
    )

    # Fetch cached performance data (non-blocking, uses 5-min cache)
    perf_data = await fetch_sector_performances()

    results = []
    for sector, stock_count in rows:
        resp = SectorResponse.model_validate(sector)
        resp.stock_count = stock_count

        # Merge Naver performance data by naver_code
        if sector.naver_code and sector.naver_code in perf_data:
            perf = perf_data[sector.naver_code]
            resp.change_rate = perf.change_rate
            resp.total_stocks = perf.total_stocks
            resp.rising_stocks = perf.rising_stocks
            resp.flat_stocks = perf.flat_stocks
            resp.falling_stocks = perf.falling_stocks

        results.append(resp)

    # Sort by change_rate descending (sectors without data go to the end)
    results.sort(
        key=lambda s: (s.change_rate is not None, s.change_rate or 0),
        reverse=True,
    )
    return results


@router.post("", response_model=SectorDetailResponse, status_code=201)
async def create_sector(body: SectorCreate, db: Session = Depends(get_db)):
    sector = Sector(name=body.name, is_custom=True)
    db.add(sector)
    db.commit()
    db.refresh(sector)
    return sector


@router.get("/{sector_id}", response_model=SectorDetailResponse)
async def get_sector(sector_id: int, db: Session = Depends(get_db)):
    sector = db.query(Sector).filter(Sector.id == sector_id).first()
    if not sector:
        raise HTTPException(status_code=404, detail="Sector not found")
    stocks = (
        db.query(Stock)
        .filter(Stock.sector_id == sector_id)
        .order_by(Stock.name)
        .all()
    )
    sector.stocks = stocks
    return sector


@router.delete("/{sector_id}", status_code=204)
async def delete_sector(sector_id: int, db: Session = Depends(get_db)):
    sector = db.query(Sector).filter(Sector.id == sector_id).first()
    if not sector:
        raise HTTPException(status_code=404, detail="Sector not found")
    if not sector.is_custom:
        raise HTTPException(status_code=400, detail="Cannot delete default sector")
    db.delete(sector)
    db.commit()


@router.get("/{sector_id}/news", response_model=list[NewsArticleResponse])
async def get_sector_news(sector_id: int, db: Session = Depends(get_db)):
    sector = db.query(Sector).filter(Sector.id == sector_id).first()
    if not sector:
        raise HTTPException(status_code=404, detail="Sector not found")

    # Single subquery instead of 3 separate queries
    stock_ids_subq = (
        db.query(Stock.id).filter(Stock.sector_id == sector_id).subquery()
    )
    news_ids_subq = (
        db.query(NewsStockRelation.news_id)
        .filter(
            (NewsStockRelation.sector_id == sector_id)
            | (NewsStockRelation.stock_id.in_(db.query(stock_ids_subq)))
        )
        .distinct()
        .subquery()
    )

    articles = (
        db.query(NewsArticle)
        .options(
            subqueryload(NewsArticle.relations).subqueryload(NewsStockRelation.stock),
            subqueryload(NewsArticle.relations).subqueryload(NewsStockRelation.sector),
        )
        .filter(NewsArticle.id.in_(db.query(news_ids_subq)))
        .order_by(NewsArticle.published_at.desc().nullslast())
        .limit(50)
        .all()
    )

    return format_articles(articles)
