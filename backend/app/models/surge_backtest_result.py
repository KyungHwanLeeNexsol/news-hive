"""SPEC-AI-069 REQ-001: backtest 게이트 판정 결과 영속화 모델.

surge_backtest.run_backtest_gate()가 산출한 pass/fail/insufficient 판정과
근거 지표(신호 수, 방향성 적중률, floor 값, config 스냅샷 해시)를 매일 1건씩 적재한다.
REQ-002/003 자동개선 거버넌스가 최신 verdict를 조회해 쓰기 가드로 사용한다.
"""
from __future__ import annotations

from datetime import date as date_, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SurgeBacktestResult(Base):
    # @MX:NOTE: [AUTO] SPEC-AI-069 REQ-001 — backtest 운영 게이트 pass/fail/insufficient 판정
    # 영속화. 스케줄러 18:45 KST 평일 잡(surge_backtest_gate)에서 매일 1건씩 적재된다.
    # REQ-003의 자동개선 쓰기 가드(surge_auto_improver._check_backtest_gate)가 최신 레코드를 조회한다.
    # @MX:SPEC: SPEC-AI-069 REQ-AI069-001
    """급등 backtest 운영 게이트 판정 결과 테이블."""

    __tablename__ = "surge_backtest_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 판정 기준 날짜 (실행일)
    run_date: Mapped[date_] = mapped_column(Date, nullable=False, index=True)

    # compute_surge_backtest 원본 지표
    total_signals: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    directional_accuracy: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    average_return_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # 판정 결과: "pass" | "fail" | "insufficient"
    verdict: Mapped[str] = mapped_column(String(20), nullable=False)
    # 판정 시점 SurgeDetectionConfig 스냅샷 sha256 해시(앞 16자) — 재현성 추적용
    config_hash: Mapped[str] = mapped_column(String(16), nullable=False)

    # 판정에 사용된 floor 값 (config 변경 이력 추적용 — REQ-002/003 거버넌스가 조회)
    min_signals: Mapped[int] = mapped_column(Integer, nullable=False)
    min_directional_accuracy: Mapped[float] = mapped_column(Float, nullable=False)
    lookback_days: Mapped[int] = mapped_column(Integer, nullable=False)

    # 탐지기 조합별 통계 (JSON string) — compute_surge_backtest().by_combination 직렬화
    by_combination_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
