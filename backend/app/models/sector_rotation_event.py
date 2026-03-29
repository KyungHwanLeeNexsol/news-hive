"""섹터 로테이션 이벤트 모델.

SPEC-AI-002 REQ-AI-017: 섹터 로테이션 패턴 인식.
이전 모멘텀 섹터에서 새 모멘텀 섹터로의 전환을 감지하고 기록한다.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SectorRotationEvent(Base):
    """섹터 로테이션 감지 이벤트."""
    __tablename__ = "sector_rotation_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 이전 모멘텀 섹터
    from_sector_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sectors.id"), nullable=False
    )

    # 새 모멘텀 섹터
    to_sector_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sectors.id"), nullable=False
    )

    # 감지 시점
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # 로테이션 신뢰도 (0.0 ~ 1.0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)

    from_sector = relationship("Sector", foreign_keys=[from_sector_id])
    to_sector = relationship("Sector", foreign_keys=[to_sector_id])
