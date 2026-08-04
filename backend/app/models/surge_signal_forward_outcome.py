"""SPEC-AI-101: 신호가 기준 EOD(장마감) 최대수익률 근사 테이블.

신호 발행가(FundSignal.price_at_signal) 대비 그날 고점까지의 실현 가능 수익률을
신호(fund_signal_id) 단위로 저장한다. SurgeActualOutcome은 (trading_date, stock_code)
단위라 동일 종목·동일 날짜의 복수 신호(T-1 배치 + 장중 재스캔, SPEC-AI-083)를 구분할
수 없어 신규 additive 테이블로 신설한다(D1, design.md §B.2). 기존 SurgeActualOutcome
스키마(컬럼)는 무수정이다.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SurgeSignalForwardOutcome(Base):
    # @MX:NOTE: [AUTO] SPEC-AI-101 — 신호 단위(fund_signal_id) EOD 최대수익률 근사.
    # day_high_price = prev_close_price × (1 + high_change_rate/100)
    # forward_max_return_pct = (day_high_price − price_at_signal) / price_at_signal × 100
    # (trading_date, fund_signal_id) UNIQUE로 평가 잡 재실행 시 upsert 멱등성 보장.
    # @MX:SPEC: SPEC-AI-101 REQ-AI101-001
    """신호가 기준 EOD 최대수익률 근사 테이블."""

    __tablename__ = "surge_signal_forward_outcome"
    __table_args__ = (
        UniqueConstraint(
            "trading_date", "fund_signal_id", name="uq_signal_forward_outcome_date_signal"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trading_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    stock_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    fund_signal_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("fund_signals.id"), nullable=False
    )
    # 신호 발행 시점 주가 (FundSignal.price_at_signal 복사값). 원본이 NULL이면 이 값도 NULL.
    price_at_signal: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # T-1 종가 절대가 (fetch_stock_price_history_sync 날짜 매칭 조회, SPEC-AI-072 선례)
    prev_close_price: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # T당일 고가 절대가 (prev_close_price × (1 + high_change_rate/100))
    day_high_price: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # 신호가 대비 EOD 최대수익률(%). 입력 중 하나라도 없으면 NULL(AC-101-003).
    forward_max_return_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
