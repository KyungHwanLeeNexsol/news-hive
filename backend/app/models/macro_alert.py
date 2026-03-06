from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MacroAlert(Base):
    """긴급 매크로 리스크 알림 — 뉴스 크롤링 시 리스크 키워드 빈도 기반 감지."""
    __tablename__ = "macro_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    level: Mapped[str] = mapped_column(String(10), nullable=False)  # 'warning' | 'critical'
    keyword: Mapped[str] = mapped_column(String(50), nullable=False)  # 감지된 리스크 키워드
    title: Mapped[str] = mapped_column(String(200), nullable=False)  # 알림 제목
    description: Mapped[str | None] = mapped_column(Text, nullable=True)  # 관련 뉴스 요약
    article_count: Mapped[int] = mapped_column(Integer, default=0)  # 감지된 뉴스 수
    is_active: Mapped[bool] = mapped_column(default=True)  # 아직 유효한 알림인지
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
