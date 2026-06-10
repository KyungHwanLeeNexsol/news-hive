"""SPEC-AI-041: 급등예측 적중 평가 및 LLM 미스 분석 서비스.

T-1 surge_candidate 시그널과 T 당일 실제 급등주를 비교하여
precision/recall/f1을 산출하고 FP/FN 분석을 LLM에 위임한다.
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from app.models.fund_signal import FundSignal
from app.models.stock import Stock
from app.models.surge_actual_outcome import SurgeActualOutcome
from app.models.surge_prediction_evaluation import SurgePredictionEvaluation
from app.services.ai_client import ask_ai_with_openai_fallback
from app.services.surge_trading_service import _get_prev_business_day

logger = logging.getLogger(__name__)


def evaluate_surge_predictions(
    db: Session, trading_date: date
) -> SurgePredictionEvaluation:
    # @MX:NOTE: [AUTO] SPEC-AI-041 — T-1 급등 시그널 적중 평가. surge_metadata IS NOT NULL 필터로 시그널 식별
    # @MX:SPEC: SPEC-AI-041 REQ-AI041-002
    """T-1 급등 시그널과 T 당일 실제 급등주를 비교하여 SurgePredictionEvaluation을 upsert한다.

    단계:
    1. trading_date의 직전 영업일(T-1) 산출
    2. T-1에 생성된 surge_candidate 시그널 집합(predicted_set) 조회
    3. trading_date의 실제 급등주 집합(actual_set) 조회
    4. TP/FP/FN/precision/recall/f1 계산
    5. SurgePredictionEvaluation upsert

    Args:
        db: SQLAlchemy 동기 세션
        trading_date: 평가 기준 날짜 (T당일)

    Returns:
        저장된 SurgePredictionEvaluation 인스턴스
    """
    # 1. T-1 영업일 산출
    prev_business_day = _get_prev_business_day(trading_date)
    logger.info(
        "급등 시그널 평가 시작: T=%s, T-1=%s", trading_date, prev_business_day
    )

    # 2. T-1 surge_candidate 시그널 조회 (created_at 날짜 기준)
    # preday_disclosure는 제외: 공시 기반 단기 반응 예측이므로 was_surge(10%+) 기준과 불일치
    signal_rows = (
        db.query(FundSignal.stock_id, Stock.stock_code)
        .join(Stock, FundSignal.stock_id == Stock.id)
        .filter(
            FundSignal.signal_type == "surge_candidate",
            FundSignal.surge_metadata.isnot(None),
            sqlfunc.date(FundSignal.created_at) == prev_business_day,
        )
        .all()
    )

    predicted_set: set[str] = {row.stock_code for row in signal_rows}
    logger.info(
        "T-1 surge_candidate 시그널: %d건 (T-1=%s)", len(predicted_set), prev_business_day
    )

    # 3. T당일 실제 급등주 조회
    actual_rows = (
        db.query(SurgeActualOutcome.stock_code)
        .filter(
            SurgeActualOutcome.trading_date == trading_date,
            SurgeActualOutcome.was_surge.is_(True),
        )
        .all()
    )

    actual_set: set[str] = {row.stock_code for row in actual_rows}
    logger.info(
        "T당일 실제 급등주: %d건 (T=%s)", len(actual_set), trading_date
    )

    # 4. TP/FP/FN 계산
    tp = len(predicted_set & actual_set)
    fp = len(predicted_set - actual_set)
    fn = len(actual_set - predicted_set)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    logger.info(
        "평가 결과: TP=%d, FP=%d, FN=%d, precision=%.3f, recall=%.3f, f1=%.3f",
        tp, fp, fn, precision, recall, f1,
    )

    # 5. SurgePredictionEvaluation upsert (evaluation_date PK 기준)
    existing = (
        db.query(SurgePredictionEvaluation)
        .filter(SurgePredictionEvaluation.evaluation_date == trading_date)
        .first()
    )

    if existing is not None:
        existing.predicted_count = len(predicted_set)
        existing.actual_surge_count = len(actual_set)
        existing.true_positive = tp
        existing.false_positive = fp
        existing.false_negative = fn
        existing.precision = precision
        existing.recall = recall
        existing.f1_score = f1
        db.flush()
        evaluation = existing
    else:
        evaluation = SurgePredictionEvaluation(
            evaluation_date=trading_date,
            predicted_count=len(predicted_set),
            actual_surge_count=len(actual_set),
            true_positive=tp,
            false_positive=fp,
            false_negative=fn,
            precision=precision,
            recall=recall,
            f1_score=f1,
        )
        db.add(evaluation)
        db.flush()

    db.commit()
    db.refresh(evaluation)
    return evaluation


async def analyze_misses_with_llm(
    missed_stocks: list[dict], db: Session
) -> str:
    """FN 종목에 대해 LLM으로 미스 원인을 분석하거나 rule-based fallback 문자열을 반환한다.

    Args:
        missed_stocks: 미스 종목 목록 (dict에 stock_code, change_rate 등 포함),
                       change_rate 내림차순 정렬 권장
        db: SQLAlchemy 동기 세션 (현재 미사용, 향후 컨텍스트 조회용)

    Returns:
        분석 결과 문자열 (caller가 miss_analysis_json에 저장)
    """
    if not missed_stocks:
        return "미스 종목 없음 (FN=0)"

    # 상위 5개만 분석 (API 비용 최적화)
    top_5 = sorted(missed_stocks, key=lambda x: x.get("change_rate", 0.0), reverse=True)[:5]

    # 프롬프트 구성
    stocks_text = "\n".join(
        f"- {item.get('stock_code', '?')}: 등락률 {item.get('change_rate', 0.0):.1f}%"
        f" ({item.get('stock_name', item.get('stock_code', '?'))})"
        for item in top_5
    )

    prompt = (
        "다음은 오늘 10% 이상 급등했으나 전일 우리 시스템이 급등 시그널을 발생시키지 못한 종목입니다.\n\n"
        f"{stocks_text}\n\n"
        "왜 이 종목들에 대해 급등 시그널을 내지 못했는가? "
        "테마 클러스터링 미탐지, 거래량 이상 미감지, 공시 패턴 미분류 등의 관점에서 "
        "한국어로 간결하게 분석해 주세요. (3~5문장)"
    )

    try:
        text, model_used = await ask_ai_with_openai_fallback(prompt)
        if text and text.strip():
            logger.info("LLM 미스 분석 완료 (model=%s, fn_count=%d)", model_used, len(top_5))
            return text.strip()
    except Exception as e:
        logger.warning("LLM 미스 분석 예외 발생: %s", e)

    # LLM 실패(Gemini daily limit 포함) → rule-based fallback
    code_list = ", ".join(item.get("stock_code", "?") for item in top_5)
    fallback = (
        f"LLM 분석 불가. 탐지기별 미발화 사유: [{code_list}] — "
        f"총 {len(missed_stocks)}개 종목 미탐지. 수동 검토 필요."
    )
    logger.info("LLM 분석 불가 — rule-based fallback 사용 (fn_count=%d)", len(missed_stocks))
    return fallback
