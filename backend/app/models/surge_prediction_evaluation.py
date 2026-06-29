"""SPEC-AI-041: 급등예측 정밀도/재현율 평가 결과 모델.

T-1 급등 시그널(surge_candidate)과 T 당일 실제 급등주를 비교하여
TP/FP/FN 및 precision/recall/f1을 저장한다.
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Float, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SurgePredictionEvaluation(Base):
    # @MX:NOTE: [AUTO] SPEC-AI-041 — T-1 시그널 vs T 실제 급등주 적중 평가 결과. evaluation_date 기준 upsert
    # @MX:SPEC: SPEC-AI-041 REQ-AI041-002
    """일별 급등예측 정밀도/재현율 평가 테이블."""

    __tablename__ = "surge_prediction_evaluation"

    # PK: 평가 기준 날짜 (T당일)
    evaluation_date: Mapped[date] = mapped_column(Date, primary_key=True, nullable=False)

    # T-1 시그널 수 (surge_candidate)
    predicted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # T 당일 실제 급등종목 수 (change_rate >= 10%)
    actual_surge_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # True Positive: 예측했고 실제로 급등
    true_positive: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # False Positive: 예측했으나 급등 아님
    false_positive: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # False Negative: 예측 못했으나 실제로 급등
    false_negative: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # precision = TP / (TP + FP)
    precision: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # recall = TP / (TP + FN)
    recall: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # f1 = 2 * precision * recall / (precision + recall)
    f1_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # LLM 또는 fallback 미스 분석 결과 (JSON or plain text)
    miss_analysis_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 적용된 개선 사항 요약 (JSON string)
    improvements_applied_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # SPEC-AI-060: 종목별 개별 원인 분석 결과 (JSON string)
    per_stock_analysis_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # SPEC-AI-065 REQ-5: 스캔 유니버스 크기 및 풀별 집계 컬럼
    # 당일 평가 대상 총 스캔 유니버스 크기 (Pool A+B+C+기존 합산)
    scan_universe_size: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    # Pool A: DART 공시 당일 종목 수
    pool_a_count: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    # Pool B: 거래량 200%+ 당일 종목 수
    pool_b_count: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    # Pool C: 등락률 5~15% 당일 종목 수
    pool_c_count: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)

    # 레코드 생성 시각
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
