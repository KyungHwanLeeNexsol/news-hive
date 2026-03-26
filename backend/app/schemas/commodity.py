from datetime import datetime

from pydantic import BaseModel


# --- 원자재 기본 정보 ---

class CommodityBase(BaseModel):
    symbol: str
    name_ko: str
    name_en: str
    category: str
    unit: str
    currency: str = "USD"


class CommodityResponse(CommodityBase):
    """원자재 목록 응답 (최신 가격 포함)."""
    id: int
    created_at: datetime
    latest_price: float | None = None
    change_pct: float | None = None

    model_config = {"from_attributes": True}


# --- 가격 데이터 ---

class CommodityPriceResponse(BaseModel):
    """단일 가격 레코드."""
    price: float
    change_pct: float | None = None
    open_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    volume: int | None = None
    recorded_at: datetime
    source: str = "yfinance"

    model_config = {"from_attributes": True}


class CommodityHistoryResponse(BaseModel):
    """원자재 과거 가격 히스토리 (OHLCV)."""
    date: str
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: int | None = None


# --- 섹터-원자재 관계 ---

class SectorCommodityResponse(BaseModel):
    """섹터별 관련 원자재 응답."""
    id: int
    commodity_id: int
    symbol: str
    name_ko: str
    name_en: str
    category: str
    correlation_type: str
    description: str | None = None
    latest_price: float | None = None
    change_pct: float | None = None

    model_config = {"from_attributes": True}


class CommodityRefreshResponse(BaseModel):
    """수동 가격 수집 결과."""
    updated_count: int
    message: str
