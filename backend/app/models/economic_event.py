from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EconomicEvent(Base):
    """글로벌 이벤트 캘린더 — 주요 경제/지정학 이벤트."""
    __tablename__ = "economic_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)  # 'fomc' | 'options_expiry' | 'geopolitical' | 'earnings' | 'economic_data' | 'custom'
    importance: Mapped[str] = mapped_column(String(10), default="medium")  # 'low' | 'medium' | 'high'
    country: Mapped[str] = mapped_column(String(10), default="KR")  # 'KR' | 'US' | 'CN' | 'JP' | 'GLOBAL'
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
