import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models.sector import Sector
from app.models.stock import Stock
from app.models.news import NewsArticle
from app.models.news_relation import NewsStockRelation
from app.schemas.stock import (
    StockCreate, StockResponse, StockListItem, StockDetailResponse,
    PriceRecordResponse, FinancialPeriodResponse, FinancialsResponse,
)
from app.schemas.news import NewsArticleResponse
from app.routers.utils import format_articles
from app.seed.sectors import seed_sectors
from app.seed.stocks import seed_all_stocks
from app.services.naver_finance import fetch_stock_fundamentals, fetch_stock_price_history
from app.services.financial_scraper import fetch_stock_valuation, fetch_stock_financials

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


@router.get("/stocks")
async def list_stocks(
    q: str = Query(default="", description="Search by name or stock code"),
    market: str = Query(default="", description="Filter by market: KOSPI or KOSDAQ"),
    sector_id: int = Query(default=0, description="Filter by sector ID"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """List all stocks with search, market filter, and pagination."""
    query = db.query(Stock).join(Sector, Stock.sector_id == Sector.id)

    if q:
        search = f"%{q}%"
        query = query.filter(
            (Stock.name.ilike(search)) | (Stock.stock_code.ilike(search))
        )

    if market:
        query = query.filter(Stock.market == market.upper())

    if sector_id:
        query = query.filter(Stock.sector_id == sector_id)

    total = query.count()

    stocks = (
        query.order_by(Stock.name)
        .offset(offset)
        .limit(limit)
        .all()
    )

    items = [
        StockListItem(
            id=s.id,
            name=s.name,
            stock_code=s.stock_code,
            sector_id=s.sector_id,
            sector_name=s.sector.name if s.sector else None,
            market=s.market,
        )
        for s in stocks
    ]

    return JSONResponse(
        content=jsonable_encoder(items),
        headers={
            "X-Total-Count": str(total),
            "Access-Control-Expose-Headers": "X-Total-Count",
        },
    )


@router.get("/stocks/{stock_id}", response_model=StockDetailResponse)
async def get_stock_detail(stock_id: int, db: Session = Depends(get_db)):
    """Stock detail with realtime fundamentals + valuation metrics."""
    stock = db.query(Stock).filter(Stock.id == stock_id).first()
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")

    sector_name = stock.sector.name if stock.sector else None

    # Fetch fundamentals and valuation in parallel
    fundamentals, valuation = await asyncio.gather(
        fetch_stock_fundamentals(stock.stock_code),
        fetch_stock_valuation(stock.stock_code),
    )

    return StockDetailResponse(
        id=stock.id,
        name=stock.name,
        stock_code=stock.stock_code,
        sector_id=stock.sector_id,
        sector_name=sector_name,
        # Realtime
        current_price=fundamentals.current_price if fundamentals else None,
        price_change=fundamentals.price_change if fundamentals else None,
        change_rate=fundamentals.change_rate if fundamentals else None,
        eps=fundamentals.eps if fundamentals else None,
        bps=fundamentals.bps if fundamentals else None,
        dividend=fundamentals.dividend if fundamentals else None,
        high_52w=fundamentals.high_52w if fundamentals else None,
        low_52w=fundamentals.low_52w if fundamentals else None,
        volume=fundamentals.volume if fundamentals else None,
        trading_value=fundamentals.trading_value if fundamentals else None,
        # Valuation
        per=valuation.per if valuation else None,
        pbr=valuation.pbr if valuation else None,
        market_cap=valuation.market_cap if valuation else None,
        dividend_yield=valuation.dividend_yield if valuation else None,
        foreign_ratio=valuation.foreign_ratio if valuation else None,
        industry_per=valuation.industry_per if valuation else None,
    )


@router.get("/stocks/{stock_id}/prices", response_model=list[PriceRecordResponse])
async def get_stock_prices(
    stock_id: int,
    months: int = Query(default=3, ge=1, le=12),
    db: Session = Depends(get_db),
):
    """Daily OHLCV price history."""
    stock = db.query(Stock).filter(Stock.id == stock_id).first()
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")

    pages = max(1, min(months * 2, 20))
    prices = await fetch_stock_price_history(stock.stock_code, pages=pages)
    return [
        PriceRecordResponse(
            date=p.date, close=p.close, open=p.open,
            high=p.high, low=p.low, volume=p.volume,
        )
        for p in prices
    ]


@router.get("/stocks/{stock_id}/financials", response_model=FinancialsResponse)
async def get_stock_financials(stock_id: int, db: Session = Depends(get_db)):
    """Annual + quarterly financial statements."""
    stock = db.query(Stock).filter(Stock.id == stock_id).first()
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")

    data = await fetch_stock_financials(stock.stock_code)
    return FinancialsResponse(
        annual=[
            FinancialPeriodResponse(**{
                "period": fp.period, "period_type": fp.period_type,
                "revenue": fp.revenue, "operating_profit": fp.operating_profit,
                "operating_margin": fp.operating_margin, "net_income": fp.net_income,
                "eps": fp.eps, "bps": fp.bps, "roe": fp.roe,
                "dividend_payout": fp.dividend_payout,
            })
            for fp in data.get("annual", [])
        ],
        quarter=[
            FinancialPeriodResponse(**{
                "period": fp.period, "period_type": fp.period_type,
                "revenue": fp.revenue, "operating_profit": fp.operating_profit,
                "operating_margin": fp.operating_margin, "net_income": fp.net_income,
                "eps": fp.eps, "bps": fp.bps, "roe": fp.roe,
                "dividend_payout": fp.dividend_payout,
            })
            for fp in data.get("quarter", [])
        ],
    )


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
            selectinload(NewsArticle.relations).selectinload(NewsStockRelation.stock),
            selectinload(NewsArticle.relations).selectinload(NewsStockRelation.sector),
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
