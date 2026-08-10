"""SPEC-AI-115: surge gate/drop attribution observations."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SurgeGateDropObservation(Base):
    """Observation row for candidates dropped by surge prediction gates."""

    __tablename__ = "surge_gate_drop_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trading_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    stock_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    gate_name: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    detector_set_json: Mapped[str] = mapped_column(Text, nullable=False)
    score_before_drop: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reason_metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    market_regime: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    shadow_profile: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)
    shadow_candidate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
