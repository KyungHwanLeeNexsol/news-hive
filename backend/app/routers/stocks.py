import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, subqueryload

from app.database import get_db
from app.models.sector import Sector
from app.models.stock import Stock
from app.models.news import NewsArticle
from app.models.news_relation import NewsStockRelation
from app.schemas.stock import StockCreate, StockResponse
from app.schemas.news import NewsArticleResponse
from app.routers.utils import format_articles
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
    """Re-fetch all KOSPI/KOSDAQ stocks from KRX and sync to DB."""
    current_count = db.query(Stock).count()
    added = seed_all_stocks(db, force=True)
    return {
        "message": f"Stock sync complete. Added {added} new stocks. Total was {current_count}.",
        "added": added,
        "previous_total": current_count,
    }


@router.delete("/stocks/{stock_id}", status_code=204)
async def delete_stock(stock_id: int, db: Session = Depends(get_db)):
    stock = db.query(Stock).filter(Stock.id == stock_id).first()
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")
    db.delete(stock)
    db.commit()


@router.get("/stocks/{stock_id}/news", response_model=list[NewsArticleResponse])
async def get_stock_news(stock_id: int, db: Session = Depends(get_db)):
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
