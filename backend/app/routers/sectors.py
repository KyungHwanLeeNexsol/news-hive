from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.sector import Sector
from app.models.stock import Stock
from app.models.news import NewsArticle
from app.models.news_relation import NewsStockRelation
from app.schemas.sector import SectorCreate, SectorResponse, SectorDetailResponse
from app.schemas.news import NewsArticleResponse, NewsRelationResponse

router = APIRouter(prefix="/api/sectors", tags=["sectors"])


@router.get("", response_model=list[SectorResponse])
async def list_sectors(db: Session = Depends(get_db)):
    rows = (
        db.query(Sector, func.count(Stock.id).label("stock_count"))
        .outerjoin(Stock, Sector.id == Stock.sector_id)
        .group_by(Sector.id)
        .order_by(Sector.id)
        .all()
    )
    results = []
    for sector, stock_count in rows:
        resp = SectorResponse.model_validate(sector)
        resp.stock_count = stock_count
        results.append(resp)
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
    sector = (
        db.query(Sector)
        .options(joinedload(Sector.stocks))
        .filter(Sector.id == sector_id)
        .first()
    )
    if not sector:
        raise HTTPException(status_code=404, detail="Sector not found")
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

    stock_ids = [s.id for s in db.query(Stock).filter(Stock.sector_id == sector_id).all()]

    relations = (
        db.query(NewsStockRelation)
        .filter(
            (NewsStockRelation.sector_id == sector_id)
            | (NewsStockRelation.stock_id.in_(stock_ids) if stock_ids else False)
        )
        .all()
    )
    news_ids = list({r.news_id for r in relations})
    if not news_ids:
        return []

    articles = (
        db.query(NewsArticle)
        .options(joinedload(NewsArticle.relations))
        .filter(NewsArticle.id.in_(news_ids))
        .order_by(NewsArticle.published_at.desc().nullslast())
        .limit(50)
        .all()
    )

    return _format_articles(articles, db)


def _format_articles(articles: list[NewsArticle], db: Session) -> list[NewsArticleResponse]:
    results = []
    for article in articles:
        relation_responses = []
        for rel in article.relations:
            relation_responses.append(
                NewsRelationResponse(
                    stock_id=rel.stock_id,
                    stock_name=rel.stock.name if rel.stock else None,
                    sector_id=rel.sector_id,
                    sector_name=rel.sector.name if rel.sector else None,
                    match_type=rel.match_type,
                    relevance=rel.relevance,
                )
            )
        results.append(
            NewsArticleResponse(
                id=article.id,
                title=article.title,
                summary=article.summary,
                url=article.url,
                source=article.source,
                published_at=article.published_at,
                collected_at=article.collected_at,
                relations=relation_responses,
            )
        )
    return results
