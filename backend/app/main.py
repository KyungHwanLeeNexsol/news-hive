from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.database import SessionLocal, engine, Base  # noqa: F401
from app.models import Sector, Stock, NewsArticle, NewsStockRelation  # noqa: F401
from app.models import Commodity, CommodityPrice, SectorCommodityRelation  # noqa: F401
from app.models.sector_insight import SectorInsight  # noqa: F401
from app.models.disclosure import Disclosure  # noqa: F401
from app.models.vip_trading import VIPDisclosure, VIPPortfolio, VIPTrade  # noqa: F401
from app.models.ks200_trading import KS200Portfolio, KS200Trade, KS200Signal  # noqa: F401
from app.models.macro_alert import MacroAlert  # noqa: F401
from app.models.economic_event import EconomicEvent  # noqa: F401
from app.seed.sectors import seed_sectors
from app.seed.stocks import seed_all_stocks
from app.services.scheduler import start_scheduler, stop_scheduler

import logging

# 구조화된 JSON 로깅 설정 (기존 로그 출력과 병행)
try:
    from pythonjsonlogger.json import JsonFormatter as _JsonFormatter

    _json_handler = logging.StreamHandler()
    _json_formatter = _JsonFormatter(
        "%(asctime)s %(name)s %(levelname)s %(message)s",
        rename_fields={"asctime": "timestamp", "levelname": "level"},
    )
    _json_handler.setFormatter(_json_formatter)
    logging.root.handlers = [_json_handler]
    logging.root.setLevel(logging.INFO)
except ImportError:
    # python-json-logger 미설치 시 기본 로깅 유지
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



@asynccontextmanager
async def lifespan(app: FastAPI):
    import threading

    # Startup: run migrations synchronously (fast, required before serving)
    _run_migrations()

    # Seed sectors + stocks in background (lightweight JSON read)
    def _run_seed():
        _logger = logging.getLogger(__name__)
        db = SessionLocal()
        try:
            seed_sectors(db)
            seed_all_stocks(db)
            from app.seed.economic_events import seed_economic_events
            seed_economic_events(db)
            from app.seed.commodities import seed_commodities, seed_sector_commodity_relations
            seed_commodities(db)
            seed_sector_commodity_relations(db)
        except Exception as e:
            _logger.warning(f"Seed error: {e}")
        finally:
            db.close()
        _logger.info("Seed complete")

        # 시드 완료 직후 원자재 가격 즉시 수집
        # (스케줄러의 첫 실행이 시드 완료 전에 동작하면 새 심볼을 놓칠 수 있음)
        try:
            from app.services.commodity_service import fetch_commodity_prices
            db2 = SessionLocal()
            try:
                count = fetch_commodity_prices(db2)
                _logger.info(f"시드 후 즉시 원자재 가격 수집: {count}개")
            finally:
                db2.close()
        except Exception as e:
            _logger.warning(f"시드 후 원자재 가격 수집 실패: {e}")

    threading.Thread(target=_run_seed, daemon=True).start()

    # 종목/섹터 관계 AI 추론 (stock_relations 테이블이 비어있을 때만 실행)
    def _run_relation_inference():
        import asyncio as _aio
        _logger = logging.getLogger(__name__)
        db = SessionLocal()
        try:
            from app.services.stock_relation_service import should_run_inference, run_full_inference
            if should_run_inference(db):
                _logger.info("stock_relations 비어있음 - AI 관계 추론 시작")
                stats = _aio.run(run_full_inference(db))
                _logger.info(f"관계 추론 완료: 섹터 간 {stats['inter_sector']}건, 섹터 내 {stats['intra_sector']}건")
            else:
                _logger.info("stock_relations에 데이터 존재 - 초기 추론 스킵")
        except Exception as e:
            _logger.warning(f"관계 추론 실패: {e}")
        finally:
            db.close()

    threading.Thread(target=_run_relation_inference, daemon=True).start()

    # WebSocket ConnectionManager 초기화
    from app.websocket import ConnectionManager as WSManager
    from app import websocket as ws_module
    from app.event_bus import set_event_bus, clear_event_bus

    ws_manager = WSManager()
    ws_module.manager = ws_manager
    set_event_bus(ws_manager)

    start_scheduler()
    yield
    # Shutdown
    stop_scheduler()
    clear_event_bus()
    ws_module.manager = None
    # Redis 연결 종료
    try:
        from app.cache import close_redis
        await close_redis()
    except Exception:
        pass


app = FastAPI(title="Stock News Tracker API", lifespan=lifespan)

# Prometheus 메트릭 자동 수집 (전체 라우트 자동 계측)
try:
    from prometheus_fastapi_instrumentator import Instrumentator
    Instrumentator().instrument(app).expose(app, endpoint="/metrics")
except ImportError:
    logging.getLogger(__name__).info(
        "prometheus-fastapi-instrumentator 미설치 - /metrics 비활성화"
    )

from app.config import settings as app_settings  # noqa: E402

app.add_middleware(
    CORSMiddleware,
    allow_origins=[app_settings.FRONTEND_URL, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate Limiter 미들웨어 (Redis 미사용 시 자동 비활성화)
from app.middleware.rate_limiter import RateLimiterMiddleware  # noqa: E402
app.add_middleware(RateLimiterMiddleware)

# Import and register routers
from app.routers import sectors, stocks, news, disclosures, alerts, events, auth, commodities, paper_trading, chat  # noqa: E402
from app.routers import user as user_router, push as push_router  # noqa: E402
from app.routers import following as following_router  # noqa: E402
from app.routers import macro_rates as macro_rates_router  # noqa: E402
from app.routers.vip_trading import router as vip_trading_router  # noqa: E402
from app.routers.ks200_trading import router as ks200_trading_router  # noqa: E402
from app.routers.trading_overview import router as trading_overview_router  # noqa: E402

app.include_router(sectors.router)
app.include_router(stocks.router)
app.include_router(news.router)
app.include_router(disclosures.router)
app.include_router(alerts.router)
app.include_router(events.router)
app.include_router(auth.router)
app.include_router(commodities.router)
app.include_router(commodities.sector_commodity_router)
app.include_router(paper_trading.router)
app.include_router(chat.router)
app.include_router(user_router.router)
app.include_router(push_router.router)
app.include_router(following_router.router)
app.include_router(macro_rates_router.router)
app.include_router(vip_trading_router)
app.include_router(ks200_trading_router)
app.include_router(trading_overview_router)

# WebSocket 엔드포인트 등록
from app.websocket import router as ws_router  # noqa: E402
app.include_router(ws_router)


@app.api_route("/api/health", methods=["GET", "HEAD"])
async def health():
    return {"status": "ok"}


@app.get("/api/health/scheduler")
def scheduler_health():
    """스케줄러 작업 상태 반환: id, next_run_time, is_overdue."""
    from app.services.scheduler import scheduler
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    jobs = []
    for job in scheduler.get_jobs():
        next_run = job.next_run_time
        is_overdue = False
        next_run_str = None
        if next_run is not None:
            next_run_str = next_run.isoformat()
            is_overdue = next_run < now
        jobs.append({
            "id": job.id,
            "next_run_time": next_run_str,
            "is_overdue": is_overdue,
        })
    return {
        "scheduler_running": scheduler.running,
        "job_count": len(jobs),
        "jobs": jobs,
    }


@app.get("/api/admin/cache/stats")
async def cache_stats():
    """캐시 적중/미스 통계 반환."""
    from app.cache import get_cache_stats, get_redis
    stats = get_cache_stats()
    r = await get_redis()
    stats["redis_connected"] = r is not None
    return stats


@app.delete("/api/admin/cache")
async def flush_cache(namespace: str = ""):
    """캐시 초기화. namespace 지정 시 해당 패턴만 삭제, 미지정 시 전체 삭제."""
    from app.cache import cache_delete, get_redis
    r = await get_redis()
    if r is None:
        return {"deleted": 0, "message": "Redis 미연결 - 인메모리 캐시만 초기화"}

    pattern = f"{namespace}*" if namespace else "*"
    deleted = await cache_delete(pattern)
    return {"deleted": deleted, "pattern": pattern}


@app.post("/api/deploy")
async def deploy_webhook(request: Request):
    """GitHub webhook → auto deploy. Validates HMAC-SHA256 signature."""
    import hashlib
    import hmac
    import subprocess

    secret = app_settings.DEPLOY_SECRET
    if not secret:
        return JSONResponse({"error": "DEPLOY_SECRET not configured"}, status_code=500)

    body = await request.body()
    sig_header = request.headers.get("X-Hub-Signature-256", "")
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(sig_header, expected):
        return JSONResponse({"error": "invalid signature"}, status_code=403)

    # Run deploy in background
    subprocess.Popen(
        ["/bin/bash", "/home/ubuntu/news-hive/deploy.sh"],
        cwd="/home/ubuntu/news-hive",
        stdout=open("/tmp/deploy.log", "w"),
        stderr=subprocess.STDOUT,
    )
    return {"status": "deploy triggered"}


@app.get("/api/market-status")
async def market_status():
    from app.services.naver_finance import _is_market_open
    is_open = _is_market_open()
    return {"market_open": is_open, "refresh_interval": 10 if is_open else 0}
