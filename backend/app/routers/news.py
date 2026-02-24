import logging

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session, subqueryload

from app.database import get_db, SessionLocal
from app.models.news import NewsArticle
from app.models.news_relation import NewsStockRelation
from app.schemas.news import NewsArticleResponse
from app.routers.utils import format_articles


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/news", tags=["news"])


@router.get("", response_model=list[NewsArticleResponse])
async def list_news(limit: int = 50, db: Session = Depends(get_db)):
    articles = (
        db.query(NewsArticle)
        .options(
            subqueryload(NewsArticle.relations).subqueryload(NewsStockRelation.stock),
            subqueryload(NewsArticle.relations).subqueryload(NewsStockRelation.sector),
        )
        .order_by(NewsArticle.published_at.desc().nullslast())
        .limit(limit)
        .all()
    )
    return format_articles(articles)


@router.post("/refresh")
async def refresh_news(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    # Quick synchronous reclassify (keyword-only, instant)
    reclassified = await _reclassify_unlinked(db)

    # Launch crawl in background so the HTTP response returns immediately
    background_tasks.add_task(_run_crawl_background)

    total = db.query(NewsArticle).count()
    return {
        "message": f"Reclassified {reclassified}. Crawl started in background.",
        "reclassified": reclassified,
        "total": total,
    }


async def _run_crawl_background():
    """Run the crawl in background with a dedicated DB session."""
    from app.services.news_crawler import crawl_all_news

    db = SessionLocal()
    try:
        count = await crawl_all_news(db)
        logger.info(f"Background crawl completed: {count} new articles")
    except Exception as e:
        logger.error(f"Background crawl failed: {e}")
    finally:
        db.close()


async def _reclassify_unlinked(db: Session) -> int:
    """Reclassify articles that have no news_stock_relations.

    Uses keyword matching only (no AI API calls) for speed.
    """
    from app.models.sector import Sector
    from app.models.stock import Stock
    from app.services.ai_classifier import _keyword_fallback

    # Find articles with no relations
    articles_with_rels = db.query(NewsStockRelation.news_id).distinct()
    unlinked = (
        db.query(NewsArticle)
        .filter(NewsArticle.id.notin_(articles_with_rels))
        .all()
    )
    if not unlinked:
        return 0

    logger.info(f"Reclassifying {len(unlinked)} unlinked articles (keyword-only)")

    sectors = db.query(Sector).all()
    stocks = db.query(Stock).all()
    count = 0

    for article in unlinked:
        try:
            classifications = _keyword_fallback(article.title, sectors, stocks)
            for cls in classifications:
                db.add(NewsStockRelation(
                    news_id=article.id,
                    stock_id=cls.get("stock_id"),
                    sector_id=cls.get("sector_id"),
                    match_type=cls.get("match_type", "keyword"),
                    relevance=cls.get("relevance", "indirect"),
                ))
                count += 1
        except Exception as e:
            logger.warning(f"Reclassify failed for article {article.id}: {e}")

    if count > 0:
        db.commit()
    logger.info(f"Reclassified: added {count} relations")
    return count
