import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
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


@router.get("/{news_id}", response_model=NewsArticleResponse)
async def get_news_detail(news_id: int, db: Session = Depends(get_db)):
    article = (
        db.query(NewsArticle)
        .options(
            subqueryload(NewsArticle.relations).subqueryload(NewsStockRelation.stock),
            subqueryload(NewsArticle.relations).subqueryload(NewsStockRelation.sector),
        )
        .filter(NewsArticle.id == news_id)
        .first()
    )
    if not article:
        raise HTTPException(status_code=404, detail="News article not found")
    return format_articles([article])[0]


@router.post("/refresh")
async def refresh_news(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    # Quick synchronous reclassify (keyword-only, instant)
    reclassified = await _reclassify_unlinked(db)

    # Backfill sentiment for articles that don't have it yet
    _backfill_sentiment(db)

    # Launch crawl in background so the HTTP response returns immediately
    background_tasks.add_task(_run_crawl_background)

    total = db.query(NewsArticle).count()
    return {
        "message": f"Reclassified {reclassified}. Crawl started in background.",
        "reclassified": reclassified,
        "total": total,
    }


@router.post("/{news_id}/summary", response_model=NewsArticleResponse)
async def generate_summary(news_id: int, db: Session = Depends(get_db)):
    """Generate AI summary for a news article (lazy, cached in DB)."""
    article = (
        db.query(NewsArticle)
        .options(
            subqueryload(NewsArticle.relations).subqueryload(NewsStockRelation.stock),
            subqueryload(NewsArticle.relations).subqueryload(NewsStockRelation.sector),
        )
        .filter(NewsArticle.id == news_id)
        .first()
    )
    if not article:
        raise HTTPException(status_code=404, detail="News article not found")

    if not article.ai_summary:
        from app.services.ai_classifier import generate_ai_summary

        relations_context = []
        for rel in article.relations:
            relations_context.append({
                "stock_name": rel.stock.name if rel.stock else None,
                "sector_name": rel.sector.name if rel.sector else None,
                "relevance": rel.relevance,
            })

        ai_summary = await generate_ai_summary(
            title=article.title,
            description=article.summary,
            relations=relations_context,
        )

        if ai_summary:
            article.ai_summary = ai_summary
            db.commit()
            db.refresh(article)

    return format_articles([article])[0]


@router.post("/{news_id}/content", response_model=NewsArticleResponse)
async def scrape_content(news_id: int, db: Session = Depends(get_db)):
    """Scrape article content on demand (lazy, cached in DB)."""
    article = (
        db.query(NewsArticle)
        .options(
            subqueryload(NewsArticle.relations).subqueryload(NewsStockRelation.stock),
            subqueryload(NewsArticle.relations).subqueryload(NewsStockRelation.sector),
        )
        .filter(NewsArticle.id == news_id)
        .first()
    )
    if not article:
        raise HTTPException(status_code=404, detail="News article not found")

    if not article.content:
        from app.services.article_scraper import scrape_article_content

        content = await scrape_article_content(article.url)
        if content:
            article.content = content
            db.commit()
            db.refresh(article)

    return format_articles([article])[0]


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


def _backfill_sentiment(db: Session) -> None:
    """Backfill sentiment for existing articles that don't have it."""
    from app.services.ai_classifier import classify_sentiment

    articles = db.query(NewsArticle).filter(NewsArticle.sentiment.is_(None)).all()
    if not articles:
        return

    for article in articles:
        article.sentiment = classify_sentiment(article.title)

    db.commit()
    logger.info(f"Backfilled sentiment for {len(articles)} articles")


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
