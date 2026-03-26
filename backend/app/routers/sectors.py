import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.database import get_db
from app.models.sector import Sector
from app.models.stock import Stock
from app.models.news import NewsArticle
from app.models.news_relation import NewsStockRelation
from app.models.sector_insight import SectorInsight
from app.schemas.sector import SectorCreate, SectorResponse, SectorDetailResponse
from app.schemas.news import NewsArticleResponse
from app.routers.utils import format_articles

logger = logging.getLogger(__name__)

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
    from app.services.naver_finance import fetch_sector_stock_performances
    from app.schemas.sector import StockInSector

    sector = db.query(Sector).filter(Sector.id == sector_id).first()
    if not sector:
        raise HTTPException(status_code=404, detail="Sector not found")
    stocks = (
        db.query(Stock)
        .filter(Stock.sector_id == sector_id)
        .order_by(Stock.name)
        .all()
    )

    # Fetch stock-level performance data from Naver
    from app.services.naver_finance import StockPerformance
    stock_perfs: dict[str, StockPerformance] = {}
    if sector.naver_code:
        perfs = await fetch_sector_stock_performances(sector.naver_code)
        stock_perfs = {p.stock_code: p for p in perfs}

    # Count news per stock
    stock_ids = [s.id for s in stocks]
    news_count_map: dict[int, int] = {}
    if stock_ids:
        news_counts_raw = (
            db.query(
                NewsStockRelation.stock_id,
                func.count(func.distinct(NewsStockRelation.news_id)),
            )
            .filter(NewsStockRelation.stock_id.in_(stock_ids))
            .group_by(NewsStockRelation.stock_id)
            .all()
        )
        news_count_map = dict(news_counts_raw)

    # Build enriched stock list
    stock_responses = []
    for stock in stocks:
        perf = stock_perfs.get(stock.stock_code)
        stock_responses.append(StockInSector(
            id=stock.id,
            name=stock.name,
            stock_code=stock.stock_code,
            keywords=stock.keywords,
            current_price=perf.current_price if perf else None,
            price_change=perf.price_change if perf else None,
            change_rate=perf.change_rate if perf else None,
            bid_price=perf.bid_price if perf else None,
            ask_price=perf.ask_price if perf else None,
            volume=perf.volume if perf else None,
            trading_value=perf.trading_value if perf else None,
            prev_volume=perf.prev_volume if perf else None,
            news_count=news_count_map.get(stock.id, 0),
        ))

    return SectorDetailResponse(
        id=sector.id,
        name=sector.name,
        is_custom=sector.is_custom,
        created_at=sector.created_at,
        stocks=stock_responses,
    )


@router.delete("/{sector_id}", status_code=204)
async def delete_sector(sector_id: int, db: Session = Depends(get_db)):
    sector = db.query(Sector).filter(Sector.id == sector_id).first()
    if not sector:
        raise HTTPException(status_code=404, detail="Sector not found")
    if not sector.is_custom:
        raise HTTPException(status_code=400, detail="Cannot delete default sector")
    db.delete(sector)
    db.commit()


@router.get("/{sector_id}/news")
async def get_sector_news(sector_id: int, limit: int = 30, offset: int = 0, db: Session = Depends(get_db)):
    sector = db.query(Sector).filter(Sector.id == sector_id).first()
    if not sector:
        raise HTTPException(status_code=404, detail="Sector not found")

    # Single flat query with JOIN instead of nested subqueries
    news_ids_subq = (
        db.query(NewsStockRelation.news_id)
        .outerjoin(Stock, NewsStockRelation.stock_id == Stock.id)
        .filter(
            (NewsStockRelation.sector_id == sector_id)
            | (Stock.sector_id == sector_id)
        )
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

    data = format_articles(articles)
    return JSONResponse(
        content=jsonable_encoder(data),
        headers={"X-Total-Count": str(total), "Access-Control-Expose-Headers": "X-Total-Count"},
    )


@router.get("/{sector_id}/commodity-news")
async def get_sector_commodity_news(
    sector_id: int,
    limit: int = 30,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """섹터에 연관된 원자재 뉴스 조회.

    SectorCommodityRelation을 통해 해당 섹터와 관련된 원자재를 찾고,
    NewsCommodityRelation을 통해 원자재 관련 뉴스를 반환한다.
    """
    from app.models.commodity import SectorCommodityRelation
    from app.models.news_commodity_relation import NewsCommodityRelation

    sector = db.query(Sector).filter(Sector.id == sector_id).first()
    if not sector:
        raise HTTPException(status_code=404, detail="Sector not found")

    # 섹터와 관련된 원자재 ID 조회
    commodity_ids = [
        r[0] for r in
        db.query(SectorCommodityRelation.commodity_id)
        .filter(SectorCommodityRelation.sector_id == sector_id)
        .all()
    ]
    if not commodity_ids:
        return JSONResponse(
            content=[],
            headers={"X-Total-Count": "0", "Access-Control-Expose-Headers": "X-Total-Count"},
        )

    # 해당 원자재와 관련된 뉴스 ID 조회
    news_ids_subq = (
        db.query(NewsCommodityRelation.news_id)
        .filter(NewsCommodityRelation.commodity_id.in_(commodity_ids))
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

    data = format_articles(articles)
    return JSONResponse(
        content=jsonable_encoder(data),
        headers={"X-Total-Count": str(total), "Access-Control-Expose-Headers": "X-Total-Count"},
    )


@router.post("/{sector_id}/insight")
async def generate_sector_insight(sector_id: int, db: Session = Depends(get_db)):
    """Generate or return cached AI insight for a sector based on recent news."""
    sector = db.query(Sector).filter(Sector.id == sector_id).first()
    if not sector:
        raise HTTPException(status_code=404, detail="Sector not found")

    # Check for cached insight (24h TTL)
    cache_cutoff = datetime.utcnow() - timedelta(hours=24)
    cached = (
        db.query(SectorInsight)
        .filter(
            SectorInsight.sector_id == sector_id,
            SectorInsight.created_at >= cache_cutoff,
        )
        .order_by(SectorInsight.created_at.desc())
        .first()
    )
    if cached:
        return {"content": cached.content, "created_at": str(cached.created_at), "cached": True}

    # Collect recent news titles for this sector
    stock_ids = [s.id for s in db.query(Stock).filter(Stock.sector_id == sector_id).all()]
    since = datetime.utcnow() - timedelta(days=7)

    news_ids_subq = (
        db.query(NewsStockRelation.news_id)
        .outerjoin(Stock, NewsStockRelation.stock_id == Stock.id)
        .filter(
            (NewsStockRelation.sector_id == sector_id)
            | (Stock.sector_id == sector_id)
        )
        .distinct()
        .subquery()
    )

    articles = (
        db.query(NewsArticle)
        .filter(
            NewsArticle.id.in_(news_ids_subq.select()),
            NewsArticle.published_at >= since,
        )
        .order_by(NewsArticle.published_at.desc())
        .limit(50)
        .all()
    )

    if not articles:
        return {"content": "최근 7일간 관련 뉴스가 없어 인사이트를 생성할 수 없습니다.", "cached": False}

    # Build prompt
    news_list = "\n".join(
        f"- [{a.sentiment or '중립'}] {a.title}" for a in articles
    )

    prompt = f"""다음은 "{sector.name}" 업종의 최근 7일간 뉴스 제목 목록입니다.

{news_list}

이 업종의 최근 동향을 투자자 관점에서 3-5줄로 요약해주세요.
다음 내용을 포함해주세요:
1. 업종의 전반적인 분위기 (호재/악재 비율)
2. 주요 이슈나 트렌드
3. 투자자가 주목해야 할 포인트

한국어로, 마크다운 없이 일반 텍스트로 작성해주세요."""

    try:
        from app.services.ai_client import ask_ai

        content = await ask_ai(prompt)
        if not content:
            return {"content": "인사이트 생성에 실패했습니다. AI API 키를 확인하세요.", "cached": False}

        # Cache to DB
        insight = SectorInsight(sector_id=sector_id, content=content)
        db.add(insight)
        db.commit()

        return {"content": content, "created_at": str(insight.created_at), "cached": False}

    except Exception as e:
        logger.error(f"Failed to generate sector insight: {e}")
        return {"content": "인사이트 생성 중 오류가 발생했습니다.", "cached": False}
