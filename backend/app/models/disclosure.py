from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Disclosure(Base):
    __tablename__ = "disclosures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    corp_code: Mapped[str] = mapped_column(String(8), nullable=False)
    corp_name: Mapped[str] = mapped_column(String(100), nullable=False)
    stock_code: Mapped[str | None] = mapped_column(String(6), nullable=True)
    stock_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("stocks.id"), nullable=True)
    report_name: Mapped[str] = mapped_column(String(500), nullable=False)
    report_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    rcept_no: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    rcept_dt: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYYMMDD
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # SPEC-AI-004: 공시 충격 스코어링 필드
    impact_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reflected_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    unreflected_gap: Mapped[float | None] = mapped_column(Float, nullable=True)
    ripple_checked: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    disclosed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    stock = relationship("Stock", backref="disclosures")
