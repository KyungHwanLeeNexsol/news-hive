"""SPEC-AI-022: 테마 그룹 모델 — 그룹주 전파 시그널을 위한 종목 묶음 관리."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ThemeGroup(Base):
    """테마 그룹 — LG그룹, 삼성그룹 등 동일 재료로 움직이는 종목 묶음."""

    __tablename__ = "theme_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 그룹명 (유니크): "LG그룹", "삼성그룹" 등
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    # 앵커 종목 (테마 점수가 이 종목을 기준으로 전파됨)
    anchor_stock_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("stocks.id", ondelete="SET NULL"), nullable=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # @MX:ANCHOR: [AUTO] theme_groups → stock_theme_groups 관계 — propagate_theme_group_signals에서 사용
    # @MX:REASON: 테마 전파 시 그룹 내 전체 종목 조회에 사용되는 핵심 관계. fan_in >= 3 예상
    stocks = relationship(
        "Stock",
        secondary="stock_theme_groups",
        back_populates="theme_groups",
    )
    anchor_stock = relationship(
        "Stock",
        foreign_keys=[anchor_stock_id],
    )


class StockThemeGroup(Base):
    """종목-테마그룹 연결 테이블."""

    __tablename__ = "stock_theme_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False
    )
    theme_group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("theme_groups.id", ondelete="CASCADE"), nullable=False
    )
    # 그룹 내 가중치 (현재 기본값 1.0, 향후 앵커 기여도 차등 적용 가능)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("stock_id", "theme_group_id", name="uq_stock_theme_group"),
    )
