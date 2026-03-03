import asyncio
import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.database import SessionLocal

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def _run_crawl_job():
    """Sync wrapper that runs the async crawl job.

    BackgroundScheduler runs jobs in a separate thread pool, so asyncio.run()
    safely creates a new event loop without conflicting with uvloop on the main thread.
    """
    from app.services.news_crawler import crawl_all_news
    from app.services.ai_classifier import classify_sentiment
    from app.models.news import NewsArticle

    db = SessionLocal()
    try:
        # Delete articles older than 7 days
        _cleanup_old_articles(db)

        count = asyncio.run(crawl_all_news(db))
        logger.info(f"Scheduled crawl completed: {count} new articles")

        # Backfill sentiment for any articles missing it
        articles = db.query(NewsArticle).filter(NewsArticle.sentiment.is_(None)).all()
        if articles:
            for article in articles:
                article.sentiment = classify_sentiment(article.title)
            db.commit()
            logger.info(f"Backfilled sentiment for {len(articles)} articles")
    except Exception as e:
        logger.error(f"Scheduled crawl failed: {e}")
    finally:
        db.close()


def _cleanup_old_articles(db):
    """Delete news articles older than 7 days."""
    from datetime import datetime, timedelta, timezone
    from app.models.news import NewsArticle
    from app.models.news_relation import NewsStockRelation

    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    # Find old article IDs
    old_ids = [
        row[0] for row in
        db.query(NewsArticle.id)
        .filter(NewsArticle.published_at < cutoff)
        .all()
    ]
    if not old_ids:
        return

    # Delete relations first, then articles
    db.query(NewsStockRelation).filter(
        NewsStockRelation.news_id.in_(old_ids)
    ).delete(synchronize_session=False)
    db.query(NewsArticle).filter(
        NewsArticle.id.in_(old_ids)
    ).delete(synchronize_session=False)
    db.commit()
    logger.info(f"Cleaned up {len(old_ids)} articles older than 7 days")


def _cleanup_old_disclosures(db):
    """Delete disclosures older than 7 days based on rcept_dt (YYYYMMDD string)."""
    from datetime import datetime, timedelta
    from app.models.disclosure import Disclosure

    cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
    deleted = db.query(Disclosure).filter(Disclosure.rcept_dt < cutoff).delete(synchronize_session=False)
    if deleted:
        db.commit()
        logger.info(f"Cleaned up {deleted} disclosures older than 7 days")


def _run_dart_crawl():
    """Sync wrapper that runs the async DART disclosure crawl."""
    from app.services.dart_crawler import fetch_dart_disclosures, backfill_disclosure_stock_ids, backfill_disclosure_report_types

    if not settings.DART_API_KEY:
        return

    db = SessionLocal()
    try:
        _cleanup_old_disclosures(db)
        count = asyncio.run(fetch_dart_disclosures(db))
        logger.info(f"DART crawl completed: {count} new disclosures")
        # Re-link any previously unlinked disclosures
        backfill_disclosure_stock_ids(db)
        backfill_disclosure_report_types(db)
    except Exception as e:
        logger.error(f"DART crawl failed: {e}")
    finally:
        db.close()


def _refresh_sector_performance():
    """Sync wrapper that refreshes Naver sector performance cache."""
    from app.services.naver_finance import fetch_sector_performances

    try:
        data = asyncio.run(fetch_sector_performances(force=True))
        logger.info(f"Sector performance refreshed: {len(data)} sectors")
    except Exception as e:
        logger.error(f"Sector performance refresh failed: {e}")


def _refresh_market_cap():
    """Pre-warm market cap ranking cache so /stocks responds instantly."""
    from app.services.naver_finance import fetch_market_cap_rankings

    try:
        data = asyncio.run(fetch_market_cap_rankings())
        logger.info(f"Market cap cache refreshed: {len(data)} stocks")
    except Exception as e:
        logger.error(f"Market cap refresh failed: {e}")


def start_scheduler():
    """Start the background news crawl scheduler."""
    interval = settings.NEWS_CRAWL_INTERVAL_MINUTES
    scheduler.add_job(
        _run_crawl_job,
        "interval",
        minutes=interval,
        id="news_crawl",
        replace_existing=True,
    )
    # Refresh Naver sector performance data every 5 minutes
    scheduler.add_job(
        _refresh_sector_performance,
        "interval",
        minutes=5,
        id="sector_perf_refresh",
        replace_existing=True,
    )
    # Pre-warm market cap cache every 5 minutes
    scheduler.add_job(
        _refresh_market_cap,
        "interval",
        minutes=5,
        id="market_cap_refresh",
        replace_existing=True,
    )
    # DART disclosure crawl every 30 minutes
    scheduler.add_job(
        _run_dart_crawl,
        "interval",
        minutes=30,
        id="dart_crawl",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"Scheduler started: crawling every {interval} min, sector/market-cap every 5 min, DART every 30 min")


def stop_scheduler():
    """Stop the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
