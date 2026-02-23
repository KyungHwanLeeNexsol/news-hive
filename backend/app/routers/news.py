from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.news import NewsArticle
from app.schemas.news import NewsArticleResponse, NewsRelationResponse

router = APIRouter(prefix="/api/news", tags=["news"])


@router.get("", response_model=list[NewsArticleResponse])
async def list_news(limit: int = 50, db: Session = Depends(get_db)):
    articles = (
        db.query(NewsArticle)
        .options(joinedload(NewsArticle.relations))
        .order_by(NewsArticle.published_at.desc().nullslast())
        .limit(limit)
        .all()
    )

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


@router.post("/refresh")
async def refresh_news(db: Session = Depends(get_db)):
    from app.services.news_crawler import crawl_all_news

    count = await crawl_all_news(db)
    return {"message": f"Collected {count} new articles"}
