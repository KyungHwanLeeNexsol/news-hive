import asyncio
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import func, cast, Date
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
from app.services.naver_finance import (
    fetch_stock_fundamentals, fetch_stock_fundamentals_batch,
    fetch_stock_price_history, fetch_market_cap_rankings,
)
from app.services.financial_scraper import fetch_stock_valuation, fetch_stock_financials
from app.services.kis_api import fetch_kis_stock_price

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
    ids: str = Query(default="", description="Comma-separated stock IDs"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """List stocks sorted by market cap with realtime prices.

    For watchlist (ids) or search (q) queries, uses polling API batch fetch.
    Otherwise, uses Naver market cap ranking page for pre-sorted data.
    """
    # --- Watchlist or search mode: query DB + batch polling API ---
    if ids or q or sector_id:
        query = db.query(Stock).join(Sector, Stock.sector_id == Sector.id)

        if ids:
            id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()]
            if id_list:
                query = query.filter(Stock.id.in_(id_list))

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
        stocks = query.order_by(Stock.name).all()

        # Batch fetch prices
        stock_codes = [s.stock_code for s in stocks]
        prices = await fetch_stock_fundamentals_batch(stock_codes) if stock_codes else {}

        # News counts
        stock_ids = [s.id for s in stocks]
        news_counts: dict[int, int] = {}
        if stock_ids:
            rows = (
                db.query(NewsStockRelation.stock_id, func.count(func.distinct(NewsStockRelation.news_id)))
                .filter(NewsStockRelation.stock_id.in_(stock_ids))
                .group_by(NewsStockRelation.stock_id)
                .all()
            )
            news_counts = {r[0]: r[1] for r in rows}

        items = []
        for s in stocks:
            fund = prices.get(s.stock_code)
            items.append(StockListItem(
                id=s.id,
                name=s.name,
                stock_code=s.stock_code,
                sector_id=s.sector_id,
                sector_name=s.sector.name if s.sector else None,
                market=s.market,
                current_price=fund.current_price if fund else None,
                price_change=fund.price_change if fund else None,
                change_rate=fund.change_rate if fund else None,
                volume=fund.volume if fund else None,
                trading_value=fund.trading_value if fund else None,
                market_cap=None,
                news_count=news_counts.get(s.id, 0),
            ))

        # Sort by trading_value descending
        items.sort(key=lambda x: x.trading_value or 0, reverse=True)
        # Apply pagination after sort
        paginated = items[offset:offset + limit]

        return JSONResponse(
            content=jsonable_encoder(paginated),
            headers={
                "X-Total-Count": str(total),
                "Access-Control-Expose-Headers": "X-Total-Count",
            },
        )

    # --- Default mode: Naver market cap ranking (pre-sorted) ---
    rankings = await fetch_market_cap_rankings()

    # Filter by market
    if market:
        rankings = [r for r in rankings if r.market == market.upper()]

    # Build stock_code → DB stock lookup
    all_codes = [r.stock_code for r in rankings]
    db_stocks = (
        db.query(Stock)
        .join(Sector, Stock.sector_id == Sector.id)
        .filter(Stock.stock_code.in_(all_codes))
        .all()
    )
    code_to_stock: dict[str, Stock] = {s.stock_code: s for s in db_stocks}

    # News counts for matched stocks
    matched_ids = [s.id for s in db_stocks]
    news_counts = {}
    if matched_ids:
        rows = (
            db.query(NewsStockRelation.stock_id, func.count(func.distinct(NewsStockRelation.news_id)))
            .filter(NewsStockRelation.stock_id.in_(matched_ids))
            .group_by(NewsStockRelation.stock_id)
            .all()
        )
        news_counts = {r[0]: r[1] for r in rows}

    # Build response — only stocks that exist in our DB
    items = []
    for r in rankings:
        stock = code_to_stock.get(r.stock_code)
        if not stock:
            continue
        items.append(StockListItem(
            id=stock.id,
            name=stock.name,
            stock_code=stock.stock_code,
            sector_id=stock.sector_id,
            sector_name=stock.sector.name if stock.sector else None,
            market=r.market,
            current_price=r.current_price or None,
            price_change=r.price_change or None,
            change_rate=r.change_rate or None,
            volume=r.volume or None,
            trading_value=None,
            market_cap=r.market_cap or None,
            news_count=news_counts.get(stock.id, 0),
        ))

    total = len(items)
    paginated = items[offset:offset + limit]

    return JSONResponse(
        content=jsonable_encoder(paginated),
        headers={
            "X-Total-Count": str(total),
            "Access-Control-Expose-Headers": "X-Total-Count",
        },
    )


@router.get("/stocks/{stock_id}", response_model=StockDetailResponse)
async def get_stock_detail(stock_id: int, db: Session = Depends(get_db)):
    """Stock detail with realtime fundamentals + valuation metrics.

    Data sources (in priority order):
    1. KIS API — 52w high/low, PER, PBR, foreign ratio, market cap
    2. Naver polling API — realtime price, EPS, BPS, dividend
    3. WiseReport scraper — valuation fallback, industry PER
    """
    stock = db.query(Stock).filter(Stock.id == stock_id).first()
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")

    sector_name = stock.sector.name if stock.sector else None

    # Fetch all data sources in parallel
    fundamentals, valuation, kis = await asyncio.gather(
        fetch_stock_fundamentals(stock.stock_code),
        fetch_stock_valuation(stock.stock_code),
        fetch_kis_stock_price(stock.stock_code),
    )

    # KIS provides richer data — use it as primary for fields it covers
    return StockDetailResponse(
        id=stock.id,
        name=stock.name,
        stock_code=stock.stock_code,
        sector_id=stock.sector_id,
        sector_name=sector_name,
        # Realtime price (KIS primary, Naver fallback)
        current_price=(kis.current_price if kis else None) or (fundamentals.current_price if fundamentals else None),
        price_change=(kis.price_change if kis else None) or (fundamentals.price_change if fundamentals else None),
        change_rate=(kis.change_rate if kis else None) or (fundamentals.change_rate if fundamentals else None),
        volume=(kis.volume if kis else None) or (fundamentals.volume if fundamentals else None),
        trading_value=(kis.trading_value if kis else None) or (fundamentals.trading_value if fundamentals else None),
        # Fundamentals (KIS primary, Naver fallback)
        eps=(kis.eps if kis and kis.eps else None) or (fundamentals.eps if fundamentals else None),
        bps=(kis.bps if kis and kis.bps else None) or (fundamentals.bps if fundamentals else None),
        dividend=fundamentals.dividend if fundamentals else None,
        # 52w range (KIS only — Naver polling API doesn't provide this)
        high_52w=kis.high_52w if kis and kis.high_52w else None,
        low_52w=kis.low_52w if kis and kis.low_52w else None,
        # Valuation (KIS primary, WiseReport fallback)
        per=(kis.per if kis and kis.per else None) or (valuation.per if valuation else None),
        pbr=(kis.pbr if kis and kis.pbr else None) or (valuation.pbr if valuation else None),
        market_cap=(kis.market_cap if kis and kis.market_cap else None) or (valuation.market_cap if valuation else None),
        foreign_ratio=(kis.foreign_ratio if kis and kis.foreign_ratio else None) or (valuation.foreign_ratio if valuation else None),
        dividend_yield=valuation.dividend_yield if valuation else None,
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
                "is_estimate": fp.is_estimate,
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
                "is_estimate": fp.is_estimate,
                "revenue": fp.revenue, "operating_profit": fp.operating_profit,
                "operating_margin": fp.operating_margin, "net_income": fp.net_income,
                "eps": fp.eps, "bps": fp.bps, "roe": fp.roe,
                "dividend_payout": fp.dividend_payout,
            })
            for fp in data.get("quarter", [])
        ],
    )


@router.get("/stocks/{stock_id}/sentiment-trend")
async def get_stock_sentiment_trend(
    stock_id: int,
    days: int = Query(default=30, ge=7, le=90),
    db: Session = Depends(get_db),
):
    """Daily sentiment distribution for a stock's news over the last N days."""
    stock = db.query(Stock).filter(Stock.id == stock_id).first()
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")

    since = datetime.utcnow() - timedelta(days=days)

    rows = (
        db.query(
            cast(NewsArticle.published_at, Date).label("date"),
            NewsArticle.sentiment,
            func.count().label("cnt"),
        )
        .join(NewsStockRelation, NewsStockRelation.news_id == NewsArticle.id)
        .filter(
            NewsStockRelation.stock_id == stock_id,
            NewsArticle.published_at >= since,
            NewsArticle.sentiment.isnot(None),
        )
        .group_by(cast(NewsArticle.published_at, Date), NewsArticle.sentiment)
        .order_by(cast(NewsArticle.published_at, Date))
        .all()
    )

    # Aggregate into {date: {positive, negative, neutral}}
    trend: dict[str, dict[str, int]] = {}
    for row in rows:
        d = str(row.date)
        if d not in trend:
            trend[d] = {"date": d, "positive": 0, "negative": 0, "neutral": 0}
        sentiment = row.sentiment or "neutral"
        if sentiment in trend[d]:
            trend[d][sentiment] = row.cnt

    return list(trend.values())


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
