"""SPEC-AI-029: 적응형 급등 확률 임계값 히스토리 모델.

날짜별 산출된 임계값과 산출 근거(승률, 레짐, 사유)를 저장한다.
date 컬럼은 UNIQUE 제약으로 일자당 단일 레코드를 보장한다.
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Float, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SurgeThresholdHistory(Base):
    # @MX:NOTE: [AUTO] SPEC-AI-029 — 날짜별 적응형 임계값 이력. date UNIQUE 제약으로 upsert 패턴 적용
    # @MX:SPEC: SPEC-AI-029 REQ-AI029-004
    """날짜별 적응형 surge 임계값 이력 테이블."""

    __tablename__ = "surge_threshold_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 날짜 (KST 기준, UNIQUE — 일자당 하나의 레코드만 허용)
    date: Mapped[date] = mapped_column(Date, nullable=False, unique=True, index=True)
    # 산출된 적응형 임계값
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    # 직전 5거래 승률 (5개 미만이면 NULL)
    win_rate_5d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # 당일 시장 레짐 (BULL / BEAR / SIDEWAYS)
    regime: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # 임계값 산출 사유 (로그 및 디버깅용)
    reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    # 레코드 생성 시각
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
