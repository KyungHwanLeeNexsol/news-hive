from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import SessionLocal, engine, Base
from app.models import Sector, Stock, NewsArticle, NewsStockRelation  # noqa: F401
from app.models.sector_insight import SectorInsight  # noqa: F401
from app.models.disclosure import Disclosure  # noqa: F401
from app.seed.sectors import seed_sectors
from app.seed.stocks import seed_all_stocks
from app.services.scheduler import start_scheduler, stop_scheduler

import logging

logging.basicConfig(level=logging.INFO)


def _run_migrations():
    """Run Alembic migrations on startup."""
    from alembic.config import Config
    from alembic import command
    import os

    alembic_cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    alembic_cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    try:
        command.upgrade(alembic_cfg, "head")
        logging.getLogger(__name__).info("Alembic migrations applied successfully")
    except Exception as e:
        logging.getLogger(__name__).warning(f"Alembic migration failed (may already be applied): {e}")


def _run_seed_and_backfill():
    """Run seed + backfill tasks in a background thread.

    This runs after the app is already serving requests, so cold start
    latency is not affected.
    """
    logger = logging.getLogger(__name__)
    logger.info("Background seed/backfill starting...")
    db = SessionLocal()
    try:
        seed_sectors(db)
        seed_all_stocks(db)
        _backfill_sentiment(db)
        _fix_html_entities(db)
        _backfill_relations(db)
        _reset_bad_scraped_content(db)
    except Exception as e:
        logger.warning(f"Background seed/backfill error: {e}")
    finally:
        db.close()
    logger.info("Background seed/backfill complete")


@asynccontextmanager
async def lifespan(app: FastAPI):
    import threading

    # Startup: run migrations synchronously (fast, required before serving)
    _run_migrations()
    Base.metadata.create_all(bind=engine)

    # Run heavy seed/backfill in background so app starts serving immediately
    seed_thread = threading.Thread(target=_run_seed_and_backfill, daemon=True)
    seed_thread.start()

    # Pre-warm market cap + sector caches so first /stocks request is instant
    def _prewarm_caches():
        import asyncio
        from app.services.naver_finance import fetch_market_cap_rankings, fetch_sector_performances
        try:
            asyncio.run(fetch_market_cap_rankings())
            asyncio.run(fetch_sector_performances(force=True))
        except Exception as e:
            logging.getLogger(__name__).warning(f"Cache pre-warm failed: {e}")

    threading.Thread(target=_prewarm_caches, daemon=True).start()

    start_scheduler()
    yield
    # Shutdown
    stop_scheduler()


def _backfill_sentiment(db):
    """Backfill sentiment for existing articles that don't have it."""
    from app.models.news import NewsArticle
    from app.services.ai_classifier import classify_sentiment

    articles = db.query(NewsArticle).filter(NewsArticle.sentiment.is_(None)).all()
    if not articles:
        return
    for article in articles:
        article.sentiment = classify_sentiment(article.title)
    db.commit()
    logging.getLogger(__name__).info(f"Backfilled sentiment for {len(articles)} articles")


def _fix_html_entities(db):
    """Fix existing articles with raw HTML entities in titles/summaries."""
    import html as html_mod
    from app.models.news import NewsArticle

    # Find articles with common HTML entities
    from sqlalchemy import or_
    articles = db.query(NewsArticle).filter(
        or_(
            NewsArticle.title.contains("&"),
            NewsArticle.summary.contains("&"),
        )
    ).all()

    fixed = 0
    for article in articles:
        new_title = html_mod.unescape(article.title)
        new_summary = html_mod.unescape(article.summary) if article.summary else article.summary
        if new_title != article.title or new_summary != article.summary:
            article.title = new_title
            article.summary = new_summary
            fixed += 1

    if fixed:
        db.commit()
        logging.getLogger(__name__).info(f"Fixed HTML entities in {fixed} articles")


def _backfill_relations(db):
    """Backfill sector/stock relations for articles that have none.

    Uses keyword matching (fast, synchronous) to tag unlinked articles.
    """
    from app.models.news import NewsArticle
    from app.models.news_relation import NewsStockRelation
    from app.models.sector import Sector
    from app.models.stock import Stock
    from app.services.ai_classifier import KeywordIndex, classify_news

    # Find articles with zero relations
    articles_with_rels = db.query(NewsStockRelation.news_id).distinct()
    unlinked = (
        db.query(NewsArticle)
        .filter(NewsArticle.id.notin_(articles_with_rels))
        .all()
    )
    if not unlinked:
        return

    sectors = db.query(Sector).all()
    stocks = db.query(Stock).all()
    index = KeywordIndex.build(sectors, stocks)
    count = 0

    for article in unlinked:
        results = classify_news(article.title, index)
        for cls in results:
            db.add(NewsStockRelation(
                news_id=article.id,
                stock_id=cls.get("stock_id"),
                sector_id=cls.get("sector_id"),
                match_type=cls.get("match_type", "keyword"),
                relevance=cls.get("relevance", "indirect"),
            ))
            count += 1

    if count:
        db.commit()
        logging.getLogger(__name__).info(
            f"Backfilled relations: {count} relations for {len(unlinked)} articles"
        )


def _reset_bad_scraped_content(db):
    """Reset article content that was poorly scraped (contains page-level noise).

    One-time cleanup: clears content for articles where scraping captured
    the entire page instead of just the article body, so they'll be
    re-scraped with the improved scraper on next view.
    """
    from app.models.news import NewsArticle
    from sqlalchemy import func

    # Articles with excessively long content likely captured the whole page
    bad_articles = db.query(NewsArticle).filter(
        NewsArticle.content.isnot(None),
        func.length(NewsArticle.content) > 5000,
    ).all()

    reset = 0
    noise_markers = ["좋아요", "화나요", "슬퍼요", "많이 본 뉴스", "최신 영상", "암호화폐", "BANNER", "뉴스발전소"]
    for article in bad_articles:
        if any(marker in article.content for marker in noise_markers):
            article.content = None
            reset += 1

    if reset:
        db.commit()
        logging.getLogger(__name__).info(f"Reset {reset} poorly scraped articles for re-scraping")


app = FastAPI(title="Stock News Tracker API", lifespan=lifespan)

from app.config import settings as app_settings  # noqa: E402

app.add_middleware(
    CORSMiddleware,
    allow_origins=[app_settings.FRONTEND_URL, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import and register routers
from app.routers import sectors, stocks, news, disclosures  # noqa: E402

app.include_router(sectors.router)
app.include_router(stocks.router)
app.include_router(news.router)
app.include_router(disclosures.router)


@app.api_route("/api/health", methods=["GET", "HEAD"])
async def health():
    return {"status": "ok"}
