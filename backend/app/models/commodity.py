from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Commodity(Base):
    """원자재 마스터 테이블 (WTI, 금, 구리 등)."""
    __tablename__ = "commodities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)  # CL=F, GC=F
    name_ko: Mapped[str] = mapped_column(String(50), nullable=False)  # WTI 원유
    name_en: Mapped[str] = mapped_column(String(50), nullable=False)  # WTI Crude Oil
    category: Mapped[str] = mapped_column(String(20), nullable=False)  # energy/metal/agriculture
    unit: Mapped[str] = mapped_column(String(20), nullable=False)  # barrel/oz/lb/bushel
    currency: Mapped[str] = mapped_column(String(5), default="USD")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    prices = relationship("CommodityPrice", back_populates="commodity", cascade="all, delete-orphan")
    sector_relations = relationship("SectorCommodityRelation", back_populates="commodity")


class CommodityPrice(Base):
    """원자재 가격 히스토리 (yfinance로 수집)."""
    __tablename__ = "commodity_prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    commodity_id: Mapped[int] = mapped_column(Integer, ForeignKey("commodities.id"), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    open_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    high_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    low_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    source: Mapped[str] = mapped_column(String(20), default="yfinance")

    commodity = relationship("Commodity", back_populates="prices")


class SectorCommodityRelation(Base):
    """섹터-원자재 상관관계 매핑 (예: 에너지 섹터 ↔ WTI 원유)."""
    __tablename__ = "sector_commodity_relations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sector_id: Mapped[int] = mapped_column(Integer, ForeignKey("sectors.id"), nullable=False)
    commodity_id: Mapped[int] = mapped_column(Integer, ForeignKey("commodities.id"), nullable=False)
    correlation_type: Mapped[str] = mapped_column(String(20), nullable=False)  # positive/negative/neutral
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    sector = relationship("Sector")
    commodity = relationship("Commodity", back_populates="sector_relations")
