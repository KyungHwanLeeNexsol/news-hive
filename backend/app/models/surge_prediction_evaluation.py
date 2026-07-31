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
    # @MX:NOTE: [AUTO] SPEC-AI-068 — scannable_recall/coverage 컬럼 추가. scannable_recall은
    # T-1 스캔 유니버스 ∩ 실제급등주 기준 recall(알고리즘 품질), coverage는 실제급등주 중
    # 스캔 유니버스 비율(유니버스 설계 품질)이다. 레거시 recall은 유니버스 존재 시 scannable_recall과
    # 동일값으로 전환되고, 부재(과거 날짜)시 시장전체 기준 값을 유지한다(REQ-AI068-004).
    # @MX:SPEC: SPEC-AI-068 REQ-AI068-002, REQ-AI068-003, REQ-AI068-004
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
    # Pool C: 등락률 5%+ 당일 종목 수
    pool_c_count: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)

    # SPEC-AI-068 REQ-002: T-1 스캔 유니버스 교집합 기준 recall (알고리즘 품질 지표)
    # 분모(scannable_actual)가 0이면 측정 불가로 간주하여 null
    scannable_recall: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # SPEC-AI-068 REQ-003: 실제급등주 중 스캔 유니버스 비율 (유니버스 설계 품질 지표)
    # total_actual_count가 0이면 null
    coverage: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # SPEC-AI-068 REQ-002/003: 실제급등주 ∩ 스캔 유니버스 종목 수 (scannable_recall/coverage 분자)
    scannable_actual_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    # SPEC-AI-068 REQ-003: 전체 실제급등주 종목 수 (coverage 분모, actual_surge_count와 동일값)
    total_actual_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)

    # SPEC-AI-092 REQ-AI092-002: 평가 당시 공식 predicted set(near-limit carry/same-day
    # horizon 제외) 종목코드 JSON 배열 스냅샷. FundSignal.created_at이 carry-over/update
    # 경로로 후일 이동해도 평가 당시 predicted set을 복원할 수 있도록 한다. 과거(스냅샷
    # 도입 이전) row는 null — API는 null이면 기존 방식(재조회)으로 fail-open한다.
    predicted_codes_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # SPEC-AI-095 REQ-AI095-003: 고가 기준(high_change_rate) 병렬 평가지표. predicted_set과
    # COALESCE(high_change_rate, change_rate) >= 10.0 기준 실제급등집합의 교차로 산출한다.
    # 기존 recall/precision(종가 기준)과 병렬이며 대체하지 않는다(REQ-AI095-002 동결).
    # predicted_count==0 또는 TP_high+FN_high==0이면 각각 precision/recall은 null(측정 불가).
    high_based_recall: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    high_based_precision: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    high_based_coverage: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 레코드 생성 시각
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
