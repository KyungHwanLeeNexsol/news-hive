from datetime import datetime

from sqlalchemy import DateTime, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PortfolioReport(Base):
    """AI 펀드매니저의 포트폴리오 분석 리포트."""
    __tablename__ = "portfolio_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_ids: Mapped[str] = mapped_column(Text, nullable=False)  # comma-separated stock IDs
    overall_assessment: Mapped[str] = mapped_column(Text, nullable=False)  # 종합 평가
    risk_analysis: Mapped[str | None] = mapped_column(Text, nullable=True)  # 리스크 분석
    sector_balance: Mapped[str | None] = mapped_column(Text, nullable=True)  # 섹터 분산 분석
    rebalancing: Mapped[str | None] = mapped_column(Text, nullable=True)  # 리밸런싱 제안
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
