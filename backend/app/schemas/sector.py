from datetime import datetime

from pydantic import BaseModel


class SectorCreate(BaseModel):
    name: str


class StockInSector(BaseModel):
    id: int
    name: str
    stock_code: str
    keywords: list[str] | None = None

    model_config = {"from_attributes": True}


class SectorResponse(BaseModel):
    id: int
    name: str
    is_custom: bool
    created_at: datetime
    stock_count: int = 0

    model_config = {"from_attributes": True}


class SectorDetailResponse(BaseModel):
    id: int
    name: str
    is_custom: bool
    created_at: datetime
    stocks: list[StockInSector] = []

    model_config = {"from_attributes": True}
