"""SPEC-AI-116: missing trigger detector shadow candidates."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SurgeMissingTriggerShadowCandidate(Base):
    """Shadow-only candidate emitted by a missing-trigger detector family."""

    __tablename__ = "surge_missing_trigger_shadow_candidates"

    trading_date: Mapped[date] = mapped_column(Date, primary_key=True, nullable=False)
    stock_code: Mapped[str] = mapped_column(String(10), primary_key=True, nullable=False)
    detector_family: Mapped[str] = mapped_column(
        String(40), primary_key=True, nullable=False
    )
    horizon: Mapped[str] = mapped_column(String(20), primary_key=True, nullable=False)
    stock_name: Mapped[str] = mapped_column(String(100), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    source_pool: Mapped[str] = mapped_column(String(60), nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False)
    risk_tags_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
