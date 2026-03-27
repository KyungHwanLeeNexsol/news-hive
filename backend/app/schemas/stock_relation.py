"""종목/섹터 관계 Pydantic 스키마."""

from datetime import datetime

from pydantic import BaseModel


class StockRelationResponse(BaseModel):
    """종목/섹터 관계 응답 스키마."""
    id: int
    source_stock_id: int | None = None
    source_stock_name: str | None = None
    source_sector_id: int | None = None
    source_sector_name: str | None = None
    target_stock_id: int | None = None
    target_stock_name: str | None = None
    target_sector_id: int | None = None
    target_sector_name: str | None = None
    relation_type: str
    confidence: float
    reason: str | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class StockRelationListResponse(BaseModel):
    """관계 목록 응답 (페이지네이션 포함)."""
    relations: list[StockRelationResponse]
    total: int


class InferRelationsResponse(BaseModel):
    """관계 추론 실행 결과 응답."""
    inter_sector: int
    intra_sector: int
    message: str
