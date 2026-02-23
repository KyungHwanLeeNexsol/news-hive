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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create tables and seed data
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_sectors(db)
        seed_all_stocks(db)
    finally:
        db.close()
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
from app.routers import sectors, stocks, news  # noqa: E402

app.include_router(sectors.router)
app.include_router(stocks.router)
app.include_router(news.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
