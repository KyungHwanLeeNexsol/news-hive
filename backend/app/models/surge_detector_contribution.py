"""SPEC-AI-070 REQ-001/002: 탐지기별 롤링 기여도 스냅샷 영속화 모델.

evaluate_detector_contribution()이 T-1 surge_basis 멤버십 × T당일 scannable 결과
attribution으로 산출한 탐지기별 기여도(emission/solo/solo_tp/coincident_hit_rate/
unique_catch/retire_candidate)를 탐지기당 1행씩 run_date 기준으로 upsert한다.
assess_retirement_candidates()가 run_date desc 최근 N행을 조회해 누적
emission/solo_tp/unique_catch로 floor 미달 여부를 판정하는 입력이기도 하다.

retire_candidate는 사람 승인 게이트 리포트의 "제안" 판정일 뿐이며, 이 값 자체가
surge_detection.yaml/auto.yaml 등 어떤 config도 자동으로 변경하지 않는다(REQ-004 [HARD]).
"""
from __future__ import annotations

from datetime import date as date_
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SurgeDetectorContribution(Base):
    # @MX:NOTE: [AUTO] SPEC-AI-070 REQ-001/002 — 탐지기별 기여도 롤링 스냅샷. 스케줄러
    # 19:05 KST 평일 잡(surge_detector_contribution)에서 탐지기당 1행씩 upsert된다.
    # run_date+detector 유니크 — 동일 날짜 재실행 시 upsert(갱신)한다.
    # @MX:SPEC: SPEC-AI-070 REQ-AI070-001, REQ-AI070-002
    """탐지기별 기여도 롤링 스냅샷 테이블."""

    __tablename__ = "surge_detector_contribution"
    __table_args__ = (
        UniqueConstraint(
            "run_date", "detector", name="uq_surge_detector_contribution_run_date_detector"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 평가 기준 날짜(T당일, evaluate_surge_predictions/evaluate_detector_contribution과 동일 정의)
    run_date: Mapped[date_] = mapped_column(Date, nullable=False, index=True)
    # surge_basis에 등장하는 탐지기 식별자 문자열 (예: theme_cluster, volume_news_combo, legacy 등)
    detector: Mapped[str] = mapped_column(String(40), nullable=False)

    # D ∈ surge_basis 인 시그널 수
    emission_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # surge_basis == [D] (D 단독) 시그널 수
    solo_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # solo 시그널 중 scannable 실제급등주 적중 수
    solo_tp: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # D가 낀 모든 시그널 중 scannable 적중 비율. EC-2: 해당 run_date에 scannable 실제급등주가
    # 0이면 null(측정 불가) — 실패로 간주하지 않는다.
    coincident_hit_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # D 단독으로만 잡힌 scannable 실제급등 종목 수(중복 제거) — "D 은퇴 시 잃는 TP"
    unique_catch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # REQ-003/004: 은퇴 "제안" 플래그 — 사람이 리포트를 검토해 base surge_detection.yaml을
    # 수동 편집해야만 실제로 적용된다. 이 필드 자체는 어떤 자동 쓰기도 트리거하지 않는다.
    retire_candidate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
