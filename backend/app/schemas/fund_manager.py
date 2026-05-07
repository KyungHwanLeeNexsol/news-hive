from datetime import date, datetime
from typing import Optional

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
    ai_model: str | None = None
    # SPEC-AI-004: 공시 기반 시그널 유형
    signal_type: str | None = None
    # SPEC-AI-004: 연결된 공시 ID
    disclosure_id: int | None = None
    # 적중률 추적 필드
    price_at_signal: int | None = None
    price_after_1d: int | None = None
    price_after_3d: int | None = None
    price_after_5d: int | None = None
    is_correct: bool | None = None
    return_pct: float | None = None
    verified_at: datetime | None = None

    model_config = {"from_attributes": True}


class ConfidenceBucket(BaseModel):
    total: int
    accuracy: float


class AccuracyStatsResponse(BaseModel):
    total: int
    correct: int
    accuracy: float
    avg_return: float
    buy_accuracy: float
    sell_accuracy: float
    by_confidence: dict[str, ConfidenceBucket] = {}


class DailyBriefingResponse(BaseModel):
    id: int
    briefing_date: date
    market_overview: str
    sector_highlights: str | None = None
    stock_picks: str | None = None
    risk_assessment: str | None = None
    strategy: str | None = None
    created_at: datetime
    ai_model: str | None = None

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


# ---------------------------------------------------------------------------
# SPEC-AI-015: 시장 레짐 응답 스키마
# ---------------------------------------------------------------------------

class RegimeParamsResponse(BaseModel):
    """레짐별 투자 파라미터 응답."""
    min_action_confidence: float
    max_position_pct_high: float
    target_pct_max: float
    stop_loss_pct_default: float
    max_daily_trades: int


class MarketRegimeResponse(BaseModel):
    """시장 레짐 단건 응답."""
    date: date
    regime: str  # "BULL" / "BEAR" / "SIDEWAYS"
    kospi_5d_return: float
    kospi_20d_ma_position: float
    volatility_index: Optional[float] = None
    confidence_score: float
    params: RegimeParamsResponse

    model_config = {"from_attributes": True}


class MarketRegimeHistoryResponse(BaseModel):
    """시장 레짐 현재 + 히스토리 응답."""
    today: MarketRegimeResponse
    history: list[MarketRegimeResponse]
