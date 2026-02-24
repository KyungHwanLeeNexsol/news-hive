from datetime import datetime

from pydantic import BaseModel


class NewsRelationResponse(BaseModel):
    stock_id: int | None = None
    stock_name: str | None = None
    sector_id: int | None = None
    sector_name: str | None = None
    match_type: str
    relevance: str

    model_config = {"from_attributes": True}


class NewsArticleResponse(BaseModel):
    id: int
    title: str
    summary: str | None = None
    ai_summary: str | None = None
    url: str
    source: str
    sentiment: str | None = None
    published_at: datetime | None = None
    collected_at: datetime
    relations: list[NewsRelationResponse] = []

    model_config = {"from_attributes": True}
