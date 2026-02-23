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
    keywords: list[str] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
