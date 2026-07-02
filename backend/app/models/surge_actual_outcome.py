"""SPEC-AI-041: 일별 실제 급등주 결과 모델.

장 마감 후 당일 실제 급등한 종목(change_rate >= 10.0)을 저장한다.
composite PK: (trading_date, stock_code)
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SurgeActualOutcome(Base):
    # @MX:NOTE: [AUTO] SPEC-AI-041 — 장 마감 후 실제 급등주 결과. composite PK로 일자+종목 upsert 보장
    # @MX:SPEC: SPEC-AI-041 REQ-AI041-001
    # @MX:NOTE: [AUTO] SPEC-AI-068 — surge_type 컬럼 추가. T-1 스캔 유니버스 포함 여부로
    # scannable(선행형, 공식 예측 목표)/non_scannable(당일 촉매형, 실시간 조기탐지 트랙 경계 —
    # 별도 후속 SPEC 범위, 본 SPEC은 라벨링까지만) 라벨링. evaluate_surge_predictions가 평가 시 UPDATE.
    # @MX:SPEC: SPEC-AI-068 REQ-AI068-005
    """일별 실제 급등주 결과 테이블 (T당일 상승률 기록)."""

    __tablename__ = "surge_actual_outcome"

    # composite PK: (trading_date, stock_code)
    trading_date: Mapped[date] = mapped_column(Date, primary_key=True, nullable=False)
    stock_code: Mapped[str] = mapped_column(String(10), primary_key=True, nullable=False)

    stock_name: Mapped[str] = mapped_column(String(50), nullable=False)
    # 당일 종가 기준 등락률 (%)
    change_rate: Mapped[float] = mapped_column(Float, nullable=False)
    # change_rate >= 10.0 이면 True
    was_surge: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # 고가 기준 등락률 (조회 불가 시 None)
    high_change_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # KOSPI 또는 KOSDAQ
    market: Mapped[str] = mapped_column(String(10), nullable=False)
    # SPEC-AI-068 REQ-005: T-1 스캔 유니버스 포함 여부 라벨. scannable / non_scannable.
    # 평가 잡 실행 전(또는 유니버스 미영속화 과거 날짜)에는 None으로 남는다.
    surge_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # 레코드 생성 시각
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
