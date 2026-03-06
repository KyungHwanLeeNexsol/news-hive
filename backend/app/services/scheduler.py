import asyncio
import logging
from datetime import datetime

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
    from sqlalchemy import or_
    from app.models.news import NewsArticle
    from app.models.news_relation import NewsStockRelation

    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    # Find old article IDs (including those with NULL published_at)
    old_ids = [
        row[0] for row in
        db.query(NewsArticle.id)
        .filter(or_(NewsArticle.published_at < cutoff, NewsArticle.published_at.is_(None)))
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



def _update_market_caps():
    """Fetch market cap rankings from Naver and update DB stocks."""
    from app.models.stock import Stock
    from app.services.naver_finance import fetch_market_cap_rankings

    db = SessionLocal()
    try:
        rankings = asyncio.run(fetch_market_cap_rankings(max_pages_per_market=6))
        if not rankings:
            logger.warning("No market cap data fetched")
            return

        # Build code -> market_cap mapping
        cap_map = {r.stock_code: r.market_cap for r in rankings if r.market_cap}

        # Batch update
        updated = 0
        stocks = db.query(Stock).filter(Stock.stock_code.in_(list(cap_map.keys()))).all()
        for stock in stocks:
            new_cap = cap_map.get(stock.stock_code)
            if new_cap and stock.market_cap != new_cap:
                stock.market_cap = new_cap
                updated += 1
        if updated:
            db.commit()
        logger.info(f"Updated market_cap for {updated}/{len(stocks)} stocks (from {len(rankings)} rankings)")
    except Exception as e:
        logger.error(f"Market cap update failed: {e}")
    finally:
        db.close()


def start_scheduler():
    """Start the background news crawl scheduler."""
    interval = settings.NEWS_CRAWL_INTERVAL_MINUTES
    scheduler.add_job(
        _run_crawl_job,
        "interval",
        minutes=interval,
        id="news_crawl",
        replace_existing=True,
        next_run_time=datetime.now(),
    )
    # DART disclosure crawl every 30 minutes (run immediately on startup too)
    scheduler.add_job(
        _run_dart_crawl,
        "interval",
        minutes=30,
        id="dart_crawl",
        replace_existing=True,
        next_run_time=datetime.now(),
    )
    # Market cap update every 6 hours (for stock list sorting order)
    scheduler.add_job(
        _update_market_caps,
        "interval",
        hours=6,
        id="market_cap_update",
        replace_existing=True,
        next_run_time=datetime.now(),
    )
    scheduler.start()
    logger.info(f"Scheduler started: crawling every {interval} min, DART every 30 min, market cap every 6h")


def stop_scheduler():
    """Stop the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
