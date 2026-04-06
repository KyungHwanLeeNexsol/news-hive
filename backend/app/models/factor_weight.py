"""팩터 가중치 이력 모델 — SPEC-AI-006."""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FactorWeightHistory(Base):
    """AI 팩터 가중치 변경 이력.

    적중률 데이터를 기반으로 자동 조정된 팩터 가중치를 저장한다.
    is_active=True인 레코드 하나만 현재 활성 가중치로 사용된다.
    """
    __tablename__ = "factor_weight_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 팩터별 가중치 (합산 = 1.0, 각 값 범위: 0.10 ~ 0.40)
    news_sentiment: Mapped[float] = mapped_column(Float, nullable=False, default=0.25)
    technical: Mapped[float] = mapped_column(Float, nullable=False, default=0.25)
    supply_demand: Mapped[float] = mapped_column(Float, nullable=False, default=0.25)
    valuation: Mapped[float] = mapped_column(Float, nullable=False, default=0.25)

    # 피어슨 상관계수 JSON (factor -> correlation)
    correlations: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # 가중치 계산에 사용된 시그널 수
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 현재 활성 가중치 여부 (한 번에 하나만 True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
