"""SPEC-AI-101: SPEC-AI-100 섀도우 비교 결과 영속화 테이블.

`run_horizon_shadow_comparison()`(SPEC-AI-100 소유)이 매 스코어링 사이클마다 무조건
(added/removed가 모두 빈 경우에도) 1행씩 적재한다(D3, REQ-AI101-004). 로그
(`logger.info`)는 added 또는 removed가 있을 때만 찍히므로 "변화 없는 날"이 관측
거래일 수에서 누락되는 구조적 버그가 있다 — 이 테이블이 그 문제를 원천 차단한다.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SurgeHorizonShadowObservation(Base):
    # @MX:NOTE: [AUTO] SPEC-AI-101 — SPEC-AI-100 섀도우 관측 1행/사이클 무조건 적재.
    # change_pct = (|added| + |removed|) / max(existing_qualified_count, 1) * 100 —
    # check_horizon_transition_readiness()의 전환 게이트 3요건(변화폭 ±30% 이내) 판정 입력.
    # @MX:SPEC: SPEC-AI-101 REQ-AI101-004, REQ-AI101-005
    """SPEC-AI-100 섀도우 비교 결과 1행/사이클 관측 테이블."""

    __tablename__ = "surge_horizon_shadow_observation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    market_regime: Mapped[str] = mapped_column(String(20), nullable=False)
    existing_qualified_count: Mapped[int] = mapped_column(Integer, nullable=False)
    shadow_qualified_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # JSON 배열 문자열 (종목 코드 리스트). 신규 테이블/컬럼 최소화를 위해 JSON 직렬화 재사용
    # (surge_feature_snapshot.active_detectors_json 선례).
    added_codes_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    removed_codes_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # qualified 집합 변화폭(%). 기존 qualified 0건이면 0.0.
    change_pct: Mapped[float] = mapped_column(Float, nullable=False)
