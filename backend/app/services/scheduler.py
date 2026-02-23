import asyncio
import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.database import SessionLocal

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def _run_crawl_job():
    """Sync wrapper that runs the async crawl job."""
    from app.services.news_crawler import crawl_all_news

    db = SessionLocal()
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        count = loop.run_until_complete(crawl_all_news(db))
        logger.info(f"Scheduled crawl completed: {count} new articles")
    except Exception as e:
        logger.error(f"Scheduled crawl failed: {e}")
    finally:
        db.close()
        loop.close()


def _refresh_sector_performance():
    """Sync wrapper that refreshes Naver sector performance cache."""
    from app.services.naver_finance import fetch_sector_performances

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        data = loop.run_until_complete(fetch_sector_performances(force=True))
        logger.info(f"Sector performance refreshed: {len(data)} sectors")
    except Exception as e:
        logger.error(f"Sector performance refresh failed: {e}")
    finally:
        loop.close()


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
    scheduler.start()
    logger.info(f"Scheduler started: crawling every {interval} min, sector perf every 5 min")


def stop_scheduler():
    """Stop the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
