from datetime import datetime

from pydantic import BaseModel


class SectorCreate(BaseModel):
    name: str


class StockInSector(BaseModel):
    id: int
    name: str
    stock_code: str
    keywords: list[str] | None = None
    change_rate: float | None = None
    news_count: int = 0

    model_config = {"from_attributes": True}


class SectorResponse(BaseModel):
    id: int
    name: str
    is_custom: bool
    created_at: datetime
    stock_count: int = 0
    naver_code: str | None = None
    change_rate: float | None = None
    total_stocks: int | None = None
    rising_stocks: int | None = None
    flat_stocks: int | None = None
    falling_stocks: int | None = None

    model_config = {"from_attributes": True}


class SectorDetailResponse(BaseModel):
    id: int
    name: str
    is_custom: bool
    created_at: datetime
    stocks: list[StockInSector] = []

    model_config = {"from_attributes": True}
