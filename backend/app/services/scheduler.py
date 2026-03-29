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

        # Detect macro risks after crawling (async — REQ-AI-010 NLP 분류)
        from app.services.macro_risk import detect_macro_risks, deactivate_old_alerts
        try:
            alerts = asyncio.run(detect_macro_risks(db))
            if alerts:
                logger.info(f"Created {len(alerts)} macro risk alerts")
            deactivate_old_alerts(db)
        except Exception as e:
            logger.error(f"Macro risk detection failed: {e}")

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
    """Fetch market cap from Naver Mobile API and update DB stocks."""
    from app.models.stock import Stock
    from app.services.naver_finance import fetch_naver_stock_list

    db = SessionLocal()
    try:
        cap_map: dict[str, int] = {}

        # Fetch multiple pages from both markets (50 per page)
        for mkt in ["KOSPI", "KOSDAQ"]:
            for page in range(1, 11):  # 10 pages × 50 = top 500 per market
                items, _total = asyncio.run(fetch_naver_stock_list(market=mkt, page=page, page_size=50))
                if not items:
                    break
                for item in items:
                    if item.market_cap:
                        cap_map[item.stock_code] = item.market_cap

        if not cap_map:
            logger.warning("No market cap data fetched")
            return

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
        logger.info(f"Updated market_cap for {updated}/{len(stocks)} stocks (from {len(cap_map)} rankings)")
    except Exception as e:
        logger.error(f"Market cap update failed: {e}")
    finally:
        db.close()


def _run_daily_briefing():
    """매일 오전 데일리 브리핑 자동 생성."""
    from app.services.fund_manager import generate_daily_briefing

    db = SessionLocal()
    try:
        briefing = asyncio.run(generate_daily_briefing(db))
        if briefing:
            logger.info(f"Daily briefing auto-generated for {briefing.briefing_date}")
    except Exception as e:
        logger.error(f"Daily briefing generation failed: {e}")
    finally:
        db.close()


def _run_signal_verification():
    """과거 시그널의 적중 여부를 검증한다."""
    from app.services.signal_verifier import verify_signals

    db = SessionLocal()
    try:
        stats = asyncio.run(verify_signals(db))
        if stats["verified"] or stats["updated"]:
            logger.info(f"Signal verification: {stats['verified']} verified, {stats['updated']} updated")
    except Exception as e:
        logger.error(f"Signal verification failed: {e}")
    finally:
        db.close()


def _run_news_impact_backfill():
    """뉴스-가격 반응 1일/5일 backfill (REQ-NPI-006~009)."""
    from app.services.news_price_impact_service import backfill_prices

    db = SessionLocal()
    try:
        stats = asyncio.run(backfill_prices(db))
        if stats["updated_1d"] or stats["updated_5d"]:
            logger.info(f"News impact backfill: 1d={stats['updated_1d']}, 5d={stats['updated_5d']}")
    except Exception as e:
        logger.error(f"News impact backfill failed: {e}")
    finally:
        db.close()


def _run_fast_verify():
    """장중 빠른 검증 실행 (1시간 간격)."""
    from app.services.signal_verifier import fast_verify

    db = SessionLocal()
    try:
        stats = asyncio.run(fast_verify(db))
        if stats["checked"]:
            logger.info(f"Fast verify: {stats['checked']} checked, {stats['early_warnings']} warnings")
    except Exception as e:
        logger.error(f"Fast verify failed: {e}")
    finally:
        db.close()


def _run_commodity_price_fetch():
    """원자재 가격 수집 + 급변 알림 생성."""
    from app.services.commodity_service import fetch_commodity_prices, check_commodity_alerts

    db = SessionLocal()
    try:
        updated = fetch_commodity_prices(db)
        if updated:
            alerts = check_commodity_alerts(db)
            if alerts:
                logger.info(f"원자재 급변 알림: {len(alerts)}개 생성")
    except Exception as e:
        logger.error(f"원자재 가격 수집 실패: {e}")
    finally:
        db.close()


def _run_commodity_news_crawl():
    """원자재 뉴스 크롤링 (기존 크롤러 재사용)."""
    from app.services.commodity_news_service import crawl_commodity_news

    db = SessionLocal()
    try:
        count = asyncio.run(crawl_commodity_news(db))
        if count:
            logger.info(f"원자재 뉴스 크롤링 완료: {count}개 기사")
    except Exception as e:
        logger.error(f"원자재 뉴스 크롤링 실패: {e}")
    finally:
        db.close()


def _run_news_impact_cleanup():
    """90일 초과 뉴스-가격 반응 레코드 정리 (REQ-NPI-016)."""
    from app.services.news_price_impact_service import cleanup_old_impacts

    db = SessionLocal()
    try:
        deleted = asyncio.run(cleanup_old_impacts(db))
        if deleted:
            logger.info(f"News impact cleanup: {deleted} records deleted")
    except Exception as e:
        logger.error(f"News impact cleanup failed: {e}")
    finally:
        db.close()


def _run_relation_inference():
    """주간 종목/섹터 관계 증분 추론."""
    from app.services.stock_relation_service import run_incremental_inference

    db = SessionLocal()
    try:
        stats = asyncio.run(run_incremental_inference(db))
        if stats["inter_sector"] or stats["intra_sector"]:
            logger.info(
                f"주간 관계 추론 완료: 섹터 간 {stats['inter_sector']}건, "
                f"섹터 내 {stats['intra_sector']}건"
            )
    except Exception as e:
        logger.error(f"주간 관계 추론 실패: {e}")
    finally:
        db.close()


def _run_exit_check():
    """장중 청산 조건 확인 (1시간 간격)."""
    from app.services.paper_trading import check_exit_conditions

    db = SessionLocal()
    try:
        stats = asyncio.run(check_exit_conditions(db))
        if stats["closed"]:
            logger.info(f"Paper trading exit check: {stats['closed']} closed ({stats['reasons']})")
    except Exception as e:
        logger.error(f"Paper trading exit check failed: {e}")
    finally:
        db.close()


def _run_sector_momentum():
    """섹터 모멘텀 일간 데이터 수집 + 분석 (매일 16:30 KST)."""
    from app.services.sector_momentum import (
        record_daily_sector_performance,
        detect_momentum_sectors,
        detect_capital_inflow,
        detect_sector_rotation,
    )

    db = SessionLocal()
    try:
        # 1) 당일 섹터 등락률 기록
        count = asyncio.run(record_daily_sector_performance(db))
        if count:
            logger.info(f"섹터 모멘텀 일간 데이터 {count}건 기록")

        # 2) 모멘텀 섹터 감지
        momentum = detect_momentum_sectors(db)
        if momentum:
            logger.info(f"모멘텀 섹터 {len(momentum)}개 감지")

        # 3) 자금 유입 감지
        inflow = detect_capital_inflow(db)
        if inflow:
            logger.info(f"자금 유입 섹터 {len(inflow)}개 감지")

        # 4) 섹터 로테이션 감지
        rotations = detect_sector_rotation(db)
        if rotations:
            logger.info(f"섹터 로테이션 {len(rotations)}건 감지")
    except Exception as e:
        logger.error(f"섹터 모멘텀 분석 실패: {e}")
    finally:
        db.close()


def _run_portfolio_snapshot():
    """일말 포트폴리오 스냅샷 (매일 16:00 KST)."""
    from app.services.paper_trading import take_daily_snapshot

    db = SessionLocal()
    try:
        asyncio.run(take_daily_snapshot(db))
    except Exception as e:
        logger.error(f"Portfolio snapshot failed: {e}")
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
    # AI daily briefing every day at 08:30 KST
    scheduler.add_job(
        _run_daily_briefing,
        "cron",
        hour=8,
        minute=30,
        timezone="Asia/Seoul",
        id="daily_briefing",
        replace_existing=True,
    )
    # 시그널 적중률 검증: 매일 18:00 KST (장 마감 후)
    scheduler.add_job(
        _run_signal_verification,
        "cron",
        hour=18,
        minute=0,
        timezone="Asia/Seoul",
        id="signal_verification",
        replace_existing=True,
    )
    # 뉴스-가격 반응 backfill: 매일 18:30 KST (시그널 검증 이후)
    scheduler.add_job(
        _run_news_impact_backfill,
        "cron",
        hour=18,
        minute=30,
        timezone="Asia/Seoul",
        id="news_impact_backfill",
        replace_existing=True,
    )
    # 원자재 가격 수집: 10분 간격
    scheduler.add_job(
        _run_commodity_price_fetch,
        "interval",
        minutes=10,
        id="commodity_price_fetch",
        replace_existing=True,
        next_run_time=datetime.now(),
    )
    # 원자재 뉴스 크롤링: 30분 간격 (뉴스 크롤링 직후)
    scheduler.add_job(
        _run_commodity_news_crawl,
        "interval",
        minutes=30,
        id="commodity_news_crawl",
        replace_existing=True,
    )
    # 뉴스-가격 반응 레코드 정리: 매일 03:00 KST
    scheduler.add_job(
        _run_news_impact_cleanup,
        "cron",
        hour=3,
        minute=0,
        timezone="Asia/Seoul",
        id="news_impact_cleanup",
        replace_existing=True,
    )
    # REQ-AI-005: 장중 빠른 검증 (1시간 간격)
    scheduler.add_job(
        _run_fast_verify,
        "interval",
        hours=1,
        id="fast_verify",
        replace_existing=True,
    )
    # 종목/섹터 관계 증분 추론: 매주 일요일 04:00 KST
    scheduler.add_job(
        _run_relation_inference,
        "cron",
        day_of_week="sun",
        hour=4,
        minute=0,
        timezone="Asia/Seoul",
        id="relation_inference",
        replace_existing=True,
    )
    # REQ-AI-013: 페이퍼 트레이딩 청산 체크 (장중 1시간 간격)
    scheduler.add_job(
        _run_exit_check,
        "interval",
        hours=1,
        id="paper_exit_check",
        replace_existing=True,
    )
    # REQ-AI-013: 포트폴리오 일일 스냅샷 (매일 16:00 KST = UTC 07:00)
    scheduler.add_job(
        _run_portfolio_snapshot,
        "cron",
        hour=7,
        minute=0,
        id="portfolio_snapshot",
        replace_existing=True,
    )
    # REQ-AI-016: 섹터 모멘텀 일간 수집 + 분석 (매일 16:30 KST)
    scheduler.add_job(
        _run_sector_momentum,
        "cron",
        hour=16,
        minute=30,
        timezone="Asia/Seoul",
        id="sector_momentum",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        f"Scheduler started: crawling every {interval} min, DART every 30 min, "
        f"market cap every 6h, commodity price every 10 min, commodity news every 30 min, "
        f"briefing at 08:30 KST, signal verify at 18:00 KST, "
        f"impact backfill at 18:30 KST, impact cleanup at 03:00 KST, "
        f"relation inference every Sunday 04:00 KST, "
        f"fast verify every 1h, paper exit check every 1h, "
        f"portfolio snapshot at 16:00 KST, "
        f"sector momentum at 16:30 KST"
    )


def stop_scheduler():
    """Stop the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
