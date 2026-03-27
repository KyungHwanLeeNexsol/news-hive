from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class StockRelation(Base):
    """종목/섹터 간 방향성 관계 (경쟁사, 공급망, 고객사, 장비/소재 공급사).

    방향성: target에 뉴스가 생기면 source에게 전파한다.
    예: target=진성이엔씨, source=대창단조, type=competitor
        -> 진성이엔씨 뉴스 발생 시, 대창단조에게 반전 감성으로 전파
    """

    __tablename__ = "stock_relations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_stock_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("stocks.id", ondelete="CASCADE"), nullable=True
    )
    source_sector_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("sectors.id", ondelete="CASCADE"), nullable=True
    )
    target_stock_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("stocks.id", ondelete="CASCADE"), nullable=True
    )
    target_sector_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("sectors.id", ondelete="CASCADE"), nullable=True
    )
    # 'competitor' | 'supplier' | 'equipment' | 'material' | 'customer'
    relation_type: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    source_stock = relationship(
        "Stock", foreign_keys=[source_stock_id], lazy="select"
    )
    source_sector = relationship(
        "Sector", foreign_keys=[source_sector_id], lazy="select"
    )
    target_stock = relationship(
        "Stock", foreign_keys=[target_stock_id], lazy="select"
    )
    target_sector = relationship(
        "Sector", foreign_keys=[target_sector_id], lazy="select"
    )

    __table_args__ = (
        CheckConstraint(
            "source_stock_id IS NOT NULL OR source_sector_id IS NOT NULL",
            name="source_not_all_null",
        ),
        CheckConstraint(
            "target_stock_id IS NOT NULL OR target_sector_id IS NOT NULL",
            name="target_not_all_null",
        ),
        UniqueConstraint(
            "source_stock_id",
            "source_sector_id",
            "target_stock_id",
            "target_sector_id",
            "relation_type",
            name="uq_stock_relations_pair_type",
        ),
        Index("idx_stock_relations_target_stock", "target_stock_id"),
        Index("idx_stock_relations_target_sector", "target_sector_id"),
    )
