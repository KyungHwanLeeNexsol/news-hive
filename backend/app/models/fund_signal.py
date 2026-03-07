from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class FundSignal(Base):
    """AI 펀드매니저의 종목별 투자 시그널."""
    __tablename__ = "fund_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(Integer, ForeignKey("stocks.id"), nullable=False)
    signal: Mapped[str] = mapped_column(String(10), nullable=False)  # 'buy' | 'sell' | 'hold'
    confidence: Mapped[float] = mapped_column(Float, nullable=False)  # 0.0 ~ 1.0
    target_price: Mapped[int | None] = mapped_column(Integer, nullable=True)  # AI 추정 목표가
    stop_loss: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 손절가
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)  # AI 분석 근거
    news_summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # 관련 뉴스 요약
    financial_summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # 재무 데이터 요약
    market_summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # 시세 데이터 요약
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    stock = relationship("Stock")
