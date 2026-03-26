"""뉴스-가격 반응 추적 API 스키마."""

from datetime import datetime

from pydantic import BaseModel


class NewsPriceImpactItem(BaseModel):
    """개별 impact 레코드 응답."""
    id: int
    stock_id: int
    stock_name: str | None = None
    stock_code: str | None = None
    price_at_news: float
    price_after_1d: float | None = None
    return_1d_pct: float | None = None
    price_after_5d: float | None = None
    return_5d_pct: float | None = None
    captured_at: str | None = None
    backfill_1d_at: str | None = None
    backfill_5d_at: str | None = None


class NewsImpactResponse(BaseModel):
    """GET /api/news/{id}/impact 응답."""
    news_id: int
    impacts: list[NewsPriceImpactItem] = []


class StockNewsImpactStatsResponse(BaseModel):
    """GET /api/stocks/{id}/news-impact-stats 응답."""
    stock_id: int
    status: str  # "sufficient" | "insufficient"
    count: int = 0
    avg_1d: float | None = None
    avg_5d: float | None = None
    win_rate_1d: float | None = None
    win_rate_5d: float | None = None
    max_return_5d: float | None = None
    min_return_5d: float | None = None
