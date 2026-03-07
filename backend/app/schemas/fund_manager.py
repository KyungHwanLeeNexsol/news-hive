from datetime import date, datetime

from pydantic import BaseModel


class FundSignalResponse(BaseModel):
    id: int
    stock_id: int
    stock_name: str | None = None
    stock_code: str | None = None
    sector_name: str | None = None
    signal: str
    confidence: float
    target_price: int | None = None
    stop_loss: int | None = None
    reasoning: str
    news_summary: str | None = None
    financial_summary: str | None = None
    market_summary: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DailyBriefingResponse(BaseModel):
    id: int
    briefing_date: date
    market_overview: str
    sector_highlights: str | None = None
    stock_picks: str | None = None
    risk_assessment: str | None = None
    strategy: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PortfolioReportResponse(BaseModel):
    id: int
    stock_ids: str
    overall_assessment: str
    risk_analysis: str | None = None
    sector_balance: str | None = None
    rebalancing: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AnalyzeRequest(BaseModel):
    stock_ids: list[int] | None = None
