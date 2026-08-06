"""SPEC-AI-105 REQ-AI105-002: bridge shadow 후보 영속화 모델.

`generate_scan_universe_bridge_candidates()`(SPEC-AI-092/102)를 마스터 스위치만
override한 config 사본으로 재호출해 계산한 shadow 후보(pool_a/pool_c 한정, §Decisions D4)를
거래일별로 저장한다. `SurgeUniverseMember`(SPEC-AI-068)와 동일한 composite PK +
일자당 replace(DELETE-then-insert) semantics를 계승한다. shadow 후보는 `qualified`/
`merged`/`FundSignal`/매매 실행 경로 어디에도 도달하지 않는다(REQ-AI105-001/006 무영향
불변식).
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SurgeBridgeShadowCandidate(Base):
    # @MX:NOTE: [AUTO] SPEC-AI-105 REQ-AI105-002 — bridge shadow 후보 영속화.
    # composite PK (trading_date, stock_code), 일자당 replace(DELETE-then-insert) semantics
    # (SurgeUniverseMember.persist_universe_members() 관례 계승 — 동일 날짜 재실행 시
    # 스테일 코드가 남지 않도록 upsert 대신 replace 사용).
    # @MX:SPEC: SPEC-AI-105 REQ-AI105-002
    """거래일별 bridge shadow 후보 테이블.

    persist_bridge_shadow_candidates()가 gather_surge_candidates() 내부(shadow 계측
    블록, `scan_universe_bridge_shadow_enabled=true`일 때만)에서 기록한다.
    analyze_bridge_shadow_precision_by_date()가 pool_a/pool_c 정밀도 측정에 사용한다.
    """

    __tablename__ = "surge_bridge_shadow_candidates"

    # composite PK: (trading_date, stock_code)
    trading_date: Mapped[date] = mapped_column(Date, primary_key=True, nullable=False)
    stock_code: Mapped[str] = mapped_column(String(10), primary_key=True, nullable=False)

    # pool_a / pool_c 한정(§Decisions D4 — pool_b는 shadow 계측에서 하드코딩 배제)
    entry_pool: Mapped[str] = mapped_column(String(10), nullable=False)

    # generate_scan_universe_bridge_candidates()가 산출한 bridge 점수(재사용, 재구현 없음)
    bridge_score: Mapped[float] = mapped_column(Float, nullable=False)

    # 레코드 생성 시각
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
