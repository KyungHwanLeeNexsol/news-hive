"""자기개선 루프 실행 이력 모델 — SPEC-AI-006."""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ImprovementLog(Base):
    """AI 자기개선 루프 실행 기록.

    action_type 값:
    - prompt_generation: 새 프롬프트 버전 자동 생성
    - ab_resolution: A/B 테스트 종료 (승격 또는 미결론)
    - weight_update: 팩터 가중치 자동 조정
    - failure_aggregation: 실패 패턴 집계 실행
    """
    __tablename__ = "improvement_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 실행된 작업 유형
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # 상세 내용 (JSON 문자열)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
