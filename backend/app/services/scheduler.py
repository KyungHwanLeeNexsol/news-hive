import asyncio
import logging
import threading
import time as _time
from datetime import datetime

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.database import SessionLocal
from app.services.job_retry import retry_with_backoff

logger = logging.getLogger(__name__)

# 뉴스/공시/리포트 크롤 완료 후 각각 호출되는 keyword matching 동시 실행 방지
_keyword_matching_lock = threading.Lock()


def _record_job_duration(job_id: str, duration: float) -> None:
    """Prometheus JOB_DURATION 메트릭 기록 (임포트 실패 시 무시)."""
    try:
        from app.metrics import JOB_DURATION
        JOB_DURATION.labels(job_id=job_id).observe(duration)
    except Exception:
        pass

scheduler = BackgroundScheduler(
    jobstores={"default": SQLAlchemyJobStore(url=settings.DATABASE_URL)},
    job_defaults={"misfire_grace_time": 30},
)


@retry_with_backoff(max_attempts=3)
def _run_crawl_job():
    """Sync wrapper that runs the async crawl job.

    BackgroundScheduler runs jobs in a separate thread pool, so asyncio.run()
    safely creates a new event loop without conflicting with uvloop on the main thread.
    """
    _start = _time.monotonic()
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
        raise
    finally:
        _record_job_duration("news_crawl", _time.monotonic() - _start)
        db.close()

    # 뉴스 크롤링 후 키워드 매칭 실행 (SPEC-FOLLOW-001)
    _run_keyword_matching()


def _cleanup_old_articles(db):
    """Delete news articles older than 7 days."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import func
    from app.models.news import NewsArticle
    from app.models.news_relation import NewsStockRelation

    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    # Keep freshly collected articles even when published_at is missing.
    # Otherwise the same URL can be re-crawled and re-notified on the next cycle.
    old_ids = [
        row[0] for row in
        db.query(NewsArticle.id)
        .filter(func.coalesce(NewsArticle.published_at, NewsArticle.collected_at) < cutoff)
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


@retry_with_backoff(max_attempts=3)
def _run_dart_crawl():
    """Sync wrapper that runs the async DART disclosure crawl."""
    _start = _time.monotonic()
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
        raise
    finally:
        _record_job_duration("dart_crawl", _time.monotonic() - _start)
        db.close()

    # DART 공시 크롤링 후 키워드 매칭 실행 (SPEC-FOLLOW-001)
    _run_keyword_matching()



@retry_with_backoff(max_attempts=3)
def _run_securities_report_crawl():
    """증권사 리포트 크롤링 동기 래퍼 (SPEC-FOLLOW-002)."""
    _start = _time.monotonic()
    from app.services.securities_report_crawler import fetch_securities_reports, backfill_report_content

    db = SessionLocal()
    try:
        count = asyncio.run(fetch_securities_reports(db))
        logger.info(f"Securities report crawl completed: {count} new reports")
        # 본문이 없는 기존 리포트 백필 (content 없는 것 순서대로 최대 50건씩)
        backfill_count = asyncio.run(backfill_report_content(db, batch_size=50))
        if backfill_count > 0:
            logger.info(f"Securities report content backfill: {backfill_count} reports updated")
    except Exception as e:
        logger.error(f"Securities report crawl failed: {e}")
        raise
    finally:
        _record_job_duration("securities_report_crawl", _time.monotonic() - _start)
        db.close()

    # 증권사 리포트 크롤링 후 키워드 매칭 실행 (SPEC-FOLLOW-002)
    _run_keyword_matching()


@retry_with_backoff(max_attempts=3)
def _update_market_caps():
    """Fetch market cap from Naver Mobile API and update DB stocks."""
    _start = _time.monotonic()
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
        raise
    finally:
        _record_job_duration("market_cap_update", _time.monotonic() - _start)
        db.close()



@retry_with_backoff(max_attempts=3)
def _run_signal_verification():
    """과거 시그널의 적중 여부를 검증한다."""
    _start = _time.monotonic()
    from app.services.signal_verifier import verify_signals

    db = SessionLocal()
    try:
        stats = asyncio.run(verify_signals(db))
        if stats["verified"] or stats["updated"]:
            logger.info(f"Signal verification: {stats['verified']} verified, {stats['updated']} updated")
    except Exception as e:
        logger.error(f"Signal verification failed: {e}")
        raise
    finally:
        _record_job_duration("signal_verification", _time.monotonic() - _start)
        db.close()


@retry_with_backoff(max_attempts=3)
def _run_daily_briefing():
    """데일리 브리핑 생성 및 매수/매도 시그널 발행 (평일 08:30 KST)."""
    if not _is_kr_market_open():
        logger.debug("주말 — 데일리 브리핑 스킵")
        return

    _start = _time.monotonic()
    from app.services.fund_manager import generate_daily_briefing

    db = SessionLocal()
    try:
        briefing = asyncio.run(generate_daily_briefing(db))
        if briefing:
            logger.info(f"Daily briefing generated: {briefing.id} ({briefing.market_sentiment})")
        else:
            logger.warning("Daily briefing generation returned None")
    except Exception as e:
        logger.error(f"Daily briefing generation failed: {e}")
        raise
    finally:
        _record_job_duration("daily_briefing", _time.monotonic() - _start)
        db.close()


@retry_with_backoff(max_attempts=3)
def _run_news_impact_backfill():
    """뉴스-가격 반응 1일/5일 backfill (REQ-NPI-006~009)."""
    _start = _time.monotonic()
    from app.services.news_price_impact_service import backfill_prices

    db = SessionLocal()
    try:
        stats = asyncio.run(backfill_prices(db))
        if stats["updated_1d"] or stats["updated_5d"]:
            logger.info(f"News impact backfill: 1d={stats['updated_1d']}, 5d={stats['updated_5d']}")
    except Exception as e:
        logger.error(f"News impact backfill failed: {e}")
        raise
    finally:
        _record_job_duration("news_impact_backfill", _time.monotonic() - _start)
        db.close()


@retry_with_backoff(max_attempts=3)
def _run_fast_verify():
    """장중 빠른 검증 실행 (1시간 간격)."""
    _start = _time.monotonic()
    from app.services.signal_verifier import fast_verify

    db = SessionLocal()
    try:
        stats = asyncio.run(fast_verify(db))
        if stats["checked"]:
            logger.info(f"Fast verify: {stats['checked']} checked, {stats['early_warnings']} warnings")
    except Exception as e:
        logger.error(f"Fast verify failed: {e}")
        raise
    finally:
        _record_job_duration("fast_verify", _time.monotonic() - _start)
        db.close()


@retry_with_backoff(max_attempts=3)
def _run_commodity_price_fetch():
    """원자재 가격 수집 + 급변 알림 생성."""
    _start = _time.monotonic()
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
        raise
    finally:
        _record_job_duration("commodity_price_fetch", _time.monotonic() - _start)
        db.close()


@retry_with_backoff(max_attempts=3)
def _run_commodity_news_crawl():
    """원자재 뉴스 크롤링 (기존 크롤러 재사용)."""
    _start = _time.monotonic()
    from app.services.commodity_news_service import crawl_commodity_news

    db = SessionLocal()
    try:
        count = asyncio.run(crawl_commodity_news(db))
        if count:
            logger.info(f"원자재 뉴스 크롤링 완료: {count}개 기사")
    except Exception as e:
        logger.error(f"원자재 뉴스 크롤링 실패: {e}")
        raise
    finally:
        _record_job_duration("commodity_news_crawl", _time.monotonic() - _start)
        db.close()


def _run_krx_session_keepalive():
    """data.krx.co.kr 세션 연장 — 20분 간격으로 호출하여 JSESSIONID 만료 방지.

    세션 타임아웃: 약 30분 비활성 시 만료.
    로그인 시 NiceProtect 암호화로 자동 재로그인 불가 → 세션 연장 방식으로 대체.
    KRX_DATA_JSESSIONID 미설정 시 조용히 건너뜀.
    """
    from app.services.krx_short_selling_crawler import keepalive_krx_session
    asyncio.run(keepalive_krx_session())


def _run_krx_short_selling_crawl():
    """KRX 공매도 잔고 수집 — 전 영업일 기준 KOSPI/KOSDAQ 전 종목."""
    _start = _time.monotonic()
    from app.services.krx_short_selling_crawler import crawl_krx_short_selling

    db = SessionLocal()
    try:
        count = asyncio.run(crawl_krx_short_selling(db))
        logger.info(f"KRX 공매도 잔고 수집 완료: {count}건 저장")
    except Exception as e:
        logger.error(f"KRX 공매도 잔고 수집 실패: {e}")
        raise
    finally:
        _record_job_duration("krx_short_selling_crawl", _time.monotonic() - _start)
        db.close()


def _run_forum_crawl():
    """종목토론방 크롤링 및 시간별 집계 — SPEC-AI-008 역발상 지표 수집."""
    _start = _time.monotonic()
    from app.services.forum_crawler import crawl_and_aggregate
    from app.models.stock import Stock

    db = SessionLocal()
    try:
        stocks = db.query(Stock).order_by(Stock.id).limit(50).all()
        succeeded = 0
        for stock in stocks:
            stock_code = stock.stock_code
            stock_id = stock.id
            try:
                asyncio.run(crawl_and_aggregate(db, stock_id, stock_code))
                succeeded += 1
            except Exception as e:
                db.rollback()
                logger.error(f"Forum crawl 실패 ({stock_code}): {e}")
        logger.info(f"종토방 크롤링 완료: {succeeded}/{len(stocks)}개 종목 처리")
    except Exception as e:
        logger.error(f"종토방 크롤링 잡 실패: {e}")
        raise
    finally:
        _record_job_duration("forum_crawl", _time.monotonic() - _start)
        db.close()


def _run_macro_global_news_crawl():
    """해외 거시경제 뉴스 크롤링 — 연준/CPI/반도체/달러 등 국내 증시 영향 매크로 뉴스."""
    _start = _time.monotonic()
    from app.services.crawlers.macro_news_crawler import fetch_macro_global_news
    from app.models.news import NewsArticle

    db = SessionLocal()
    try:
        articles = asyncio.run(fetch_macro_global_news())
        existing_urls: set[str] = {
            row[0] for row in db.query(NewsArticle.url).all()
        }
        new_count = 0
        for art in articles:
            url = art.get("url", "")
            if not url or url in existing_urls:
                continue
            existing_urls.add(url)
            try:
                db.add(NewsArticle(
                    title=art["title"][:500],
                    url=url[:1000],
                    source=art.get("source", "macro_global"),
                    published_at=art.get("published_at"),
                    summary=art.get("description", "")[:1000] if art.get("description") else None,
                    sentiment="neutral",
                ))
                new_count += 1
            except Exception as e:
                logger.debug(f"매크로 뉴스 DB 저장 실패 ({url}): {e}")
        db.commit()
        logger.info(f"매크로 글로벌 뉴스 크롤링 완료: {new_count}건 저장 (전체 {len(articles)}건)")
    except Exception as e:
        logger.error(f"매크로 글로벌 뉴스 크롤링 실패: {e}")
        raise
    finally:
        _record_job_duration("macro_global_news_crawl", _time.monotonic() - _start)
        db.close()


@retry_with_backoff(max_attempts=3)
def _run_news_impact_cleanup():
    """90일 초과 뉴스-가격 반응 레코드 정리 (REQ-NPI-016)."""
    _start = _time.monotonic()
    from app.services.news_price_impact_service import cleanup_old_impacts

    db = SessionLocal()
    try:
        deleted = asyncio.run(cleanup_old_impacts(db))
        if deleted:
            logger.info(f"News impact cleanup: {deleted} records deleted")
    except Exception as e:
        logger.error(f"News impact cleanup failed: {e}")
        raise
    finally:
        _record_job_duration("news_impact_cleanup", _time.monotonic() - _start)
        db.close()


@retry_with_backoff(max_attempts=3)
def _run_relation_inference():
    """주간 종목/섹터 관계 증분 추론."""
    _start = _time.monotonic()
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
        raise
    finally:
        _record_job_duration("relation_inference", _time.monotonic() - _start)
        db.close()


def _is_kr_market_open() -> bool:
    """한국 주식시장 거래일 여부를 간이 판정한다 (주말 제외)."""
    from datetime import timezone, timedelta

    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst)
    # 토요일(5), 일요일(6)은 휴장
    return now_kst.weekday() < 5


# ---------------------------------------------------------------------------
# SPEC-KS200-001: KOSPI 200 스토캐스틱+이격도 자동매매 스케줄 작업
# ---------------------------------------------------------------------------

def _run_ks200_daily_scan():
    """KOSPI 200 전종목 신호 스캔 — 신호 저장만 수행 (매일 15:30 KST = 06:30 UTC, 평일).

    신호 실행은 익일 09:05 KST에 _run_ks200_morning_execute()가 담당한다.
    오늘 완성 봉 데이터 기준으로 신호를 계산하고 DB에 저장한다.

    SPEC-KS200-001
    """
    if not _is_kr_market_open():
        logger.debug("주말 — KS200 신호 스캔 스킵")
        return

    _start = _time.monotonic()
    from app.services.ks200_signal import run_daily_signal_scan

    db = SessionLocal()
    try:
        scan_result = asyncio.run(run_daily_signal_scan(db))
        logger.info(
            "KS200 신호 스캔 완료: 스캔=%d, 매수신호=%d, 매도신호=%d (익일 09:05에 실행)",
            scan_result["scanned"],
            scan_result["buy_signals"],
            scan_result["sell_signals"],
        )
    except Exception as e:
        logger.error("KS200 신호 스캔 실패: %s", e)
    finally:
        _record_job_duration("ks200_daily_scan", _time.monotonic() - _start)
        db.close()


def _run_fund_morning_execute():
    """오늘 생성된 AI 펀드 시그널을 장 시작 시가에 체결 (매일 09:05 KST, 평일).

    08:30 데일리 브리핑에서 생성된 미체결 FundSignal(paper_executed=False)을
    장 시작 직후 현재가(시가)로 일괄 체결한다.
    실제 투자자와 동일한 장중 체결 조건을 시뮬레이션한다.
    """
    if not _is_kr_market_open():
        logger.debug("주말 — AI 펀드 신호 체결 스킵")
        return

    _start = _time.monotonic()
    from app.services.paper_trading import execute_pending_fund_signals

    db = SessionLocal()
    try:
        exec_result = asyncio.run(execute_pending_fund_signals(db))
        if exec_result["buy_executed"] or exec_result["sell_executed"]:
            logger.info(
                "AI 펀드 매매 체결: 매수=%d, 매도=%d, 스킵=%d",
                exec_result["buy_executed"],
                exec_result["sell_executed"],
                exec_result["skipped"],
            )
        else:
            logger.debug("AI 펀드 체결 대상 신호 없음")
    except Exception as e:
        logger.error("AI 펀드 신호 체결 실패: %s", e)
    finally:
        _record_job_duration("fund_morning_execute", _time.monotonic() - _start)
        db.close()


def _run_ks200_morning_execute():
    """전날 저장된 KS200 신호를 시장 시가에 실행 (매일 09:05 KST = 00:05 UTC, 평일).

    15:30 스캔으로 저장된 미체결 신호를 익일 장 시작 직후에 실행한다.
    시가 기준 체결로 슬리피지를 최소화한다.

    SPEC-KS200-001
    """
    if not _is_kr_market_open():
        logger.debug("주말 — KS200 신호 실행 스킵")
        return

    _start = _time.monotonic()
    from app.services.ks200_trading import execute_pending_signals

    db = SessionLocal()
    try:
        exec_result = asyncio.run(execute_pending_signals(db))
        if exec_result["buy_executed"] or exec_result["sell_executed"]:
            logger.info(
                "KS200 매매 실행: 매수=%d, 매도=%d, 스킵=%d",
                exec_result["buy_executed"],
                exec_result["sell_executed"],
                exec_result["skipped"],
            )
        else:
            logger.debug("KS200 실행 대상 신호 없음")
    except Exception as e:
        logger.error("KS200 신호 실행 실패: %s", e)
    finally:
        _record_job_duration("ks200_morning_execute", _time.monotonic() - _start)
        db.close()


# ---------------------------------------------------------------------------
# SPEC-VIP-001: VIP투자자문 추종 매매 스케줄 작업
# ---------------------------------------------------------------------------

def _run_vip_disclosure_check():
    """VIP투자자문 대량보유 공시 수집 및 처리 (30분 간격, 평일 09:00-18:00 KST).

    SPEC-VIP-001 REQ-VIP-006
    """
    if not _is_kr_market_open():
        logger.debug("주말 — VIP 공시 수집 스킵")
        return

    _start = _time.monotonic()
    from app.services.vip_disclosure_crawler import (
        fetch_vip_disclosures,
        process_unhandled_vip_disclosures,
    )

    db = SessionLocal()
    try:
        fetched = asyncio.run(fetch_vip_disclosures(db, days=3))
        if fetched:
            logger.info("VIP 신규 공시 %d건 수집", fetched)

        processed = asyncio.run(process_unhandled_vip_disclosures(db))
        if processed:
            logger.info("VIP 공시 처리 완료: %d건", processed)
    except Exception as e:
        logger.error("VIP 공시 수집/처리 실패: %s", e)
    finally:
        _record_job_duration("vip_disclosure_check", _time.monotonic() - _start)
        db.close()


def _run_vip_exit_check():
    """VIP 포지션 청산 조건 체크 (60분 간격, 평일 09:00-18:00 KST).

    - 수익률 50% 이상 시 30% 부분 익절 (REQ-VIP-004)
    - 3영업일 경과 1차 포지션에 2차 매수 실행 (REQ-VIP-002)

    SPEC-VIP-001 REQ-VIP-006
    """
    if not _is_kr_market_open():
        logger.debug("주말 — VIP Exit 체크 스킵")
        return

    _start = _time.monotonic()
    from app.services.vip_follow_trading import (
        check_exit_conditions,
        check_second_buy_pending,
    )

    db = SessionLocal()
    try:
        exit_stats = asyncio.run(check_exit_conditions(db))
        if exit_stats["partial_sold"] or exit_stats["full_exit"]:
            logger.info(
                "VIP Exit 체크: 부분익절=%d, 전량청산=%d",
                exit_stats["partial_sold"],
                exit_stats["full_exit"],
            )

        second_buys = asyncio.run(check_second_buy_pending(db))
        if second_buys:
            logger.info("VIP 2차 매수 실행: %d건", second_buys)
    except Exception as e:
        logger.error("VIP Exit 체크 실패: %s", e)
    finally:
        _record_job_duration("vip_exit_check", _time.monotonic() - _start)
        db.close()


@retry_with_backoff(max_attempts=3)
def _run_exit_check():
    """장중 청산 조건 확인 (1시간 간격). 주말에는 스킵."""
    if not _is_kr_market_open():
        logger.debug("주말 — 페이퍼 트레이딩 Exit 체크 스킵")
        return

    _start = _time.monotonic()
    from app.services.paper_trading import check_exit_conditions

    db = SessionLocal()
    try:
        stats = asyncio.run(check_exit_conditions(db))
        if stats["closed"]:
            logger.info(f"Paper trading exit check: {stats['closed']} closed ({stats['reasons']})")
    except Exception as e:
        logger.error(f"Paper trading exit check failed: {e}")
        raise
    finally:
        _record_job_duration("paper_exit_check", _time.monotonic() - _start)
        db.close()


def _run_gap_pullback_check():
    """갭업 풀백 모니터링 (REQ-DISC-015). 장초반 10:00~11:30 KST 15분 간격 실행."""
    if not _is_kr_market_open():
        logger.debug("주말 — 갭풀백 체크 스킵")
        return

    from app.services.disclosure_impact_scorer import _run_gap_pullback_check_sync
    _run_gap_pullback_check_sync()


def _run_keyword_matching():
    """신규 뉴스/공시에서 팔로잉 키워드 매칭 후 알림 발송 (SPEC-FOLLOW-001).

    뉴스/공시/리포트 크롤 완료 후 각각 호출되므로 동시 실행 가능.
    Lock으로 직렬화하여 중복 알림 발송 및 UniqueViolation 방지.
    """
    # 이미 실행 중이면 스킵 (non-blocking acquire)
    if not _keyword_matching_lock.acquire(blocking=False):
        logger.debug("키워드 매칭 이미 실행 중 — 이번 호출 스킵")
        return

    _start = _time.monotonic()
    try:
        from app.services.keyword_matcher import match_keywords_and_notify

        db = SessionLocal()
        try:
            stats = match_keywords_and_notify(db)
            if stats["notified"] > 0 or stats["matched"] > 0:
                logger.info(
                    f"키워드 매칭 완료: 매칭 {stats['matched']}건, "
                    f"알림 {stats['notified']}건, 중복 스킵 {stats['skipped_duplicates']}건"
                )
        except Exception as e:
            logger.error(f"키워드 매칭 실패: {e}")
        finally:
            _record_job_duration("keyword_matching", _time.monotonic() - _start)
            db.close()
    finally:
        _keyword_matching_lock.release()


# ---------------------------------------------------------------------------
# SPEC-AI-006: 자기개선 루프 스케줄 작업
# ---------------------------------------------------------------------------

def _run_failure_aggregation():
    """매일 18:30 KST — 검증된 시그널 실패 패턴 집계."""
    _start = _time.monotonic()
    db = SessionLocal()
    try:
        from app.services.improvement_loop import aggregate_failure_patterns, _log_improvement

        result = asyncio.run(aggregate_failure_patterns(db, days=30))
        if result:
            _log_improvement(
                db,
                action_type="failure_aggregation",
                details=result,
            )
            db.commit()
            logger.info(
                "실패 패턴 집계 완료: 총 %d건, 적중률 %.1f%%",
                result["total_verified"],
                result["accuracy_rate"] * 100,
            )
        else:
            logger.info("실패 패턴 집계: 검증 시그널 부족으로 집계 생략")
    except Exception as e:
        logger.error("실패 패턴 집계 실패: %s", e)
    finally:
        _record_job_duration("failure_aggregation", _time.monotonic() - _start)
        db.close()


def _run_prompt_improvement():
    """매주 일요일 22:00 KST — 실패 패턴 기반 프롬프트 자동 개선."""
    _start = _time.monotonic()
    db = SessionLocal()
    try:
        from app.services.improvement_loop import (
            aggregate_failure_patterns,
            generate_improved_prompt,
            register_treatment_version,
        )

        # 최근 30일 실패 패턴 집계
        failure_summary = asyncio.run(aggregate_failure_patterns(db, days=30))
        if failure_summary is None:
            logger.info("프롬프트 개선: 검증 시그널 부족으로 생략")
            return

        # 적중률이 70% 이상이면 개선 불필요
        if failure_summary["accuracy_rate"] >= 0.70:
            logger.info(
                "프롬프트 개선 생략: 적중률 %.1f%% (목표 70%% 달성)",
                failure_summary["accuracy_rate"] * 100,
            )
            return

        # 개선 프롬프트 생성
        improved = asyncio.run(generate_improved_prompt(db, failure_summary))
        if improved:
            asyncio.run(register_treatment_version(
                db,
                prompt_text=improved,
                rationale=f"적중률 {failure_summary['accuracy_rate'] * 100:.1f}% 개선 목적",
            ))
            logger.info("프롬프트 개선 완료 — 새 실험군 등록")
        else:
            logger.warning("프롬프트 개선: AI 생성 실패")
    except Exception as e:
        logger.error("프롬프트 개선 실패: %s", e)
    finally:
        _record_job_duration("prompt_improvement", _time.monotonic() - _start)
        db.close()


def _run_ab_test_evaluation():
    """매주 일요일 22:30 KST — A/B 테스트 결과 평가 및 오래된 실험 종료."""
    _start = _time.monotonic()
    db = SessionLocal()
    try:
        from app.services.prompt_versioner import evaluate_ab_test
        from app.services.improvement_loop import resolve_stale_ab_test

        # 통계적 유의성 평가 (30일 데이터)
        result = evaluate_ab_test(db, days=30)
        if result:
            logger.info(
                "A/B 테스트 평가: 대조군 %.1f%% vs 실험군 %.1f%% (p=%.4f, winner=%s)",
                result["accuracy_a"],
                result["accuracy_b"],
                result["p_value"],
                result.get("winner", "없음"),
            )

        # 30일 초과 미결론 실험 종료
        resolved = asyncio.run(resolve_stale_ab_test(db, max_days=30))
        if resolved:
            logger.info("오래된 A/B 테스트 미결론 종료")
    except Exception as e:
        logger.error("A/B 테스트 평가 실패: %s", e)
    finally:
        _record_job_duration("ab_test_evaluation", _time.monotonic() - _start)
        db.close()


def _run_factor_weight_adaptation():
    """매월 1일 23:00 KST — 팩터 가중치 자동 조정."""
    _start = _time.monotonic()
    db = SessionLocal()
    try:
        from app.services.improvement_loop import adapt_factor_weights

        new_weights = asyncio.run(adapt_factor_weights(db, days=60))
        if new_weights:
            logger.info("팩터 가중치 조정 완료: %s", new_weights)
        else:
            logger.info("팩터 가중치 조정: 데이터 부족으로 생략")
    except Exception as e:
        logger.error("팩터 가중치 조정 실패: %s", e)
    finally:
        _record_job_duration("factor_weight_adapt", _time.monotonic() - _start)
        db.close()


@retry_with_backoff(max_attempts=3)
def _run_ml_feature_capture():
    """일별 ML 피처 스냅샷 생성 (REQ-025)."""
    _start = _time.monotonic()
    from app.services.ml_feature_engineering import capture_daily_features

    db = SessionLocal()
    try:
        snapshot = asyncio.run(capture_daily_features(db))
        if snapshot:
            logger.info(f"ML 피처 스냅샷 생성: {snapshot.date}")
    except Exception as e:
        logger.error(f"ML 피처 스냅샷 생성 실패: {e}")
        raise
    finally:
        _record_job_duration("ml_feature_capture", _time.monotonic() - _start)
        db.close()


@retry_with_backoff(max_attempts=3)
def _run_sector_momentum():
    """섹터 모멘텀 일간 데이터 수집 + 분석 (매일 16:30 KST)."""
    from app.services.sector_momentum import (
        record_daily_sector_performance,
        detect_momentum_sectors,
        detect_capital_inflow,
        detect_sector_rotation,
    )

    _start = _time.monotonic()
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
        raise
    finally:
        _record_job_duration("sector_momentum", _time.monotonic() - _start)
        db.close()


@retry_with_backoff(max_attempts=3)
def _run_portfolio_snapshot():
    """일말 포트폴리오 스냅샷 (매일 16:00 KST)."""
    _start = _time.monotonic()
    from app.services.paper_trading import take_daily_snapshot

    db = SessionLocal()
    try:
        asyncio.run(take_daily_snapshot(db))
    except Exception as e:
        logger.error(f"Portfolio snapshot failed: {e}")
        raise
    finally:
        _record_job_duration("portfolio_snapshot", _time.monotonic() - _start)
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
    # DART 공시 크롤링 (설정 기반 주기, 시작 시 즉시 실행)
    scheduler.add_job(
        _run_dart_crawl,
        "interval",
        minutes=settings.DART_CRAWL_INTERVAL_MINUTES,
        id="dart_crawl",
        replace_existing=True,
        next_run_time=datetime.now(),
    )
    # SPEC-FOLLOW-002: 증권사 리포트 크롤링 (30분 간격)
    scheduler.add_job(
        _run_securities_report_crawl,
        "interval",
        minutes=30,
        id="securities_report_crawl",
        replace_existing=True,
    )
    # 시가총액 업데이트 (설정 기반 주기)
    scheduler.add_job(
        _update_market_caps,
        "interval",
        hours=settings.MARKET_CAP_UPDATE_HOURS,
        id="market_cap_update",
        replace_existing=True,
        next_run_time=datetime.now(),
    )
    # 데일리 브리핑 + 매수/매도 시그널 생성: 매일 08:30 KST (장 시작 전, 평일만)
    scheduler.add_job(
        _run_daily_briefing,
        "cron",
        day_of_week="mon-fri",
        hour=8,
        minute=30,
        timezone="Asia/Seoul",
        id="daily_briefing",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    # AI 펀드 시그널 배치 체결: 매일 09:05 KST (장 시작 직후)
    # 08:30 브리핑에서 생성된 미체결 FundSignal을 장 시작 시가로 일괄 체결
    scheduler.add_job(
        _run_fund_morning_execute,
        "cron",
        day_of_week="mon-fri",
        hour=9,
        minute=5,
        timezone="Asia/Seoul",
        id="fund_morning_execute",
        max_instances=1,
        coalesce=True,
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
    # 해외 매크로 뉴스 크롤링: 매일 07:30 KST (장전 브리핑 전 수집)
    scheduler.add_job(
        _run_macro_global_news_crawl,
        "cron",
        hour=7,
        minute=30,
        timezone="Asia/Seoul",
        id="macro_global_news_crawl",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    # KRX data.krx.co.kr 세션 연장: 20분 간격 (JSESSIONID 만료 방지)
    # 세션 타임아웃(30분) 이전에 주기적으로 연장하여 공매도 수집이 항상 가능하도록 유지
    scheduler.add_job(
        _run_krx_session_keepalive,
        "interval",
        minutes=20,
        id="krx_session_keepalive",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    # KRX 공매도 잔고 수집: 매일 18:30 KST (KRX 데이터 공시 후)
    scheduler.add_job(
        _run_krx_short_selling_crawl,
        "cron",
        day_of_week="mon-fri",
        hour=18,
        minute=30,
        timezone="Asia/Seoul",
        id="krx_short_selling_crawl",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    # SPEC-AI-008: 종목토론방 크롤링 및 역발상 지표 집계 (30분 간격, 장 시간 내에서만 실행)
    scheduler.add_job(
        _run_forum_crawl,
        "interval",
        minutes=30,
        id="forum_crawl",
        max_instances=1,
        coalesce=True,
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
    # REQ-025: ML 피처 스냅샷 (매일 09:00 KST, 데일리 브리핑 이후)
    scheduler.add_job(
        _run_ml_feature_capture,
        "cron",
        hour=9,
        minute=0,
        timezone="Asia/Seoul",
        id="ml_feature_capture",
        replace_existing=True,
    )
    # REQ-DISC-015: 갭업 풀백 모니터링 (평일 10:00~11:30 KST, 15분 간격)
    for _minute_offset in [0, 15, 30, 45]:
        scheduler.add_job(
            _run_gap_pullback_check,
            "cron",
            day_of_week="mon-fri",
            hour=10,
            minute=_minute_offset,
            timezone="Asia/Seoul",
            id=f"gap_pullback_check_10{_minute_offset:02d}",
            replace_existing=True,
        )
    for _minute_offset in [0, 15, 30]:
        scheduler.add_job(
            _run_gap_pullback_check,
            "cron",
            day_of_week="mon-fri",
            hour=11,
            minute=_minute_offset,
            timezone="Asia/Seoul",
            id=f"gap_pullback_check_11{_minute_offset:02d}",
            replace_existing=True,
        )

    # SPEC-FOLLOW-001: 팔로잉 키워드 매칭 (10분 간격)
    scheduler.add_job(
        _run_keyword_matching,
        "interval",
        minutes=10,
        id="keyword_matching",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )

    # SPEC-AI-006: 자기개선 루프 작업
    # 실패 패턴 집계: 매일 18:30 KST = 09:30 UTC
    from apscheduler.triggers.cron import CronTrigger
    scheduler.add_job(
        _run_failure_aggregation,
        CronTrigger(hour=9, minute=30, timezone="UTC"),
        id="failure_aggregation",
        replace_existing=True,
    )
    # 프롬프트 자동 개선: 매주 일요일 22:00 KST = 13:00 UTC
    scheduler.add_job(
        _run_prompt_improvement,
        CronTrigger(day_of_week="sun", hour=13, minute=0, timezone="UTC"),
        id="prompt_improvement",
        replace_existing=True,
    )
    # A/B 테스트 평가: 매주 일요일 22:30 KST = 13:30 UTC
    scheduler.add_job(
        _run_ab_test_evaluation,
        CronTrigger(day_of_week="sun", hour=13, minute=30, timezone="UTC"),
        id="ab_test_evaluation",
        replace_existing=True,
    )
    # 팩터 가중치 조정: 매월 1일 23:00 KST = 14:00 UTC
    scheduler.add_job(
        _run_factor_weight_adaptation,
        CronTrigger(day=1, hour=14, minute=0, timezone="UTC"),
        id="factor_weight_adapt",
        replace_existing=True,
    )

    # SPEC-KS200-001: KOSPI 200 신호 스캔 (매일 15:30 KST = 06:30 UTC, 평일)
    # 오늘 완성 봉 기준 신호 저장 — 실행은 익일 09:05에 수행
    scheduler.add_job(
        _run_ks200_daily_scan,
        "cron",
        day_of_week="mon-fri",
        hour=6,
        minute=30,
        id="ks200_daily_scan",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    # SPEC-KS200-001: KS200 신호 실행 (매일 09:05 KST = 00:05 UTC, 평일)
    # 전날 15:30에 저장된 미체결 신호를 시가 기준으로 실행
    scheduler.add_job(
        _run_ks200_morning_execute,
        "cron",
        day_of_week="mon-fri",
        hour=0,
        minute=5,
        id="ks200_morning_execute",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )

    # SPEC-VIP-001: VIP투자자문 추종 매매 작업
    # 공시 수집: 평일 30분 간격 (09:00~18:00 KST)
    scheduler.add_job(
        _run_vip_disclosure_check,
        "cron",
        day_of_week="mon-fri",
        hour="9-18",
        minute="*/30",
        timezone="Asia/Seoul",
        id="vip_disclosure_check",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    # VIP 청산/2차 매수 체크: 평일 60분 간격 (09:00~18:00 KST)
    scheduler.add_job(
        _run_vip_exit_check,
        "cron",
        day_of_week="mon-fri",
        hour="9-18",
        minute=0,
        timezone="Asia/Seoul",
        id="vip_exit_check",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        f"Scheduler started: crawling every {interval} min, "
        f"KS200 daily scan at 15:30 KST, "
        f"DART every {settings.DART_CRAWL_INTERVAL_MINUTES} min, "
        f"market cap every {settings.MARKET_CAP_UPDATE_HOURS}h, "
        f"commodity price every 10 min, commodity news every 30 min, "
        f"briefing at 08:30 KST, signal verify at 18:00 KST, "
        f"impact backfill at 18:30 KST, impact cleanup at 03:00 KST, "
        f"relation inference every Sunday 04:00 KST, "
        f"fast verify every 1h, paper exit check every 1h, "
        f"portfolio snapshot at 16:00 KST, "
        f"sector momentum at 16:30 KST, "
        f"ML feature capture at 09:00 KST, "
        f"gap pullback check at 10:00~11:30 KST every 15min, "
        f"failure_aggregation at 18:30 KST, "
        f"prompt_improvement every Sunday 22:00 KST, "
        f"ab_test_evaluation every Sunday 22:30 KST, "
        f"factor_weight_adapt on 1st of month 23:00 KST"
    )


def stop_scheduler():
    """Stop the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
