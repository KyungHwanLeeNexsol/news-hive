from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DailyBriefing(Base):
    """AI 펀드매니저의 일일 시장 브리핑."""
    __tablename__ = "daily_briefings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    briefing_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    market_overview: Mapped[str] = mapped_column(Text, nullable=False)  # 시장 전체 요약
    sector_highlights: Mapped[str | None] = mapped_column(Text, nullable=True)  # 주요 섹터 동향
    stock_picks: Mapped[str | None] = mapped_column(Text, nullable=True)  # 오늘의 주목 종목
    risk_assessment: Mapped[str | None] = mapped_column(Text, nullable=True)  # 리스크 평가
    strategy: Mapped[str | None] = mapped_column(Text, nullable=True)  # 오늘의 전략
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
