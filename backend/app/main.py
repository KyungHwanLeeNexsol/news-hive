from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.database import SessionLocal, engine, Base  # noqa: F401
from app.models import Sector, Stock, NewsArticle, NewsStockRelation  # noqa: F401
from app.models.sector_insight import SectorInsight  # noqa: F401
from app.models.disclosure import Disclosure  # noqa: F401
from app.models.macro_alert import MacroAlert  # noqa: F401
from app.models.economic_event import EconomicEvent  # noqa: F401
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
        except Exception as e:
            _logger.warning(f"Seed error: {e}")
        finally:
            db.close()
        _logger.info("Seed complete")

    threading.Thread(target=_run_seed, daemon=True).start()

    start_scheduler()
    yield
    # Shutdown
    stop_scheduler()


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
from app.routers import sectors, stocks, news, disclosures, alerts, events, fund_manager, auth  # noqa: E402

app.include_router(sectors.router)
app.include_router(stocks.router)
app.include_router(news.router)
app.include_router(disclosures.router)
app.include_router(alerts.router)
app.include_router(events.router)
app.include_router(fund_manager.router)
app.include_router(auth.router)


@app.api_route("/api/health", methods=["GET", "HEAD"])
async def health():
    return {"status": "ok"}


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
