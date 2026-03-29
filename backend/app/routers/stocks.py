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


async def _set_cached_with_redis(key: str, data, total: str):
    """인메모리 + Redis 동시 저장."""
    _set_cached(key, data, total)
    try:
        from app.cache import cache_set
        await cache_set(f"api:stocks:{key}", {"data": data, "total": total}, ttl=_response_cache_ttl())
    except Exception:
        pass


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

    # --- Check response cache first (인메모리 → Redis 폴백) ---
    cache_key = _cache_key(q, market, sector_id, ids, limit, offset)
    cached = _get_cached(cache_key)
    if cached:
        data, total_str = cached
        return JSONResponse(
            content=data,
            headers={"X-Total-Count": total_str, "Access-Control-Expose-Headers": "X-Total-Count"},
        )
    # 인메모리 미스 시 Redis 조회
    try:
        from app.cache import cache_get
        redis_data = await cache_get(f"api:stocks:{cache_key}")
        if redis_data and isinstance(redis_data, dict):
            _set_cached(cache_key, redis_data["data"], redis_data["total"])
            return JSONResponse(
                content=redis_data["data"],
                headers={"X-Total-Count": redis_data["total"], "Access-Control-Expose-Headers": "X-Total-Count"},
            )
    except Exception:
        pass

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
        await _set_cached_with_redis(cache_key, result, total_str)

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
    await _set_cached_with_redis(cache_key, result, total_str)

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


@router.get("/stocks/{stock_id}/relations")
async def get_stock_relations(
    stock_id: int,
    db: Session = Depends(get_db),
):
    """종목의 관련 종목/섹터 관계 목록 조회."""
    from sqlalchemy import or_
    from app.models.stock_relation import StockRelation
    from app.schemas.stock_relation import StockRelationResponse, StockRelationListResponse

    stock = db.query(Stock).filter(Stock.id == stock_id).first()
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")

    # 종목이 source 또는 target인 관계 + 종목의 섹터가 source 또는 target인 관계
    relations = (
        db.query(StockRelation)
        .filter(
            or_(
                StockRelation.source_stock_id == stock_id,
                StockRelation.target_stock_id == stock_id,
                StockRelation.source_sector_id == stock.sector_id,
                StockRelation.target_sector_id == stock.sector_id,
            )
        )
        .order_by(StockRelation.confidence.desc())
        .all()
    )

    # 이름 매핑을 위해 관련 ID 수집
    stock_ids_set: set[int] = set()
    sector_ids_set: set[int] = set()
    for r in relations:
        if r.source_stock_id:
            stock_ids_set.add(r.source_stock_id)
        if r.target_stock_id:
            stock_ids_set.add(r.target_stock_id)
        if r.source_sector_id:
            sector_ids_set.add(r.source_sector_id)
        if r.target_sector_id:
            sector_ids_set.add(r.target_sector_id)

    stock_name_map: dict[int, str] = {}
    sector_name_map: dict[int, str] = {}

    if stock_ids_set:
        for s in db.query(Stock.id, Stock.name).filter(Stock.id.in_(list(stock_ids_set))).all():
            stock_name_map[s.id] = s.name
    if sector_ids_set:
        for s in db.query(Sector.id, Sector.name).filter(Sector.id.in_(list(sector_ids_set))).all():
            sector_name_map[s.id] = s.name

    items = []
    for r in relations:
        items.append(StockRelationResponse(
            id=r.id,
            source_stock_id=r.source_stock_id,
            source_stock_name=stock_name_map.get(r.source_stock_id) if r.source_stock_id else None,
            source_sector_id=r.source_sector_id,
            source_sector_name=sector_name_map.get(r.source_sector_id) if r.source_sector_id else None,
            target_stock_id=r.target_stock_id,
            target_stock_name=stock_name_map.get(r.target_stock_id) if r.target_stock_id else None,
            target_sector_id=r.target_sector_id,
            target_sector_name=sector_name_map.get(r.target_sector_id) if r.target_sector_id else None,
            relation_type=r.relation_type,
            confidence=r.confidence,
            reason=r.reason,
            created_at=r.created_at,
        ))

    return StockRelationListResponse(relations=items, total=len(items))


@router.post("/stocks/infer-relations")
async def infer_relations(db: Session = Depends(get_db)):
    """AI 기반 종목/섹터 관계 추론을 수동 실행한다."""
    from app.services.stock_relation_service import run_full_inference
    from app.schemas.stock_relation import InferRelationsResponse

    stats = await run_full_inference(db)
    return InferRelationsResponse(
        inter_sector=stats["inter_sector"],
        intra_sector=stats["intra_sector"],
        message=f"추론 완료: 섹터 간 {stats['inter_sector']}건, 섹터 내 {stats['intra_sector']}건",
    )


@router.delete("/stocks/relations/{relation_id}", status_code=204)
async def delete_relation(relation_id: int, db: Session = Depends(get_db)):
    """종목/섹터 관계를 삭제한다."""
    from app.models.stock_relation import StockRelation

    relation = db.query(StockRelation).filter(StockRelation.id == relation_id).first()
    if not relation:
        raise HTTPException(status_code=404, detail="Relation not found")
    db.delete(relation)
    db.commit()


@router.get("/stocks/{stock_id}/news-price-correlation")
async def get_news_price_correlation(
    stock_id: int,
    days: int = Query(default=90, ge=7, le=365),
    db: Session = Depends(get_db),
):
    """뉴스 감성 점수와 주가 변동의 7일 롤링 피어슨 상관계수.

    일별 감성 점수 = (positive 건수 - negative 건수) / 전체 건수
    일별 가격 변동률 = (종가 - 전일 종가) / 전일 종가 * 100
    7일 롤링 피어슨 상관계수로 뉴스-가격 연관성을 측정한다.
    """
    import math

    stock = db.query(Stock).filter(Stock.id == stock_id).first()
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")

    since = datetime.utcnow() - timedelta(days=days)

    # 1) 일별 감성 집계
    sentiment_rows = (
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
        .all()
    )

    # {date_str: {"positive": n, "negative": n, "neutral": n, ...}}
    daily_sentiment: dict[str, dict[str, int]] = {}
    for row in sentiment_rows:
        d = str(row.date)
        if d not in daily_sentiment:
            daily_sentiment[d] = {}
        daily_sentiment[d][row.sentiment] = row.cnt

    # 감성 점수 계산: (긍정 - 부정) / 전체
    def _calc_sentiment_score(counts: dict[str, int]) -> float:
        pos = counts.get("positive", 0) + counts.get("strong_positive", 0)
        neg = counts.get("negative", 0) + counts.get("strong_negative", 0)
        total = sum(counts.values())
        if total == 0:
            return 0.0
        return (pos - neg) / total

    # 2) 일별 가격 변동률 (네이버 가격 히스토리)
    from app.services.naver_finance import fetch_stock_price_history

    pages = max(1, min(days // 15, 20))
    prices = await fetch_stock_price_history(stock.stock_code, pages=pages)

    # 날짜 → 종가 맵 (prices는 최신순 정렬)
    price_map: dict[str, float] = {}
    for p in prices:
        price_map[p.date] = p.close

    # 날짜 정렬 (오래된 순)
    sorted_dates = sorted(price_map.keys())

    # 일별 가격 변동률
    price_changes: dict[str, float] = {}
    for i in range(1, len(sorted_dates)):
        prev_close = price_map[sorted_dates[i - 1]]
        curr_close = price_map[sorted_dates[i]]
        if prev_close > 0:
            pct = (curr_close - prev_close) / prev_close * 100
            price_changes[sorted_dates[i]] = round(pct, 2)

    # 3) 공통 날짜에서 타임라인 구성
    all_dates = sorted(set(daily_sentiment.keys()) | set(price_changes.keys()))

    timeline: list[dict] = []
    sentiments_series: list[float] = []
    prices_series: list[float] = []

    for d in all_dates:
        s_score = _calc_sentiment_score(daily_sentiment.get(d, {}))
        p_change = price_changes.get(d)

        sentiments_series.append(s_score)
        prices_series.append(p_change if p_change is not None else 0.0)

        # 7일 롤링 상관계수
        corr_7d = None
        if len(sentiments_series) >= 7:
            window_s = sentiments_series[-7:]
            window_p = prices_series[-7:]
            corr_7d = _pearson_correlation(window_s, window_p)

        entry: dict = {
            "date": d,
            "sentiment_score": round(s_score, 4),
            "price_change_pct": p_change,
            "correlation_7d": round(corr_7d, 4) if corr_7d is not None else None,
        }
        timeline.append(entry)

    # 현재 7일 상관계수
    current_corr = None
    if len(sentiments_series) >= 7:
        current_corr = _pearson_correlation(sentiments_series[-7:], prices_series[-7:])

    return {
        "correlation_7d": round(current_corr, 4) if current_corr is not None else None,
        "timeline": timeline,
    }


def _pearson_correlation(x: list[float], y: list[float]) -> float | None:
    """두 시계열의 피어슨 상관계수를 계산한다. 데이터 부족 시 None 반환."""
    import math

    n = len(x)
    if n < 2 or n != len(y):
        return None

    mean_x = sum(x) / n
    mean_y = sum(y) / n

    numerator = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    denom_x = sum((xi - mean_x) ** 2 for xi in x)
    denom_y = sum((yi - mean_y) ** 2 for yi in y)

    denominator = math.sqrt(denom_x * denom_y)
    if denominator == 0:
        return 0.0

    return numerator / denominator


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
