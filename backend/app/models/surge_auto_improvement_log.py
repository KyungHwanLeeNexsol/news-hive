"""SPEC-AI-041: 급등예측 자동 파라미터 개선 이력 모델.

평가 결과를 기반으로 적용된 파라미터 변경 이력을 저장한다.
parameter_path는 점 표기법 경로 (예: "ensemble.weights.theme_cluster").
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SurgeAutoImprovementLog(Base):
    # @MX:NOTE: [AUTO] SPEC-AI-041 — 자동 파라미터 개선 이력. parameter_path는 dot notation 경로
    # @MX:SPEC: SPEC-AI-041 REQ-AI041-003
    """급등예측 자동 파라미터 개선 이력 테이블."""

    __tablename__ = "surge_auto_improvement_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 파라미터 변경 적용 시각
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # 이 개선이 근거로 삼은 평가 날짜
    evaluation_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # 변경된 파라미터 경로 (예: "ensemble.weights.theme_cluster")
    parameter_path: Mapped[str] = mapped_column(String(100), nullable=False)
    # 변경 전 값
    old_value: Mapped[float] = mapped_column(Float, nullable=False)
    # 변경 후 값
    new_value: Mapped[float] = mapped_column(Float, nullable=False)
    # 변경 사유 (LLM 분석 결과 또는 rule-based 설명)
    rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 평가에 사용된 롤링 윈도우 일수
    rolling_window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
