import asyncio
import logging
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import func, cast, Date
from sqlalchemy.orm import Session, joinedload, selectinload

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
    fetch_stock_price_history, fetch_naver_stock_list,
)
from app.services.financial_scraper import fetch_stock_valuation, fetch_stock_financials
from app.services.kis_api import fetch_kis_stock_price

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["stocks"])

# --- Endpoint-level response cache ---
_response_cache: dict[str, tuple[float, object, str]] = {}  # key -> (expires, data, total)


def _response_cache_ttl() -> int:
    from app.services.naver_finance import _is_market_open
    return 10 if _is_market_open() else 120


def _cache_key(q: str, market: str, sector_id: int, ids: str, limit: int, offset: int) -> str:
    return f"stocks:{q}:{market}:{sector_id}:{ids}:{limit}:{offset}"


def _get_cached(key: str):
    if key in _response_cache:
        expires, data, total = _response_cache[key]
        if time.time() < expires:
            return data, total
        del _response_cache[key]
    return None


def _set_cached(key: str, data, total: str):
    _response_cache[key] = (time.time() + _response_cache_ttl(), data, total)


def _get_news_counts(db: Session, stock_ids: list[int]) -> dict[int, int]:
    """Single query to get news counts for all stocks."""
    if not stock_ids:
        return {}
    rows = (
        db.query(
            NewsStockRelation.stock_id,
            func.count(func.distinct(NewsStockRelation.news_id)),
        )
        .filter(NewsStockRelation.stock_id.in_(stock_ids))
        .group_by(NewsStockRelation.stock_id)
        .all()
    )
    return {r[0]: r[1] for r in rows}


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
    """List stocks sorted by market cap with realtime prices."""

    # --- Check response cache first ---
    cache_key = _cache_key(q, market, sector_id, ids, limit, offset)
    cached = _get_cached(cache_key)
    if cached:
        data, total_str = cached
        return JSONResponse(
            content=data,
            headers={"X-Total-Count": total_str, "Access-Control-Expose-Headers": "X-Total-Count"},
        )

    # --- Watchlist or search mode ---
    if ids or q or sector_id:
        query = db.query(Stock).options(joinedload(Stock.sector))

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
        stocks = query.order_by(Stock.name).limit(limit).offset(offset).all()

        # Batch fetch prices only for this page's stocks
        stock_codes = [s.stock_code for s in stocks]
        prices = await fetch_stock_fundamentals_batch(stock_codes) if stock_codes else {}

        # Single news count query
        news_counts = _get_news_counts(db, [s.id for s in stocks])

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

        result = jsonable_encoder(items)
        total_str = str(total)
        _set_cached(cache_key, result, total_str)

        return JSONResponse(
            content=result,
            headers={"X-Total-Count": total_str, "Access-Control-Expose-Headers": "X-Total-Count"},
        )

    # --- Default mode: Naver Mobile API (JSON, real-time prices + market cap) ---
    markets_to_fetch = [market.upper()] if market else ["KOSPI", "KOSDAQ"]

    # Naver API uses 1-based pages; map our offset/limit
    naver_page = (offset // limit) + 1

    all_naver_items = []
    total = 0

    if len(markets_to_fetch) == 1:
        # Single market: straightforward pagination
        naver_items, naver_total = await fetch_naver_stock_list(
            market=markets_to_fetch[0], page=naver_page, page_size=limit,
        )
        all_naver_items = naver_items
        total = naver_total
    else:
        # Combined: fetch same page from both, merge by market_cap, take `limit`
        import asyncio as _aio
        results = await _aio.gather(
            fetch_naver_stock_list(market="KOSPI", page=naver_page, page_size=limit),
            fetch_naver_stock_list(market="KOSDAQ", page=naver_page, page_size=limit),
        )
        for naver_items, naver_total in results:
            all_naver_items.extend(naver_items)
            total += naver_total
        # Sort combined list by market_cap descending and take top `limit`
        all_naver_items.sort(key=lambda x: x.market_cap, reverse=True)
        all_naver_items = all_naver_items[:limit]

    # Match Naver data with DB stocks for sector info + news counts
    naver_codes = [n.stock_code for n in all_naver_items]
    db_stocks = (
        db.query(Stock)
        .options(joinedload(Stock.sector))
        .filter(Stock.stock_code.in_(naver_codes))
        .all()
    ) if naver_codes else []
    code_to_stock: dict[str, Stock] = {s.stock_code: s for s in db_stocks}
    news_counts = _get_news_counts(db, [s.id for s in db_stocks])

    items = []
    for n in all_naver_items:
        stock = code_to_stock.get(n.stock_code)
        items.append(StockListItem(
            id=stock.id if stock else 0,
            name=stock.name if stock else n.name,
            stock_code=n.stock_code,
            sector_id=stock.sector_id if stock else 0,
            sector_name=stock.sector.name if stock and stock.sector else None,
            market=n.market,
            current_price=n.current_price,
            price_change=n.price_change,
            change_rate=n.change_rate,
            volume=n.volume,
            trading_value=n.trading_value,
            market_cap=n.market_cap,
            news_count=news_counts.get(stock.id, 0) if stock else 0,
        ))

    result = jsonable_encoder(items)
    total_str = str(total)
    _set_cached(cache_key, result, total_str)

    return JSONResponse(
        content=result,
        headers={"X-Total-Count": total_str, "Access-Control-Expose-Headers": "X-Total-Count"},
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


@router.get("/stocks/{stock_id}/news-impact-stats")
async def get_stock_news_impact_stats(
    stock_id: int,
    days: int = Query(default=30, ge=7, le=90),
    db: Session = Depends(get_db),
):
    """종목의 뉴스-가격 반응 통계 (REQ-NPI-011, 012, 013)."""
    from app.services.news_price_impact_service import get_stock_impact_stats
    from app.schemas.news_price_impact import StockNewsImpactStatsResponse

    stock = db.query(Stock).filter(Stock.id == stock_id).first()
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")

    stats = await get_stock_impact_stats(db, stock_id, days)
    return StockNewsImpactStatsResponse(stock_id=stock_id, **stats)


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
