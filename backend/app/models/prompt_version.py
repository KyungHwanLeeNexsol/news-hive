"""프롬프트 버전 및 A/B 테스트 결과 모델."""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PromptVersion(Base):
    """AI 프롬프트 버전 관리."""
    __tablename__ = "prompt_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version_name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)  # 변경 사항 설명
    template_key: Mapped[str] = mapped_column(String(50), nullable=False)  # briefing / signal
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_control: Mapped[bool] = mapped_column(Boolean, default=False)  # A/B 테스트 대조군

    # SPEC-AI-006: AI 자동 생성 프롬프트 내용
    prompt_template: Mapped[str | None] = mapped_column(Text, nullable=True)  # 실제 프롬프트 텍스트
    generation_source: Mapped[str | None] = mapped_column(Text, nullable=True)  # 생성 근거 (JSON)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PromptABResult(Base):
    """A/B 테스트 비교 결과."""
    __tablename__ = "prompt_ab_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version_a: Mapped[str] = mapped_column(String(50), nullable=False)  # 대조군
    version_b: Mapped[str] = mapped_column(String(50), nullable=False)  # 실험군
    total_trials: Mapped[int] = mapped_column(Integer, default=0)
    accuracy_a: Mapped[float | None] = mapped_column(Float, nullable=True)
    accuracy_b: Mapped[float | None] = mapped_column(Float, nullable=True)
    p_value: Mapped[float | None] = mapped_column(Float, nullable=True)  # z-test p-value
    winner: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
