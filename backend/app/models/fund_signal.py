from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
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

    # 적중률 추적 필드
    price_at_signal: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 시그널 발행 시점 주가
    price_after_1d: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1일 후 주가
    price_after_3d: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 3일 후 주가
    price_after_5d: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 5일 후 주가
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # 시그널 방향 적중 여부
    return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)  # 5일 수익률 (%)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 검증 완료 시점

    # REQ-AI-003: 시그널 실패 원인 분류
    # 값: macro_shock, supply_reversal, earnings_miss, sector_contagion, technical_breakdown
    error_category: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # REQ-AI-005: 장중 빠른 검증
    price_after_6h: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 6시간 후 주가
    price_after_12h: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 12시간 후 주가
    early_warning: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # 손절가 이탈 경고

    # REQ-AI-006: 다중 팩터 스코어링
    factor_scores: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON: 4개 팩터 점수
    composite_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # 가중 합산 점수

    # REQ-AI-008: A/B 테스트
    prompt_version: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 프롬프트 버전

    stock = relationship("Stock")
