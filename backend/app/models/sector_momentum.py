"""섹터 모멘텀 모델.

SPEC-AI-002 REQ-AI-016: 섹터별 자금 흐름 추적.
섹터별 일간 등락률과 거래대금 변화율을 저장하고,
5일 평균 기반 모멘텀 태그와 자금 유입 여부를 기록한다.
"""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SectorMomentum(Base):
    """섹터별 일간 모멘텀 데이터."""
    __tablename__ = "sector_momentum"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sector_id: Mapped[int] = mapped_column(Integer, ForeignKey("sectors.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)

    # 당일 등락률 (%)
    daily_return: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # 5일 평균 등락률 (%) — 데이터 충분 시 계산
    avg_return_5d: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 5일 거래대금 변화율 (%) — 현재 네이버 데이터에 거래대금 없으므로
    # 상승/하락 종목 비율 변화로 대체
    volume_change_5d: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 모멘텀 태그: "momentum_sector" | None
    momentum_tag: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # 자금 유입 감지 여부
    capital_inflow: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    sector = relationship("Sector")
