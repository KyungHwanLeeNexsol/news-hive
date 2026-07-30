import asyncio
import logging
import threading
import time as _time
from datetime import datetime, timedelta, timezone

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
    # misfire_grace_time: 서버 재시작 후 최대 1시간 이내 누락 잡을 복구 실행
    # 기존 30초는 2분 이상 재시작 시 잡 영구 소멸 — 1시간으로 확대
    job_defaults={"misfire_grace_time": 3600, "coalesce": True},
)


# ---------------------------------------------------------------------------
# SPEC-AI-066 REQ-AI066-007: 고임팩트 뉴스 이벤트 구동 재스캔
# ---------------------------------------------------------------------------

# @MX:WARN: [AUTO] SPEC-AI-066 REQ-007 — 모듈 수준 가변 상태 (쿨다운 맵 + 일일 카운터)
# @MX:REASON: Redis 없는 베어메탈 환경. 스레드 안전성은 GIL 의존. 프로세스 재시작 시 리셋(허용 — 정기 스캔이 백업)
_event_rescan_state: dict = {"date": None, "count": 0, "cooldown": {}}


def _reset_event_rescan_state() -> None:
    """이벤트 재스캔 상태 초기화 (테스트/운영 리셋용)."""
    _event_rescan_state["date"] = None
    _event_rescan_state["count"] = 0
    _event_rescan_state["cooldown"] = {}


def _run_event_surge_generation(db) -> int:
    """이벤트 경로에서 급등 시그널 생성을 비동기 1회 실행한다 (테스트에서 패치 가능).

    정기 스캔(_run_surge_signal_generate)과 동일한 run_surge_signal_generation을 재사용하되,
    정기 잡 스케줄/등록에는 전혀 관여하지 않는다 (REQ-007: 정기 스캔 불변).
    """
    from app.services.fund_manager import run_surge_signal_generation

    return asyncio.run(run_surge_signal_generation(db))


def _find_high_conviction_event_stocks(db, config) -> list[str]:
    """SPEC-AI-066 REQ-007: 최근 저장된 기사 중 HIGH-conviction 촉매 바를 만족하는 종목 코드.

    바(bar): 기사 텍스트(title+ai_summary)에 인수/합병/경영권·고임팩트 키워드가 있고,
    감성이 요구 강도(min_sentiment_high) 이상.
    """
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    from app.models.news import NewsArticle
    from app.models.news_relation import NewsStockRelation
    from app.models.stock import Stock
    from app.services.surge_detector import _has_catalyst_keyword, _positive_sentiment_score

    catalyst = config.catalyst_conviction
    _cutoff = (_dt.now(_tz.utc) - _td(hours=config.volume_news_combo.news_window_hours)).replace(tzinfo=None)

    rows = (
        db.query(
            Stock.stock_code,
            NewsArticle.title,
            NewsArticle.ai_summary,
            NewsArticle.sentiment,
        )
        .join(NewsStockRelation, NewsStockRelation.news_id == NewsArticle.id)
        .join(Stock, Stock.id == NewsStockRelation.stock_id)
        .filter(NewsArticle.collected_at >= _cutoff)
        .all()
    )

    qualifying: list[str] = []
    _seen: set[str] = set()
    for code, title, ai_summary, sentiment in rows:
        if code in _seen:
            continue
        _text = (title or "") + " " + (ai_summary or "")
        if not _has_catalyst_keyword(_text, config):
            continue
        if _positive_sentiment_score(sentiment) < catalyst.min_sentiment_high:
            continue
        _seen.add(code)
        qualifying.append(code)
    return qualifying


def _maybe_trigger_event_rescan(db, config, now=None) -> bool:
    """SPEC-AI-066 REQ-007: 신규 HIGH-conviction 기사가 있으면 급등 재스캔을 1회 트리거한다.

    가드: event_rescan_enabled 스위치, 종목당 쿨다운(event_rescan_cooldown_minutes),
    일일 상한(max_daily_event_triggers, LLM 예산 보호). 상한/쿨다운 도달 시 스킵하고
    정기 스캔에 위임한다. 정기 스캔은 이 경로와 무관하게 그대로 동작한다.

    Returns:
        트리거가 실행되었으면 True.
    """
    catalyst = config.catalyst_conviction
    if not catalyst.event_rescan_enabled:
        return False

    if now is None:
        now = datetime.now(timezone.utc)

    # 날짜 변경 시 일일 카운터 리셋
    _today = now.date()
    if _event_rescan_state["date"] != _today:
        _event_rescan_state["date"] = _today
        _event_rescan_state["count"] = 0
        _event_rescan_state["cooldown"] = {}

    qualifying = _find_high_conviction_event_stocks(db, config)
    if not qualifying:
        return False

    # 일일 상한 체크 (LLM 예산 보호)
    if _event_rescan_state["count"] >= catalyst.max_daily_event_triggers:
        logger.info("[이벤트재스캔] 일일 상한(%d) 도달 — 정기 스캔에 위임", catalyst.max_daily_event_triggers)
        return False

    # 종목당 쿨다운 필터
    _cooldown = timedelta(minutes=catalyst.event_rescan_cooldown_minutes)
    fresh: list[str] = []
    for code in qualifying:
        _last = _event_rescan_state["cooldown"].get(code)
        if _last is not None and (now - _last) < _cooldown:
            continue
        fresh.append(code)

    if not fresh:
        logger.debug("[이벤트재스캔] 모든 HIGH 종목이 쿨다운 내 — 스킵")
        return False

    # 트리거 1회 실행
    try:
        _count = _run_event_surge_generation(db)
        logger.info("[이벤트재스캔] 트리거 완료: 종목=%s 시그널=%s", fresh, _count)
    except Exception as e:
        logger.error("[이벤트재스캔] 트리거 실패: %s", e)
        return False

    for code in fresh:
        _event_rescan_state["cooldown"][code] = now
    _event_rescan_state["count"] += 1
    return True


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

    # SPEC-AI-066 REQ-007: 뉴스 저장 완료 훅 — HIGH-conviction 촉매 기사가 저장되면
    # 다음 정기 스캔을 기다리지 않고 급등 재스캔을 1회 트리거한다 (기본 비활성, staged rollout).
    # 정기 스캔(08:00/09:05/10:00/15:20 KST)은 이 훅과 무관하게 그대로 동작한다.
    try:
        from app.surge_config.surge_settings import get_surge_config
        _sc = get_surge_config()
        if _sc.catalyst_conviction.event_rescan_enabled:
            _erdb = SessionLocal()
            try:
                _maybe_trigger_event_rescan(_erdb, _sc)
            finally:
                try:
                    _erdb.close()
                except Exception:
                    pass
    except Exception as e:
        logger.error(f"이벤트 재스캔 훅 실패 (정기 스캔에 영향 없음): {e}")


def _cleanup_old_articles(db):
    """Delete news articles older than 5 days."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import func
    from app.models.news import NewsArticle
    from app.models.news_relation import NewsStockRelation

    cutoff = datetime.now(timezone.utc) - timedelta(days=5)

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
    logger.info(f"Cleaned up {len(old_ids)} articles older than 5 days")


def _cleanup_old_disclosures(db):
    """Delete disclosures older than 5 days based on rcept_dt (YYYYMMDD string)."""
    from datetime import datetime, timedelta
    from app.models.disclosure import Disclosure

    cutoff = (datetime.now() - timedelta(days=5)).strftime("%Y%m%d")
    deleted = db.query(Disclosure).filter(Disclosure.rcept_dt < cutoff).delete(synchronize_session=False)
    if deleted:
        db.commit()
        logger.info(f"Cleaned up {deleted} disclosures older than 5 days")


# @MX:ANCHOR: [AUTO] _run_dart_crawl — 스케줄러 정기 잡 + watchdog(_check_dart_health) 양쪽에서
# 직접 호출되는 고 fan_in(>=3) 진입점. 정리(_cleanup_old_disclosures)/수집(fetch_dart_disclosures)
# 독립 격리 계약을 변경하려면 이 함수를 호출하는 모든 경로(정기 스케줄, watchdog 복구 스레드)의
# 영향을 함께 검토해야 한다.
# @MX:REASON: SPEC-AI-073 REQ-AI073-001 — 정리 실패가 수집을 차단해 8일+ 데이터 아웃티지를
# 유발한 실제 프로덕션 인시던트(2026-06-30~07-08)의 회귀를 막는 방어선. 격리를 제거하면
# 정리 단계의 어떤 미래 실패(FK 위반 외의 사유 포함)도 다시 수집 전체를 중단시킬 수 있다.
@retry_with_backoff(max_attempts=3)
def _run_dart_crawl():
    """Sync wrapper that runs the async DART disclosure crawl."""
    _start = _time.monotonic()
    logger.info("DART crawl 시작 (days=5)")
    from app.services.dart_crawler import fetch_dart_disclosures, backfill_disclosure_stock_ids, backfill_disclosure_report_types

    db = SessionLocal()
    try:
        # @MX:WARN: [AUTO] 정리(cleanup)와 수집(fetch)을 독립 try/except로 격리 — 정리 실패가
        # 수집을 막지 못하게 하는 2차 방어선(FK 원인 교정과 무관하게 항상 유지).
        # @MX:REASON: SPEC-AI-073 REQ-AI073-001. 정리 단계에서 예외(과거 FK ForeignKeyViolation
        # 포함, 향후 다른 원인도 대상)가 발생하면 세션이 abort 상태가 되므로, 수집 진행 전
        # db.rollback()으로 반드시 복구해야 한다(복구 없이 진행 시 PendingRollbackError 위험).
        try:
            _cleanup_old_disclosures(db)
        except Exception as cleanup_err:
            logger.error(f"DART disclosure cleanup failed (수집은 계속 진행): {cleanup_err}")
            db.rollback()

        # days=5: 공휴일 연속 휴장(최대 3일) + 복구 버퍼 2일. watchdog 2h 재실행으로 장기 다운타임 불필요.
        count = asyncio.run(fetch_dart_disclosures(db, days=5))
        logger.info(f"DART crawl completed: {count} new disclosures")
        # Re-link any previously unlinked disclosures
        backfill_disclosure_stock_ids(db)
        backfill_disclosure_report_types(db)
    except Exception as e:
        logger.error(f"DART crawl failed: {e}")
        raise
    finally:
        _record_job_duration("dart_crawl", _time.monotonic() - _start)
        # SSL 연결 끊김 시 close() 자체가 에러를 던져 APScheduler jobstore 업데이트를
        # 실패시켜 잡이 "실행 중" 상태로 stuck되는 버그 방어 (cf. 5c2662c)
        try:
            db.rollback()
        except Exception:
            pass
        try:
            db.close()
        except Exception:
            pass

    # DART 공시 크롤링 후 키워드 매칭 실행 (SPEC-FOLLOW-001)
    _run_keyword_matching()


def _send_dart_stale_alert(elapsed_hours: float) -> None:
    """DART stale 감지 시 Telegram 관리자 알림."""
    import os
    chat_id = os.environ.get("TELEGRAM_ADMIN_CHAT_ID")
    if not chat_id:
        logger.debug("TELEGRAM_ADMIN_CHAT_ID 미설정, DART alert 스킵")
        return
    try:
        from app.services.telegram_service import send_telegram_message
        msg = (
            f"⚠️ [NewsHive] DART 공시 크롤러 이상\n"
            f"마지막 수집: {elapsed_hours:.1f}시간 전\n"
            f"자동 재크롤 트리거 중..."
        )
        asyncio.run(send_telegram_message(chat_id, msg))
    except Exception as e:
        logger.warning("DART stale 알림 발송 실패: %s", e)


def _check_dart_health() -> None:
    """DART stale 감지 watchdog — 2시간 이상 공시 미수집 시 자동 재크롤.

    장 시간(07:00~18:00 KST)에만 동작한다. 수집 지연 2시간 초과 시:
      1. CRITICAL 로그 출력
      2. Telegram 관리자 알림 (TELEGRAM_ADMIN_CHAT_ID 설정 시)
      3. 별도 스레드에서 _run_dart_crawl() 직접 실행
         (job.modify()는 APScheduler executor 문제로 실제 실행이 보장되지 않음)
    """
    import threading

    from sqlalchemy import func as sqlfunc
    from app.models.disclosure import Disclosure

    now_kst = datetime.now(timezone(timedelta(hours=9)))
    if not (7 <= now_kst.hour < 18):
        return

    db = SessionLocal()
    try:
        latest = db.query(sqlfunc.max(Disclosure.created_at)).scalar()
        now_utc = datetime.now(timezone.utc)

        if latest is None:
            elapsed_hours = 999.0
        else:
            # PostgreSQL TIMESTAMPTZ → timezone-aware; naive datetime이면 UTC로 간주
            if latest.tzinfo is None:
                latest = latest.replace(tzinfo=timezone.utc)
            elapsed_hours = (now_utc - latest).total_seconds() / 3600

        if elapsed_hours > 2.0:
            logger.critical(
                "DART HEALTH ALERT: 마지막 공시 수집이 %.1f시간 전입니다. 즉시 재크롤 트리거.",
                elapsed_hours,
            )
            _send_dart_stale_alert(elapsed_hours)
            # job.modify()는 APScheduler executor 문제로 실제 함수 실행이 보장 안 됨.
            # threading.Thread로 직접 실행해 즉시 크롤이 보장되도록 함.
            threading.Thread(target=_run_dart_crawl, daemon=True, name="dart_health_recovery").start()
            logger.info("DART HEALTH: dart_crawl 복구 스레드 시작")
        else:
            logger.debug("DART HEALTH: OK (%.1fh 전 수집)", elapsed_hours)
    except Exception as e:
        logger.error("DART HEALTH check 실패: %s", e)
    finally:
        db.close()


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


# SPEC-AI-087 REQ-001: 시장당 안전 상한(페이지당 50종목, 최대 3,000종목/시장). 기존
# range(1, 11)(최대 500종목) 고정 상한이 추적 종목(stocks 테이블) 커버리지를 조용히
# 절단하던 근본원인 — Naver API 자체에는 500종목 제한이 없음(이번 세션 실측:
# KOSPI totalCount=2471, KOSDAQ=1822). 안전 상한은 API 이상 동작(무한 페이지네이션 등)
# 방어선일 뿐이며, 정상 경로는 `if not items: break` 조기 종료로 그보다 먼저 끝난다.
_MARKET_CAP_UPDATE_MAX_PAGES = 60


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
            for page in range(1, _MARKET_CAP_UPDATE_MAX_PAGES + 1):
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
def _run_keyword_backfill():
    """SPEC-AI-087 REQ-007: keywords가 NULL/공백인 추적 종목에 키워드 태깅을 시도한다.

    backfill_stock_keywords()는 이미 저장된 NewsArticle/Disclosure 레코드만 읽으며
    외부 API/LLM 호출이 없어(REQ-AI084-004(b)) 정기 실행 비용이 낮다. 이미 keywords가
    채워진 종목(수동 설정 포함)은 idempotent 계약에 따라 건드리지 않는다.
    """
    _start = _time.monotonic()
    from app.services.keyword_tagging_service import backfill_stock_keywords

    db = SessionLocal()
    try:
        result = backfill_stock_keywords(db)
        logger.info(
            "[keyword_backfill] 스캔 %d개, 신규 태깅 %d개, 기존 보존(스킵) %d개",
            result.stocks_scanned,
            result.stocks_tagged,
            result.stocks_skipped_existing,
        )
    except Exception as e:
        logger.error(f"Keyword backfill failed: {e}")
        raise
    finally:
        _record_job_duration("keyword_backfill", _time.monotonic() - _start)
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
            logger.info(f"Daily briefing generated: {briefing.id} (ai_model={briefing.ai_model})")
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


# ---------------------------------------------------------------------------
# SPEC-AI-013: 급등예측 모의투자 포트폴리오 스케줄 작업
# ---------------------------------------------------------------------------

def _run_auto_register_stocks():
    """상승률 상위 종목 중 DB 미등록 종목 자동 등록 (평일 15:10 KST).

    급등 시그널 생성(15:20) 10분 전에 실행하여 당일 급등 후보 종목 누락을 방지한다.
    """
    if not _is_kr_market_open():
        return

    _start = _time.monotonic()
    from app.services.stock_registry_service import register_unknown_stocks

    db = SessionLocal()
    try:
        count = asyncio.run(register_unknown_stocks(db))
        logger.info("신규 종목 자동 등록 완료: %d개", count)
    except Exception as e:
        logger.error("신규 종목 자동 등록 실패: %s", e)
    finally:
        _record_job_duration("auto_register_stocks", _time.monotonic() - _start)
        db.close()


def _run_surge_collect_outcomes():
    """SPEC-AI-041: 당일 실제 급등주 결과 수집 (평일 16:10 KST)."""
    if not _is_kr_market_open():
        logger.debug("주말 — surge 결과 수집 스킵")
        return

    _start = _time.monotonic()
    from app.services.surge_actual_outcome_service import collect_daily_surge_outcomes
    from datetime import date as _date
    from sqlalchemy.exc import OperationalError

    today = _date.today()
    db = SessionLocal()
    try:
        try:
            count = asyncio.run(collect_daily_surge_outcomes(db, today))
        except OperationalError as e:
            # 2026-06-30 16:00 KST 재현 사례: 15:20 시그널 생성 잡(12~15분 실행)이
            # 끝난 직후 idle 상태였던 DB 연결이 SSL 끊김으로 죽어있어 이 잡이
            # 재시도 없이 조용히 실패, surge_actual_outcome이 당일 0건으로 남았다.
            # 오염된 세션을 버리고 새 세션으로 1회만 재시도한다.
            logger.error("surge collect outcomes SSL 연결 오류 — 세션 재생성 후 재시도: %s", e)
            try:
                db.rollback()
            except Exception:
                pass
            try:
                db.close()
            except Exception:
                pass
            db = SessionLocal()
            try:
                count = asyncio.run(collect_daily_surge_outcomes(db, today))
            except Exception as retry_e:
                logger.error(
                    "surge collect outcomes 재시도 실패 — 당일(%s) 결과 수집 불가: %s",
                    today, retry_e, exc_info=True,
                )
                return
        logger.info("surge 실제 결과 수집 완료: %d건", count)
    except Exception:
        logger.exception("surge collect outcomes 실패")
        raise
    finally:
        _record_job_duration("surge_collect_outcomes", _time.monotonic() - _start)
        # SSL 연결 끊김 시 close() 자체가 에러를 던져 APScheduler로 전파되므로 방어
        try:
            db.rollback()
        except Exception:
            pass
        try:
            db.close()
        except Exception:
            pass


def _run_surge_verify_predictions():
    """SPEC-AI-041: T-1 시그널 vs T 실제 결과 평가 (평일 18:30 KST, verify_signals 18:00 완료 후)."""
    if not _is_kr_market_open():
        logger.debug("주말 — surge 예측 검증 스킵")
        return

    _start = _time.monotonic()
    from app.services.surge_evaluation_service import (
        evaluate_surge_predictions,
        analyze_misses_with_llm,
    )
    from datetime import date as _date

    db = SessionLocal()
    try:
        today = _date.today()

        # SPEC-AI-065 REQ-5 버그픽스: T-1(예측일)에 라이브 시그널 생성 중 저장된
        # pool_counts를 조회하여 evaluate_surge_predictions에 전달한다.
        # 레코드가 없으면(fail-open) None을 넘겨 기존과 동일하게 0으로 기록된다.
        pool_counts = None
        try:
            from app.services.surge_trading_service import _get_prev_business_day
            from app.services.surge_universe_pool_service import get_pool_counts_for_date

            _prev_day_for_pool = _get_prev_business_day(today)
            pool_counts = get_pool_counts_for_date(db, _prev_day_for_pool)
        except Exception as _pce:
            logger.warning("[급등평가] pool_counts 조회 실패 (0으로 기록됨): %s", _pce)

        # SPEC-AI-086 REQ-AI086-006: 직전 평가 레코드의 scannable_actual_count/
        # scan_universe_size를 조회하여 scannable_denominator_expanded 판정에 전달한다.
        # 레코드가 없으면(fail-open) None을 넘겨 evaluate_surge_predictions가 계산을
        # 건너뛰고(REQ-AI086-007 기존 동작과 동일) 속성만 None으로 남긴다.
        prior_scannable_metrics = None
        try:
            from app.models.surge_prediction_evaluation import (
                SurgePredictionEvaluation as _SPE,
            )

            _prior_eval = (
                db.query(_SPE)
                .filter(_SPE.evaluation_date < today)
                .order_by(_SPE.evaluation_date.desc())
                .first()
            )
            if _prior_eval is not None:
                prior_scannable_metrics = {
                    "scannable_actual_count": _prior_eval.scannable_actual_count or 0,
                    "scan_universe_size": _prior_eval.scan_universe_size or 0,
                }
        except Exception as _pme:
            logger.warning("[급등평가] prior_scannable_metrics 조회 실패 (무시): %s", _pme)

        evaluation = evaluate_surge_predictions(
            db, today, pool_counts=pool_counts, prior_scannable_metrics=prior_scannable_metrics
        )
        logger.info(
            "surge 예측 평가 완료: precision=%.3f, recall=%.3f, f1=%.3f, "
            "scannable_denominator_expanded=%s",
            evaluation.precision or 0.0,
            evaluation.recall or 0.0,
            evaluation.f1_score or 0.0,
            getattr(evaluation, "scannable_denominator_expanded", None),
        )

        # SPEC-AI-061 REQ-AI061-B01: 핵심 평가 결과(precision/recall/f1)를 FN 분석 블록 진입 전에
        # 즉시 커밋하여 이후 선택적 보강 블록에서 SSL 오류/쿼리 실패가 발생해도 결과를 보존한다.
        db.commit()

        # SPEC-AI-086 REQ-AI086-002: non_scannable 실제급등주 원인 진단(truncated/absent)을
        # 실제로 실행한다 — 핵심 평가 결과(위 commit)와 격리된 별도 블록으로, 실패해도
        # precision/recall/f1/scannable_denominator_expanded 결과는 보존된다. 진단 자체는
        # 함수 내부에서 요약 로그 1줄을 남긴다(REQ-AI086-008과 별개 로그, evaluate 시점 데이터
        # 부재로 단일 로그 라인 통합 불가 — plan.md 실용적 분리 결정).
        try:
            from app.services.surge_evaluation_service import diagnose_non_scannable_causes

            diagnose_non_scannable_causes(db, today)
        except Exception as _dge:
            logger.warning("[급등평가] non_scannable 원인 진단 실패 (무시): %s", _dge)

        # FN 분석 블록 — 예외 격리 (precision/recall/f1 결과는 위 commit으로 이미 보존)
        # SPEC-AI-061 REQ-AI061-B02
        try:
            if evaluation.false_negative > 0:
                # FN 종목 조회
                from app.models.surge_actual_outcome import SurgeActualOutcome as _SAO
                from app.models.fund_signal import FundSignal as _FS
                from app.models.stock import Stock as _Stock
                from sqlalchemy import func as _func

                from app.services.surge_trading_service import _get_prev_business_day
                prev_day = _get_prev_business_day(today)

                predicted_codes = {
                    row.stock_code
                    for row in db.query(_Stock.stock_code)
                    .join(_FS, _FS.stock_id == _Stock.id)
                    .filter(
                        _FS.surge_metadata.isnot(None),
                        _func.date(_FS.created_at) == prev_day,
                    )
                    .all()
                }

                missed = [
                    {"stock_code": r.stock_code, "stock_name": r.stock_name, "change_rate": r.change_rate}
                    for r in db.query(_SAO.stock_code, _SAO.stock_name, _SAO.change_rate)
                    .filter(_SAO.trading_date == today, _SAO.was_surge.is_(True))
                    .all()
                    if r.stock_code not in predicted_codes
                ]

                analysis = asyncio.run(analyze_misses_with_llm(missed, db))
                evaluation.miss_analysis_json = analysis
                db.commit()
                logger.info("LLM 미스 분석 저장 완료")
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
            logger.warning("FN 분석 실패 — 평가 결과는 보존됨", exc_info=True)

        # SPEC-AI-060: TP 분석 + 종목별 분석 결과 저장 (예외 격리 — precision/recall/f1 보존)
        try:
            from app.services.surge_evaluation_service import (
                analyze_true_positives_with_llm,
                _LLMBudgetGuard,
            )
            from app.surge_config.surge_settings import get_surge_config
            import json as _json

            cfg = get_surge_config().per_stock_analysis
            if cfg.enabled:
                # TP 종목 조회 (predicted_set ∩ actual_set)
                from app.models.surge_actual_outcome import SurgeActualOutcome as _SAO2
                from app.models.fund_signal import FundSignal as _FS2
                from app.models.stock import Stock as _Stock2
                from sqlalchemy import func as _func2

                prev_day2 = _get_prev_business_day(today)
                predicted_codes2 = {
                    row.stock_code
                    for row in db.query(_Stock2.stock_code)
                    .join(_FS2, _FS2.stock_id == _Stock2.id)
                    .filter(
                        _FS2.surge_metadata.isnot(None),
                        _func2.date(_FS2.created_at) == prev_day2,
                    )
                    .all()
                }
                actual_surge_rows2 = (
                    db.query(_SAO2.stock_code, _SAO2.stock_name, _SAO2.change_rate)
                    .filter(_SAO2.trading_date == today, _SAO2.was_surge.is_(True))
                    .all()
                )
                tp_stocks = [
                    {"stock_code": r.stock_code, "stock_name": r.stock_name, "change_rate": r.change_rate}
                    for r in actual_surge_rows2
                    if r.stock_code in predicted_codes2
                ]

                budget_guard = _LLMBudgetGuard(
                    max_calls=cfg.max_calls_per_run,
                    delay_sec=cfg.call_delay_sec,
                )
                tp_analyses = asyncio.run(
                    analyze_true_positives_with_llm(tp_stocks, db, budget_guard)
                )

                # miss_analysis_json이 JSON인 경우 fn_analysis 추출, 아니면 원문 보존
                fn_data: list = []
                try:
                    parsed_miss = _json.loads(evaluation.miss_analysis_json or "{}")
                    fn_data = parsed_miss.get("per_stock", [])
                except Exception:
                    fn_data = []

                per_stock_data = {
                    "fn_analysis": fn_data,
                    "tp_analysis": tp_analyses,
                }
                evaluation.per_stock_analysis_json = _json.dumps(
                    per_stock_data, ensure_ascii=False
                )
                db.commit()
                logger.info(
                    "종목별 분석 저장 완료 (tp=%d, fn=%d)",
                    len(tp_analyses), len(fn_data),
                )
        except Exception:
            # SPEC-AI-061 REQ-AI061-B03: TP 분석 블록 실패 시 세션을 clean 상태로 복원
            try:
                db.rollback()
            except Exception:
                pass
            logger.warning("종목별 분석 실패 — 평가 결과는 보존됨", exc_info=True)
            # raise 하지 않음: precision/recall/f1 결과가 이미 commit됨 (AC-13, SPEC-AI-061 REQ-AI061-B04)
    except Exception:
        logger.exception("surge verify predictions 실패")
        raise
    finally:
        _record_job_duration("surge_verify_predictions", _time.monotonic() - _start)
        db.close()


def _run_surge_auto_improve():
    """SPEC-AI-041: 탐지기 가중치 자동 개선 (평일 19:00 KST, verify_signals 18:00 이후)."""
    if not _is_kr_market_open():
        logger.debug("주말 — surge 자동 개선 스킵")
        return

    _start = _time.monotonic()
    from app.services.surge_auto_improver import analyze_and_improve
    from datetime import date as _date

    db = SessionLocal()
    try:
        logs = analyze_and_improve(db, _date.today())
        logger.info("surge 자동 개선 완료: %d개 파라미터 변경", len(logs))
    except Exception:
        logger.exception("surge auto improve 실패")
        raise
    finally:
        _record_job_duration("surge_auto_improve", _time.monotonic() - _start)
        db.close()


def _run_surge_backtest_gate():
    """SPEC-AI-069 REQ-AI069-001: backtest 운영 게이트 pass/fail/insufficient 판정 영속화.

    평일 18:45 KST (verify_predictions 18:30 이후, auto_improve 19:00 이전).
    """
    if not _is_kr_market_open():
        logger.debug("주말 — backtest 게이트 스킵")
        return

    _start = _time.monotonic()
    import json as _json
    from datetime import date as _date

    from app.models.surge_backtest_result import SurgeBacktestResult
    from app.services.surge_backtest import run_backtest_gate

    db = SessionLocal()
    try:
        verdict = run_backtest_gate(db)
        record = SurgeBacktestResult(
            run_date=_date.today(),
            total_signals=verdict.total_signals,
            directional_accuracy=verdict.directional_accuracy,
            average_return_pct=verdict.average_return_pct,
            verdict=verdict.verdict,
            config_hash=verdict.config_hash,
            min_signals=verdict.min_signals,
            min_directional_accuracy=verdict.min_directional_accuracy,
            lookback_days=verdict.lookback_days,
            by_combination_json=_json.dumps(verdict.by_combination, ensure_ascii=False),
        )
        db.add(record)
        db.commit()
        logger.info(
            "backtest 게이트 판정 완료: verdict=%s 신호=%d 적중률=%.3f",
            verdict.verdict, verdict.total_signals, verdict.directional_accuracy,
        )
    except Exception:
        logger.exception("surge backtest gate 실패")
        raise
    finally:
        _record_job_duration("surge_backtest_gate", _time.monotonic() - _start)
        db.close()


def _run_surge_detector_contribution():
    """SPEC-AI-070 REQ-001~004: 탐지기별 기여도 집계 + 은퇴 제안 리포트 발송.

    평일 19:05 KST (verify_predictions 18:30, backtest_gate 18:45 이후,
    auto_improve 19:00 이전 — 은퇴 제안이 그날의 최신 backtest 결과를 참조하도록 선행 실행).
    측정·리포트 전용 잡 — surge_detection.yaml/auto.yaml을 쓰지 않으며 탐지기를
    자동으로 추가/제거/비활성화하지 않는다(REQ-004 [HARD]).
    """
    if not _is_kr_market_open():
        logger.debug("주말 — 탐지기 기여도 계산 스킵")
        return

    _start = _time.monotonic()
    from datetime import date as _date

    from app.services.surge_contribution_service import (
        apply_retirement_candidates,
        assess_retirement_candidates,
        build_contribution_report,
        evaluate_detector_contribution,
    )

    db = SessionLocal()
    try:
        trading_date = _date.today()
        rows = evaluate_detector_contribution(db, trading_date)
        assessments = assess_retirement_candidates(db, trading_date)
        apply_retirement_candidates(db, trading_date, assessments)
        report_text = build_contribution_report(
            db, trading_date, contribution_rows=rows, retirement_assessments=assessments
        )
        logger.info("[탐지기기여도] 리포트 생성 완료 (run_date=%s)\n%s", trading_date, report_text)

        # REQ-002: 텔레그램 리포트 발송 — 미설정 시 graceful skip(EC-7), 로그로만 남김
        import os

        chat_id = os.environ.get("TELEGRAM_ADMIN_CHAT_ID")
        if not chat_id:
            logger.info("TELEGRAM_ADMIN_CHAT_ID 미설정 — 탐지기 기여도 리포트 텔레그램 발송 스킵")
        else:
            from app.services.telegram_service import send_telegram_message

            success = asyncio.run(send_telegram_message(chat_id, report_text))
            if success:
                logger.info("탐지기 기여도 리포트 발송 완료 (run_date=%s)", trading_date)
            else:
                logger.warning("탐지기 기여도 리포트 발송 실패 (run_date=%s)", trading_date)
    except Exception:
        logger.exception("surge detector contribution 실패")
        raise
    finally:
        _record_job_duration("surge_detector_contribution", _time.monotonic() - _start)
        db.close()


def _run_surge_missing_evaluation_check():
    """SPEC-AI-092 REQ-AI092-006: 장마감 이후 당일 actual/evaluation 레코드 누락 감시.

    평일 19:15 KST (verify_predictions 18:30, backtest_gate 18:45, auto_improve 19:00,
    detector_contribution 19:05 이후 — 모든 평가 관련 잡이 실행을 마친 뒤 확인해야
    "아직 안 돌았음"을 "누락"으로 오판하지 않는다). 순수 읽기 감지 + fail-open 경보.
    """
    if not _is_kr_market_open():
        logger.debug("주말 — 급등평가 누락 감시 스킵")
        return

    _start = _time.monotonic()
    from app.services.surge_evaluation_service import check_and_alert_missing_evaluation

    db = SessionLocal()
    try:
        status = check_and_alert_missing_evaluation(db)
        logger.info("[급등평가누락감시] 확인 완료: %s", status)
    except Exception:
        logger.exception("surge missing evaluation check 실패")
        raise
    finally:
        _record_job_duration("surge_missing_evaluation_check", _time.monotonic() - _start)
        db.close()


def _run_surge_daily_report():
    """SPEC-AI-041: 텔레그램 일일 리포트 발송 (평일 17:05 KST)."""
    if not _is_kr_market_open():
        logger.debug("주말 — surge 리포트 스킵")
        return

    _start = _time.monotonic()
    from app.services.surge_auto_improver import run_daily_report
    from datetime import date as _date

    db = SessionLocal()
    try:
        asyncio.run(run_daily_report(db, _date.today()))
        logger.info("surge 일일 리포트 발송 완료")
    except Exception:
        logger.exception("surge daily report 실패")
        raise
    finally:
        _record_job_duration("surge_daily_report", _time.monotonic() - _start)
        db.close()


def _run_bollinger_squeeze_detect():
    """볼린저 밴드 스퀴즈 탐지 (평일 15:10 KST, 15:20 시그널 생성 직전).

    SPEC-AI-051 REQ-AI051-003
    """
    if not _is_kr_market_open():
        logger.debug("주말 — 볼린저 스퀴즈 탐지 스킵")
        return

    _start = _time.monotonic()
    db = SessionLocal()
    try:
        from app.services.surge_detector import detect_bollinger_squeeze_signals
        from app.surge_config.surge_settings import BollingerSqueezeConfig
        cfg = BollingerSqueezeConfig()
        results = detect_bollinger_squeeze_signals(db, cfg)
        logger.info("볼린저 스퀴즈 탐지 완료: %d건", len(results))
    except Exception as e:
        logger.error("볼린저 스퀴즈 탐지 잡 실패: %s", e)
    finally:
        _record_job_duration("surge_bollinger_squeeze", _time.monotonic() - _start)
        try:
            db.close()
        except Exception:
            pass


def _run_gap_up_runner_detect():
    """갭상승 런너 파이프라인 (평일 14:30 KST, 당일 체결 아님 — 익일 전용).

    SPEC-AI-051 REQ-AI051-010
    """
    if not _is_kr_market_open():
        logger.debug("주말 — 갭상승 런너 탐지 스킵")
        return

    _start = _time.monotonic()
    db = SessionLocal()
    try:
        from app.services.surge_detector import detect_gap_up_runners
        from app.surge_config.surge_settings import GapUpRunnersConfig
        cfg = GapUpRunnersConfig()
        results = detect_gap_up_runners(db, cfg)
        logger.info("갭상승 런너 탐지 완료: %d건", len(results))
    except Exception as e:
        logger.error("갭상승 런너 탐지 잡 실패: %s", e)
    finally:
        _record_job_duration("surge_gap_up_runners", _time.monotonic() - _start)
        db.close()


def _run_surge_signal_generate():
    """급등예측 시그널 독립 생성 (평일 15:20 KST, 장 마감 10분 전).

    generate_daily_briefing() 전체를 돌리지 않고 _gather_surge_candidates()만
    실행한다. 전일 장 데이터(거래량·테마·공시)가 확정된 시점에 익일 후보를 탐지한다.
    익일 surge_execute_buys(09:00)는 이 시그널을 읽어 매수를 실행한다.

    SPEC-AI-013 REQ-SURGE-TRADE-055
    """
    if not _is_kr_market_open():
        logger.debug("주말 — 급등시그널 생성 스킵")
        return

    _start = _time.monotonic()
    from app.services.fund_manager import run_surge_signal_generation

    db = SessionLocal()
    try:
        count = asyncio.run(run_surge_signal_generation(db))
        logger.info("급등시그널 15:20 생성 완료: %d개", count)
    except Exception as e:
        logger.error("급등시그널 생성 잡 실패: %s", e)
    finally:
        _record_job_duration("surge_signal_generate", _time.monotonic() - _start)
        # SSL 연결 끊김 시 close() 자체가 에러를 던져 APScheduler로 전파되므로 방어
        try:
            db.rollback()
        except Exception:
            pass
        try:
            db.close()
        except Exception:
            pass


def _run_surge_universe_build():
    """SPEC-AI-065 REQ-2: 스캔 유니버스 사전 빌드 (평일 16:00 KST, 시장 마감 후).

    Pool A(DART 공시)/Pool B(거래량 200%+)/Pool C(등락률 5%+) 종목을 수집하여
    다음 날 시그널 생성(15:20 KST)에서 활용할 수 있도록 기준선 업데이트를 준비한다.
    실패해도 당일 시그널 생성에 영향 없음 (fail-open).
    """
    if not _is_kr_market_open():
        logger.debug("주말 — 스캔유니버스 빌드 스킵")
        return

    _start = _time.monotonic()
    from app.services.surge_detector import build_scan_universe
    from app.surge_config.surge_settings import get_surge_config
    from sqlalchemy.exc import OperationalError

    db = SessionLocal()
    try:
        cfg = get_surge_config()
        try:
            universe_codes, entry_pool_map, pool_counts = build_scan_universe(
                db, cfg, existing_codes=set()
            )
        except OperationalError as e:
            # SSL 연결 끊김 시 오염된 세션을 버리고 새 세션으로 1회만 재시도한다
            # (surge_collect_outcomes와 동일한 패턴, 2026-06-30 재현 사례 참고).
            logger.error("스캔유니버스 빌드 SSL 연결 오류 — 세션 재생성 후 재시도: %s", e)
            try:
                db.rollback()
            except Exception:
                pass
            try:
                db.close()
            except Exception:
                pass
            db = SessionLocal()
            try:
                universe_codes, entry_pool_map, pool_counts = build_scan_universe(
                    db, cfg, existing_codes=set()
                )
            except Exception as retry_e:
                logger.error("스캔유니버스 빌드 재시도 실패 (무시): %s", retry_e, exc_info=True)
                return
        logger.info(
            "스캔유니버스 빌드 완료: 총=%d개 (A=%d B=%d C=%d)",
            len(universe_codes),
            pool_counts.get("pool_a", 0),
            pool_counts.get("pool_b", 0),
            pool_counts.get("pool_c", 0),
        )
    except Exception as e:
        logger.warning("스캔유니버스 빌드 실패 (무시): %s", e)
    finally:
        _record_job_duration("surge_universe_build", _time.monotonic() - _start)
        try:
            db.rollback()
        except Exception:
            pass
        try:
            db.close()
        except Exception:
            pass


def _run_surge_execute_buys():
    """급등예측 시그널 기반 매수 실행 (평일 09:00~15:30 KST, 30분 간격).

    is_market_hours() 가드가 서비스 내부에서도 동작하므로
    스케줄러 트리거가 정각(09:00)이 아닌 경우에도 안전하게 처리된다.

    SPEC-AI-013 REQ-SURGE-TRADE-050, REQ-SURGE-TRADE-051
    """
    _start = _time.monotonic()
    from app.services.surge_trading_service import execute_buy_orders

    db = SessionLocal()
    try:
        result = execute_buy_orders(db)
        if result["executed"] > 0:
            logger.info(
                "Surge 매수 실행 완료: executed=%d, skipped=%d, failed=%d",
                result["executed"],
                result["skipped"],
                result["failed"],
            )
        else:
            logger.debug(
                "Surge 매수 실행: executed=0, skipped=%d, failed=%d",
                result["skipped"],
                result["failed"],
            )
    except Exception as e:
        logger.error("Surge 매수 실행 잡 실패: %s", e)
    finally:
        _record_job_duration("surge_execute_buys", _time.monotonic() - _start)
        db.close()


def _run_surge_check_exits():
    """급등예측 포지션 종료 조건 체크 (평일 09:00~15:30 KST, 5분 간격).

    손절(-8%), 익절(+15%), 최대 보유 기간(5거래일) 조건 체크.

    SPEC-AI-013 REQ-SURGE-TRADE-050, REQ-SURGE-TRADE-052
    """
    _start = _time.monotonic()
    from app.services.surge_trading_service import check_exit_conditions

    db = SessionLocal()
    try:
        result = check_exit_conditions(db)
        if result["closed"] > 0:
            logger.info(
                "Surge 종료 체크 완료: closed=%d, still_open=%d, errors=%d",
                result["closed"],
                result["still_open"],
                result["errors"],
            )
        else:
            logger.debug(
                "Surge 종료 체크: closed=0, still_open=%d, errors=%d",
                result["still_open"],
                result["errors"],
            )
    except Exception as e:
        logger.error("Surge 종료 조건 체크 잡 실패: %s", e)
    finally:
        _record_job_duration("surge_check_exits", _time.monotonic() - _start)
        db.close()


def _run_force_max_holding_exit():
    """장 마감 후 max_holding_period 도달 포지션 강제 청산 (평일 15:40 KST).

    APScheduler 잡 누락(missed 이벤트) 또는 15:30 정규장 종료 직후
    check_exit_conditions가 실행되지 않은 경우를 대비한 안전망.

    force_max_holding=True로 호출하여 장 외 시간에도 만기 포지션을 청산한다.
    가격 조회 실패 시 진입가로 보수적 청산(PnL=0) 처리.

    SPEC-AI-013 REQ-SURGE-TRADE-052
    """
    _start = _time.monotonic()
    from app.services.surge_trading_service import check_exit_conditions

    db = SessionLocal()
    try:
        result = check_exit_conditions(db, force_max_holding=True)
        if result["closed"] > 0:
            logger.info(
                "Surge force-max-holding 청산 완료: closed=%d, still_open=%d, errors=%d",
                result["closed"],
                result["still_open"],
                result["errors"],
            )
        else:
            logger.debug(
                "Surge force-max-holding: 청산 대상 없음 (still_open=%d)",
                result["still_open"],
            )
    except Exception as e:
        logger.error("Surge force-max-holding 청산 잡 실패: %s", e)
    finally:
        _record_job_duration("surge_force_max_holding_exit", _time.monotonic() - _start)
        db.close()


def _is_kr_market_open() -> bool:
    """한국 주식시장 거래일 여부를 간이 판정한다 (주말 제외)."""
    from datetime import timezone, timedelta

    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst)
    # 토요일(5), 일요일(6)은 휴장
    return now_kst.weekday() < 5


def _is_trading_day() -> bool:
    """KRX 거래일 여부 판정 (주말 + KRX 임시 공휴일 포함).

    # @MX:NOTE: [AUTO] SPEC-AI-042 REQ-042-011 — surge_preday_scan/preopen_refresh/early_entry 잡용
    #   _is_kr_market_open()은 주말만 체크하지만, 이 함수는 KRX_EXTRA_HOLIDAYS도 포함한다.
    """
    from datetime import timezone, timedelta
    from app.services.surge_trading_service import KRX_EXTRA_HOLIDAYS

    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst)
    if now_kst.weekday() >= 5:  # 토(5)/일(6)
        return False
    if now_kst.date() in KRX_EXTRA_HOLIDAYS:
        return False
    return True


def _run_surge_preday_scan():
    """SPEC-AI-042: 장 마감 후 공시 스캔 (평일 17:00 KST).

    당일 15:30 KST 이후 접수된 공시를 대상으로 두 탐지기를 실행하여
    preday_disclosure 시그널을 저장한다.

    REQ-042-001, REQ-042-011
    """
    if not _is_trading_day():
        logger.debug("주말/휴장일 — surge_preday_scan 스킵")
        return

    _start = _time.monotonic()
    from app.services.preday_signal_service import post_market_scan
    from datetime import timezone as _tz, timedelta as _td
    from datetime import time as _time_cls

    kst = _tz(_td(hours=9))
    today_kst = datetime.now(kst).date()
    scan_from_dt = datetime.combine(today_kst, _time_cls(15, 30)).replace(tzinfo=kst)

    db = SessionLocal()
    try:
        count = post_market_scan(db, scan_from_dt)
        logger.info("surge_preday_scan 완료: %d개 시그널 저장", count)
    except Exception as e:
        logger.exception("surge_preday_scan 잡 실패: %s", e)
    finally:
        _record_job_duration("surge_preday_scan", _time.monotonic() - _start)
        db.close()


def _run_surge_preopen_refresh():
    """SPEC-AI-042: 장전 워치리스트 갱신 (평일 08:00 KST).

    전날 17:00 KST 이후 접수된 공시를 재스캔하여 preday_disclosure 시그널을 보완한다.

    REQ-042-003, REQ-042-011
    """
    if not _is_trading_day():
        logger.debug("주말/휴장일 — surge_preopen_refresh 스킵")
        return

    _start = _time.monotonic()
    from app.services.preday_signal_service import preopen_watchlist_refresh

    db = SessionLocal()
    try:
        count = preopen_watchlist_refresh(db)
        logger.info("surge_preopen_refresh 완료: %d개 시그널 추가", count)
    except Exception as e:
        logger.exception("surge_preopen_refresh 잡 실패: %s", e)
    finally:
        _record_job_duration("surge_preopen_refresh", _time.monotonic() - _start)
        db.close()


def _run_surge_preday_early_entry():
    """SPEC-AI-042: preday_disclosure 시그널 조기 진입 (평일 09:05 KST).

    preday_disclosure 보유 종목의 갭 비율을 조회하여
    0% <= gap < gap_entry_threshold 범위 종목에 execute_buy_orders를 호출한다.
    is_buy_eligible_hours/BUY_CUTOFF 가드에 의존 (우회 금지, REQ-042-013).

    REQ-042-005~007, REQ-042-011, REQ-042-013
    """
    if not _is_trading_day():
        logger.debug("주말/휴장일 — surge_preday_early_entry 스킵")
        return

    _start = _time.monotonic()
    from app.services.preday_signal_service import early_entry_check

    db = SessionLocal()
    try:
        result = early_entry_check(db)
        logger.info(
            "surge_preday_early_entry 완료: candidates=%d, entered=%d, "
            "skipped_gapup=%d, skipped_gapdown=%d",
            result.get("candidates", 0),
            result.get("entered", 0),
            result.get("skipped_gapup", 0),
            result.get("skipped_gapdown", 0),
        )
    except Exception as e:
        logger.exception("surge_preday_early_entry 잡 실패: %s", e)
    finally:
        _record_job_duration("surge_preday_early_entry", _time.monotonic() - _start)
        db.close()


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


def _run_market_regime_update():
    """시장 레짐 분류 실행 (평일 08:55 KST — 데일리 브리핑 5분 전).

    SPEC-AI-015: 브리핑 실행 전 오늘의 시장 레짐을 사전 분류하여 DB에 캐시한다.
    브리핑/시그널 생성 시 DB 조회로 즉시 참조 가능하도록 보장한다.
    """
    _start = _time.monotonic()
    from app.services.market_regime_service import get_or_create_today_regime

    db = SessionLocal()
    try:
        regime = get_or_create_today_regime(db)
        logger.info(
            "시장 레짐 분류 완료: %s (신뢰도=%.2f)",
            regime.regime.value if hasattr(regime.regime, 'value') else str(regime.regime),
            regime.confidence_score,
        )
    except Exception as e:
        logger.error("시장 레짐 분류 실패: %s", e)
        raise
    finally:
        _record_job_duration("market_regime_update", _time.monotonic() - _start)
        db.close()


# SPEC-AI-064: 코스피 대폭락 조기 경보 래퍼 함수 3개
def _run_us_close_crash_scan():
    """미국 장마감 후 S&P 500 전일 종가 스캔 (06:30 KST, SPEC-AI-064 그룹 D)."""
    _start = _time.monotonic()
    from app.services.crash_guard_service import run_us_close_crash_scan

    db = SessionLocal()
    try:
        asyncio.run(run_us_close_crash_scan(db))
    except Exception:
        logger.exception("crash_us_close_scan 실패")
        raise
    finally:
        _record_job_duration("crash_us_close_scan", _time.monotonic() - _start)
        db.close()


def _run_premarket_crash_scan():
    """장전 글로벌 선물·VIX·환율 + 코스피200 야간 선물 스캔 (08:30 KST, SPEC-AI-064 그룹 A+E)."""
    _start = _time.monotonic()
    from app.services.crash_guard_service import run_premarket_crash_scan

    db = SessionLocal()
    try:
        asyncio.run(run_premarket_crash_scan(db))
    except Exception:
        logger.exception("crash_premarket_scan 실패")
        raise
    finally:
        _record_job_duration("crash_premarket_scan", _time.monotonic() - _start)
        db.close()


def _run_intraday_crash_check():
    """장중 코스피 낙폭 체크 (09:05 KST, SPEC-AI-064 그룹 B).

    fund_morning_execute(09:05), surge_preday_early_entry(09:05)와 id가 다르므로
    replace_existing이 기존 잡을 덮어쓰지 않는다.
    """
    _start = _time.monotonic()
    from app.services.crash_guard_service import run_intraday_crash_check

    db = SessionLocal()
    try:
        asyncio.run(run_intraday_crash_check(db))
    except Exception:
        logger.exception("crash_intraday_check 실패")
        raise
    finally:
        _record_job_duration("crash_intraday_check", _time.monotonic() - _start)
        db.close()


def start_scheduler():
    """Start the background news crawl scheduler."""
    # scheduler.start()을 add_job() 이전에 호출해야 SQLAlchemyJobStore가
    # 초기화된 상태에서 replace_existing=True가 정상 작동함.
    # start() 이전에 add_job()을 호출하면 pending 잡이 DB의 기존 잡을
    # 교체하지 못해 next_run_time이 구 버전으로 stuck되는 버그 발생.
    scheduler.start()
    interval = settings.NEWS_CRAWL_INTERVAL_MINUTES
    scheduler.add_job(
        _run_crawl_job,
        "interval",
        minutes=interval,
        id="news_crawl",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),
    )
    # DART 공시 크롤링 (설정 기반 주기, 시작 시 즉시 실행)
    scheduler.add_job(
        _run_dart_crawl,
        "interval",
        minutes=settings.DART_CRAWL_INTERVAL_MINUTES,
        id="dart_crawl",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),
    )
    # DART stale 감지 watchdog: 90분 간격, 서비스 시작 5분 후 첫 실행
    scheduler.add_job(
        _check_dart_health,
        "interval",
        minutes=90,
        id="dart_health_check",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(minutes=5),
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
        next_run_time=datetime.now(timezone.utc),
    )
    # SPEC-AI-087 REQ-007: 키워드 백필 — 1일 1회(외부 API/LLM 호출 없어 시총 업데이트보다
    # 낮은 빈도로 충분, DART/네이버 rate limit과 무관)
    scheduler.add_job(
        _run_keyword_backfill,
        "interval",
        hours=24,
        id="keyword_backfill",
        replace_existing=True,
    )
    # 데일리 브리핑 + 매수/매도 시그널 생성: 매일 08:30 KST (장 시작 전, 평일만)
    # SPEC-AI-015: 시장 레짐 사전 분류 (08:55 KST — 브리핑 5분 전)
    scheduler.add_job(
        _run_market_regime_update,
        "cron",
        day_of_week="mon-fri",
        hour=8,
        minute=55,
        timezone="Asia/Seoul",
        id="market_regime_update",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
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
        next_run_time=datetime.now(timezone.utc),
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

    # SPEC-AI-018 개선: 신규 종목 자동 등록 (평일 15:10 KST — 급등 시그널 생성 10분 전)
    scheduler.add_job(
        _run_auto_register_stocks,
        "cron",
        day_of_week="mon-fri",
        hour=15,
        minute=10,
        timezone="Asia/Seoul",
        id="auto_register_stocks",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    # SPEC-AI-051: 갭상승 런너 파이프라인 (평일 14:30 KST, 익일 갭상승 후보 사전 등록)
    scheduler.add_job(
        _run_gap_up_runner_detect,
        "cron",
        day_of_week="mon-fri",
        hour=14,
        minute=30,
        timezone="Asia/Seoul",
        id="surge_gap_up_runners",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    # SPEC-AI-051: 볼린저 밴드 스퀴즈 탐지 (평일 15:10 KST, 15:20 생성 직전)
    scheduler.add_job(
        _run_bollinger_squeeze_detect,
        "cron",
        day_of_week="mon-fri",
        hour=15,
        minute=10,
        timezone="Asia/Seoul",
        id="surge_bollinger_squeeze",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    # SPEC-AI-013: 급등예측 시그널 전일 생성 (평일 15:20 KST, 장 마감 10분 전)
    # 익일 급등 후보를 오늘 장 데이터 기반으로 사전 탐지.
    # surge_execute_buys(09:00)가 이 시그널을 읽어 익일 시가 매수를 수행한다.
    scheduler.add_job(
        _run_surge_signal_generate,
        "cron",
        day_of_week="mon-fri",
        hour=15,
        minute=20,
        timezone="Asia/Seoul",
        id="surge_signal_generate",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    # SPEC-AI-038 REQ-038-003: 장중 재탐지 (평일 10:00 KST)
    # BUY_CUTOFF(11:00) 1시간 전 장중 거래량·공시 데이터로 당일 신규 시그널 탐지.
    # 10:30 execute_buys 잡이 이 시그널을 읽어 당일 매수를 수행한다.
    scheduler.add_job(
        _run_surge_signal_generate,
        "cron",
        day_of_week="mon-fri",
        hour=10,
        minute=0,
        timezone="Asia/Seoul",
        id="surge_signal_generate_intraday",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    # @MX:NOTE: [AUTO] SPEC-AI-083 REQ-AI083-001/013 — 09:05~BUY_CUTOFF(11:00) 구간 장중
    #   고빈도 재스캔. 기존 10:00 단일 스캔이 장 초반(09:00~10:00)에 이미 실현된 급등을
    #   구조적으로 놓치던 사각지대를 다잡 확장으로 축소한다. 간격 근거: gather 1회 정상 소요
    #   12~15분(fund_manager.py:3106 부근)·최악 20분(_GATHER_TIMEOUT_S=1200, SPEC-AI-082)
    #   대비 ~20분 간격으로 배치해 max_instances=1 하에서 실행 겹침(misfire)을 방지한다
    #   (REQ-AI083-002/003). 진짜 분 단위 고빈도는 gather 순차 HTTP 재구조화 없이는 불가하며
    #   ([X-6] 후속), 본 스케줄은 gather 소요에 상한이 잡히는 현실적 재스캔이다. 콜백은 기존
    #   후보 생성 전용 _run_surge_signal_generate를 재사용한다 — 매수/청산 콜백을 신규
    #   참조하지 않는다(예측 기록 모드, REQ-AI083-010/[X-3]). 09:10은 사각지대 축소용 조기
    #   스캔(REQ-AI083-004), 10:55는 BUY_CUTOFF 직전 마지막 스캔이다.
    # @MX:SPEC: SPEC-AI-083 REQ-AI083-001
    for _intraday_hour, _intraday_minute in ((9, 10), (9, 35), (10, 30), (10, 55)):
        scheduler.add_job(
            _run_surge_signal_generate,
            "cron",
            day_of_week="mon-fri",
            hour=_intraday_hour,
            minute=_intraday_minute,
            timezone="Asia/Seoul",
            id=f"surge_signal_generate_intraday_{_intraday_hour:02d}{_intraday_minute:02d}",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
    # SPEC-AI-043: 포트폴리오 실행 비활성화 — 예측 기록 모드로 전환
    # surge_execute_buys, surge_check_exits, surge_force_max_holding_exit 잡 비활성화
    # (SurgePortfolio/SurgeTrade 데이터는 보존, 복구 가능)
    # scheduler.add_job(  # DISABLED by SPEC-AI-043
    #     _run_surge_execute_buys,
    #     "cron",
    #     day_of_week="mon-fri",
    #     hour="9-15",
    #     minute="0,30",
    #     timezone="Asia/Seoul",
    #     id="surge_execute_buys",
    #     max_instances=1,
    #     coalesce=True,
    #     replace_existing=True,
    # )
    # scheduler.add_job(  # DISABLED by SPEC-AI-043
    #     _run_surge_check_exits,
    #     "cron",
    #     day_of_week="mon-fri",
    #     hour="9-15",
    #     minute="*/5",
    #     timezone="Asia/Seoul",
    #     id="surge_check_exits",
    #     max_instances=1,
    #     coalesce=True,
    #     replace_existing=True,
    # )
    # scheduler.add_job(  # DISABLED by SPEC-AI-043
    #     _run_force_max_holding_exit,
    #     "cron",
    #     day_of_week="mon-fri",
    #     hour=6,         # 15:40 KST = 06:40 UTC
    #     minute=40,
    #     timezone="UTC",
    #     id="surge_force_max_holding_exit",
    #     max_instances=1,
    #     coalesce=True,
    #     replace_existing=True,
    # )

    # SPEC-AI-041: 급등예측 평가 파이프라인 (4단계, 장 마감 후 순차 실행)
    # 16:10 — 실제 급등주 결과 수집
    scheduler.add_job(
        _run_surge_collect_outcomes,
        "cron",
        day_of_week="mon-fri",
        hour=16,
        minute=10,
        timezone="Asia/Seoul",
        id="surge_collect_outcomes",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    # 18:30 — T-1 시그널 vs T 실제 결과 평가 (verify_signals 18:00 완료 후)
    scheduler.add_job(
        _run_surge_verify_predictions,
        "cron",
        day_of_week="mon-fri",
        hour=18,
        minute=30,
        timezone="Asia/Seoul",
        id="surge_verify_predictions",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    # 18:45 — SPEC-AI-069 REQ-001: backtest 운영 게이트 판정 (verify_predictions 18:30 이후,
    # auto_improve 19:00 이전 — 자동개선 재활성 시 최신 verdict를 참조할 수 있도록 선행 실행)
    scheduler.add_job(
        _run_surge_backtest_gate,
        "cron",
        day_of_week="mon-fri",
        hour=18,
        minute=45,
        timezone="Asia/Seoul",
        id="surge_backtest_gate",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    # 19:05 — SPEC-AI-070 REQ-001~004: 탐지기별 기여도 집계 + 은퇴 제안 리포트
    # (verify_predictions 18:30, backtest_gate 18:45, auto_improve 19:00 이후 실행 —
    # 자동개선 잡과 서로 독립적인 별도 측정·리포트 전용 잡이며 config를 쓰지 않는다)
    scheduler.add_job(
        _run_surge_detector_contribution,
        "cron",
        day_of_week="mon-fri",
        hour=19,
        minute=5,
        timezone="Asia/Seoul",
        id="surge_detector_contribution",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    # 19:15 — SPEC-AI-092 REQ-AI092-006: 급등평가 누락 감시 (verify_predictions 18:30,
    # backtest_gate 18:45, auto_improve 19:00, detector_contribution 19:05 이후 실행)
    scheduler.add_job(
        _run_surge_missing_evaluation_check,
        "cron",
        day_of_week="mon-fri",
        hour=19,
        minute=15,
        timezone="Asia/Seoul",
        id="surge_missing_evaluation_check",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    # 19:00 — 탐지기 가중치 자동 조정 (verify_signals 18:00 완료 후)
    scheduler.add_job(
        _run_surge_auto_improve,
        "cron",
        day_of_week="mon-fri",
        hour=19,
        minute=0,
        timezone="Asia/Seoul",
        id="surge_auto_improve",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    # 17:05 — 텔레그램 일일 리포트 발송
    scheduler.add_job(
        _run_surge_daily_report,
        "cron",
        day_of_week="mon-fri",
        hour=17,
        minute=5,
        timezone="Asia/Seoul",
        id="surge_daily_report",
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

    # SPEC-AI-042: 야간·장전 공시 기반 갭업 조기 포착 잡 (3개)
    # 17:00 KST — 장 마감 후 공시 스캔 (preday_disclosure 시그널 생성)
    scheduler.add_job(
        _run_surge_preday_scan,
        "cron",
        day_of_week="mon-fri",
        hour=17,
        minute=0,
        timezone="Asia/Seoul",
        id="surge_preday_scan",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    # 08:00 KST — 장전 워치리스트 갱신 (전날 17:00 이후 공시 재스캔)
    scheduler.add_job(
        _run_surge_preopen_refresh,
        "cron",
        day_of_week="mon-fri",
        hour=8,
        minute=0,
        timezone="Asia/Seoul",
        id="surge_preopen_refresh",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    # 09:05 KST — preday_disclosure 조기 진입 (id: surge_preday_early_entry ≠ fund_morning_execute)
    scheduler.add_job(
        _run_surge_preday_early_entry,
        "cron",
        day_of_week="mon-fri",
        hour=9,
        minute=5,
        timezone="Asia/Seoul",
        id="surge_preday_early_entry",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )

    # SPEC-AI-064: 코스피 대폭락 조기 경보 잡 3개
    # 06:30 KST — 미국 장마감 후 S&P 500 전일 종가 스캔 (그룹 D, 2.5시간 선행 경보)
    scheduler.add_job(
        _run_us_close_crash_scan,
        "cron",
        day_of_week="mon-fri",
        hour=6,
        minute=30,
        timezone="Asia/Seoul",
        id="crash_us_close_scan",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    # 08:30 KST — 장전 글로벌 선물·VIX·환율 + 코스피200 야간 선물 스캔 (그룹 A+E)
    scheduler.add_job(
        _run_premarket_crash_scan,
        "cron",
        day_of_week="mon-fri",
        hour=8,
        minute=30,
        timezone="Asia/Seoul",
        id="crash_premarket_scan",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    # 09:05 KST — 장중 코스피 낙폭 체크 (그룹 B)
    # 주의: fund_morning_execute(id="fund_morning_execute"), surge_preday_early_entry와
    # 동일 시각이나 id가 다르므로 replace_existing으로 기존 잡 덮어쓰지 않음.
    scheduler.add_job(
        _run_intraday_crash_check,
        "cron",
        day_of_week="mon-fri",
        hour=9,
        minute=5,
        timezone="Asia/Seoul",
        id="crash_intraday_check",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    # SPEC-AI-065 REQ-2: 스캔 유니버스 사전 빌드 (평일 16:00 KST, 장 마감 30분 후)
    scheduler.add_job(
        _run_surge_universe_build,
        "cron",
        day_of_week="mon-fri",
        hour=16,
        minute=0,
        timezone="Asia/Seoul",
        id="surge_universe_build",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )

    logger.info(
        f"Scheduler started: crawling every {interval} min, "
        f"KS200 daily scan at 15:30 KST, "
        f"DART every {settings.DART_CRAWL_INTERVAL_MINUTES} min, "
        f"market cap every {settings.MARKET_CAP_UPDATE_HOURS}h, "
        f"commodity price every 10 min, commodity news every 30 min, "
        f"briefing at 08:30 KST, surge_signal_generate at 15:20 KST, signal verify at 18:00 KST, "
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
        f"factor_weight_adapt on 1st of month 23:00 KST, "
        f"surge_preday_scan at 17:00 KST, surge_preopen_refresh at 08:00 KST, "
        f"surge_preday_early_entry at 09:05 KST"
    )


def stop_scheduler():
    """Stop the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
