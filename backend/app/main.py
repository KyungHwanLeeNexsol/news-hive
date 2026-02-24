from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import SessionLocal, engine, Base
from app.models import Sector, Stock, NewsArticle, NewsStockRelation  # noqa: F401
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
    # Startup: run migrations, create tables, and seed data
    _run_migrations()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_sectors(db)
        seed_all_stocks(db)
        _backfill_sentiment(db)
    finally:
        db.close()
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
from app.routers import sectors, stocks, news  # noqa: E402

app.include_router(sectors.router)
app.include_router(stocks.router)
app.include_router(news.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
