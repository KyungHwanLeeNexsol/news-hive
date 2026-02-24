import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.news import NewsArticle
from app.schemas.news import NewsArticleResponse, NewsRelationResponse

logger = logging.getLogger(__name__)

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

    try:
        # Reclassify existing articles that have no relations
        reclassified = await _reclassify_unlinked(db)

        count = await crawl_all_news(db)
        total = db.query(NewsArticle).count()
        return {
            "message": f"Collected {count} new articles, reclassified {reclassified}",
            "new": count,
            "reclassified": reclassified,
            "total": total,
        }
    except Exception as e:
        import traceback
        return {"message": f"Crawl failed: {e}", "error": traceback.format_exc()}


async def _reclassify_unlinked(db: Session) -> int:
    """Reclassify articles that have no news_stock_relations."""
    from app.models.news_relation import NewsStockRelation
    from app.models.sector import Sector
    from app.models.stock import Stock
    from app.services.ai_classifier import classify_news

    # Find articles with no relations
    articles_with_rels = db.query(NewsStockRelation.news_id).distinct()
    unlinked = (
        db.query(NewsArticle)
        .filter(NewsArticle.id.notin_(articles_with_rels))
        .all()
    )
    if not unlinked:
        return 0

    logger.info(f"Reclassifying {len(unlinked)} unlinked articles")

    sectors = db.query(Sector).all()
    stocks = db.query(Stock).all()
    count = 0

    for article in unlinked:
        try:
            classifications = await classify_news(article.title, sectors, stocks)
            for cls in classifications:
                db.add(NewsStockRelation(
                    news_id=article.id,
                    stock_id=cls.get("stock_id"),
                    sector_id=cls.get("sector_id"),
                    match_type=cls.get("match_type", "ai_classified"),
                    relevance=cls.get("relevance", "indirect"),
                ))
                count += 1
        except Exception as e:
            logger.warning(f"Reclassify failed for article {article.id}: {e}")

    if count > 0:
        db.commit()
    logger.info(f"Reclassified: added {count} relations")
    return count
