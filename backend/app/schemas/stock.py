from datetime import datetime

from pydantic import BaseModel


class StockCreate(BaseModel):
    name: str
    stock_code: str
    keywords: list[str] | None = None


class StockResponse(BaseModel):
    id: int
    sector_id: int
    name: str
    stock_code: str
    market: str | None = None
    keywords: list[str] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class StockListItem(BaseModel):
    id: int
    name: str
    stock_code: str
    sector_id: int
    sector_name: str | None = None
    market: str | None = None
    current_price: int | None = None
    price_change: int | None = None
    change_rate: float | None = None
    bid_price: int | None = None
    ask_price: int | None = None
    volume: int | None = None
    trading_value: int | None = None
    prev_volume: int | None = None
    news_count: int = 0


class StockDetailResponse(BaseModel):
    id: int
    name: str
    stock_code: str
    sector_id: int
    sector_name: str | None = None
    # Realtime fundamentals
    current_price: int | None = None
    price_change: int | None = None
    change_rate: float | None = None
    eps: int | None = None
    bps: int | None = None
    dividend: int | None = None
    high_52w: int | None = None
    low_52w: int | None = None
    volume: int | None = None
    trading_value: int | None = None
    # Valuation
    per: float | None = None
    pbr: float | None = None
    market_cap: int | None = None           # 억원
    dividend_yield: float | None = None     # %
    foreign_ratio: float | None = None      # %
    industry_per: float | None = None


class PriceRecordResponse(BaseModel):
    date: str
    close: int
    open: int
    high: int
    low: int
    volume: int


class FinancialPeriodResponse(BaseModel):
    period: str
    period_type: str
    revenue: int | None = None
    operating_profit: int | None = None
    operating_margin: float | None = None
    net_income: int | None = None
    eps: int | None = None
    bps: int | None = None
    roe: float | None = None
    dividend_payout: float | None = None


class FinancialsResponse(BaseModel):
    annual: list[FinancialPeriodResponse] = []
    quarter: list[FinancialPeriodResponse] = []
