import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session, subqueryload

from app.database import get_db
from app.models.sector import Sector
from app.models.stock import Stock
from app.models.news import NewsArticle
from app.models.news_relation import NewsStockRelation
from app.schemas.stock import StockCreate, StockResponse
from app.schemas.news import NewsArticleResponse
from app.routers.utils import format_articles
from app.seed.sectors import seed_sectors
from app.seed.stocks import seed_all_stocks

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["stocks"])


@router.post("/sectors/{sector_id}/stocks", response_model=StockResponse, status_code=201)
async def create_stock(sector_id: int, body: StockCreate, db: Session = Depends(get_db)):
    sector = db.query(Sector).filter(Sector.id == sector_id).first()
    if not sector:
        raise HTTPException(status_code=404, detail="Sector not found")

    stock = Stock(
        sector_id=sector_id,
        name=body.name,
        stock_code=body.stock_code,
        keywords=body.keywords,
    )
    db.add(stock)
    db.commit()
    db.refresh(stock)
    return stock


@router.post("/stocks/sync")
async def sync_stocks(db: Session = Depends(get_db)):
    """Re-seed sectors (fix bad mappings) then re-fetch all stocks from KRX."""
    sector_count_before = db.query(Sector).count()
    seed_sectors(db)
    sector_count_after = db.query(Sector).count()

    current_count = db.query(Stock).count()
    added = seed_all_stocks(db, force=True)
    return {
        "message": (
            f"Sync complete. Sectors: {sector_count_before} → {sector_count_after}. "
            f"Stocks: {added} synced (was {current_count})."
        ),
        "sectors_before": sector_count_before,
        "sectors_after": sector_count_after,
        "stocks_synced": added,
        "stocks_previous": current_count,
    }


@router.delete("/stocks/{stock_id}", status_code=204)
async def delete_stock(stock_id: int, db: Session = Depends(get_db)):
    stock = db.query(Stock).filter(Stock.id == stock_id).first()
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")
    db.delete(stock)
    db.commit()


@router.get("/stocks/{stock_id}/news")
async def get_stock_news(stock_id: int, limit: int = 30, offset: int = 0, db: Session = Depends(get_db)):
    stock = db.query(Stock).filter(Stock.id == stock_id).first()
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")

    # Subquery instead of loading all relation objects into Python
    news_ids_subq = (
        db.query(NewsStockRelation.news_id)
        .filter(NewsStockRelation.stock_id == stock_id)
        .distinct()
        .subquery()
    )

    total = db.query(func.count()).select_from(news_ids_subq).scalar()

    articles = (
        db.query(NewsArticle)
        .options(
            subqueryload(NewsArticle.relations).subqueryload(NewsStockRelation.stock),
            subqueryload(NewsArticle.relations).subqueryload(NewsStockRelation.sector),
        )
        .filter(NewsArticle.id.in_(db.query(news_ids_subq)))
        .order_by(NewsArticle.published_at.desc().nullslast())
        .offset(offset)
        .limit(limit)
        .all()
    )

    data = format_articles(articles)
    return JSONResponse(
        content=jsonable_encoder(data),
        headers={"X-Total-Count": str(total), "Access-Control-Expose-Headers": "X-Total-Count"},
    )
