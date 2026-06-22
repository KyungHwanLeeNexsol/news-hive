"""SPEC-AI-041/060: 급등예측 적중 평가 및 LLM 미스 분석 서비스.

T-1 surge_candidate 시그널과 T 당일 실제 급등주를 비교하여
precision/recall/f1을 산출하고 FP/FN 분석을 LLM에 위임한다.

SPEC-AI-060: 종목별 개별 원인 분석 및 탐지기 개선 피드백 강화.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta, timezone
from statistics import mean
from typing import Any

from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from app.models.disclosure import Disclosure
from app.models.fund_signal import FundSignal
from app.models.news import NewsArticle
from app.models.news_relation import NewsStockRelation
from app.models.stock import Stock
from app.models.surge_actual_outcome import SurgeActualOutcome
from app.models.surge_prediction_evaluation import SurgePredictionEvaluation
from app.services.ai_client import ask_ai_with_openai_fallback
from app.services.surge_trading_service import _get_prev_business_day

logger = logging.getLogger(__name__)

# 급등 원인 분류 enum (LLM 응답 검증용)
_VALID_ROOT_CAUSES = {"공시", "뉴스", "거래량", "테마", "불명"}


class _LLMBudgetGuard:
    """LLM 호출 횟수를 제한하여 Gemini free tier 일일 한도를 보호한다.

    # @MX:WARN: [AUTO] SPEC-AI-060 — Gemini free tier 20회/일 전체 공유. budget_guard 없이 직접 호출 금지
    # @MX:REASON: 일일 API 한도 초과 시 briefing/signal 잡까지 영향 받음
    """

    def __init__(self, max_calls: int, delay_sec: float) -> None:
        self._count = 0
        self._max = max_calls
        self._delay = delay_sec

    def can_call(self) -> bool:
        """추가 LLM 호출 가능 여부를 반환한다."""
        return self._count < self._max

    async def record_call(self) -> None:
        """호출 카운터를 증가시키고 rate limit 딜레이를 적용한다."""
        self._count += 1
        if self._delay > 0:
            await asyncio.sleep(self._delay)

    @property
    def used(self) -> int:
        return self._count


def enrich_surge_stock_context(
    stock_code: str, trading_date: date, db: Session
) -> dict:
    # @MX:ANCHOR: [AUTO] SPEC-AI-060 — enrich_surge_stock_context: 공시/뉴스/거래량/시그널 컨텍스트 수집. 3+ 호출 지점 예상
    # @MX:REASON: analyze_misses_with_llm + analyze_surge_cause_with_llm + scheduler에서 호출됨
    """주어진 종목의 당일 컨텍스트(공시/뉴스/거래량/시그널)를 수집한다.

    각 서브쿼리는 독립적인 try/except로 보호되어 하나 실패해도 나머지는 수집된다.

    Args:
        stock_code: 종목 코드 (6자리 문자열)
        trading_date: 평가 기준 날짜 (T당일)
        db: SQLAlchemy 동기 세션

    Returns:
        {
            "disclosures": [{"report_name": str, "ai_summary": str|None}, ...],  # 최대 2건
            "news_headlines": [{"title": str, "summary": str|None}, ...],
            "volume_ratio": float|None,  # 당일 거래량 / 최근 (N-1)일 평균
            "our_signal": dict|None,  # T-1 FundSignal surge_metadata
        }
    """
    today_str = trading_date.strftime("%Y%m%d")
    prev_business_day = _get_prev_business_day(trading_date)
    prev_day_str = prev_business_day.strftime("%Y%m%d")

    result: dict[str, Any] = {
        "disclosures": [],
        "news_headlines": [],
        "volume_ratio": None,
        "our_signal": None,
    }

    # 1. 공시: 당일/전일 공시 조회 (rcept_dt는 YYYYMMDD 문자열)
    try:
        disclosure_rows = (
            db.query(Disclosure.report_name, Disclosure.ai_summary)
            .filter(
                Disclosure.stock_code == stock_code,
                Disclosure.rcept_dt.in_([today_str, prev_day_str]),
            )
            .order_by(Disclosure.rcept_dt.desc())
            .limit(2)
            .all()
        )
        result["disclosures"] = [
            {"report_name": row.report_name, "ai_summary": row.ai_summary}
            for row in disclosure_rows
        ]
    except Exception as e:
        logger.debug("[컨텍스트] %s 공시 조회 실패: %s", stock_code, e)

    # 2. 뉴스: NewsArticle → NewsStockRelation → Stock 조인
    try:
        # 당일 00:00 ~ 익일 00:00 UTC 범위 (날짜 기준 조회)
        day_start = datetime(trading_date.year, trading_date.month, trading_date.day, tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)

        news_rows = (
            db.query(NewsArticle.title, NewsArticle.summary)
            .join(NewsStockRelation, NewsStockRelation.news_id == NewsArticle.id)
            .join(Stock, Stock.id == NewsStockRelation.stock_id)
            .filter(
                Stock.stock_code == stock_code,
                NewsArticle.published_at >= day_start,
                NewsArticle.published_at < day_end,
            )
            .limit(5)
            .all()
        )
        result["news_headlines"] = [
            {"title": row.title, "summary": row.summary}
            for row in news_rows
        ]
    except Exception as e:
        logger.debug("[컨텍스트] %s 뉴스 조회 실패: %s", stock_code, e)

    # 3. 거래량 비율: _get_volume_history 호출 후 ratio 계산
    try:
        from app.services.surge_detector import _get_volume_history

        volumes = _get_volume_history(stock_code, baseline_days=6)
        if len(volumes) >= 2:
            # 마지막이 당일, 나머지가 baseline
            baseline_vols = volumes[:-1]
            today_vol = volumes[-1]
            baseline_mean = mean(baseline_vols) if baseline_vols else None
            if baseline_mean and baseline_mean > 0:
                result["volume_ratio"] = today_vol / baseline_mean
        elif len(volumes) == 1:
            # 데이터 부족 → None 유지
            pass
    except Exception as e:
        logger.debug("[컨텍스트] %s 거래량 조회 실패: %s", stock_code, e)

    # 4. T-1 FundSignal surge_metadata 조회
    try:
        signal_row = (
            db.query(FundSignal.surge_metadata, FundSignal.signal_type, FundSignal.confidence)
            .join(Stock, FundSignal.stock_id == Stock.id)
            .filter(
                Stock.stock_code == stock_code,
                sqlfunc.date(FundSignal.created_at) == prev_business_day,
                FundSignal.surge_metadata.isnot(None),
            )
            .order_by(FundSignal.confidence.desc())
            .first()
        )
        if signal_row:
            try:
                metadata = json.loads(signal_row.surge_metadata)
            except (json.JSONDecodeError, TypeError):
                metadata = {}
            result["our_signal"] = {
                "signal_type": signal_row.signal_type,
                "confidence": signal_row.confidence,
                "contributions": metadata,
            }
    except Exception as e:
        logger.debug("[컨텍스트] %s 시그널 조회 실패: %s", stock_code, e)

    return result


def _make_fallback_cause_result(stock_code: str, reason: str = "데이터 없음(원인 미상)") -> dict:
    """LLM 호출 불가 시 rule-based fallback 결과를 반환한다."""
    return {
        "stock_code": stock_code,
        "root_cause": "불명",
        "should_have_fired": "unknown",
        "improvement_suggestion": reason,
        "confidence_note": "컨텍스트 데이터 없음",
    }


async def analyze_surge_cause_with_llm(
    stock_code: str,
    context: dict,
    our_signal: dict | None,
    db: Session,
    budget_guard: "_LLMBudgetGuard",
) -> dict:
    # @MX:WARN: [AUTO] LLM 호출 함수 — Gemini free tier 20회/일 공유. budget_guard로 8회 상한 적용
    # @MX:REASON: 일일 API 한도 초과 시 briefing/signal 잡에 영향
    """종목별 급등 원인을 LLM으로 분석하여 JSON 구조화 결과를 반환한다.

    Args:
        stock_code: 종목 코드
        context: enrich_surge_stock_context() 반환값
        our_signal: T-1 시그널 정보 (없으면 None)
        db: SQLAlchemy 동기 세션 (현재 미사용, 향후 확장용)
        budget_guard: LLM 호출 횟수 제한기

    Returns:
        {
            "stock_code": str,
            "root_cause": "공시"|"뉴스"|"거래량"|"테마"|"불명",
            "should_have_fired": str,  # 탐지기명 또는 "unknown"
            "improvement_suggestion": str,
            "confidence_note": str,
        }
    """
    # AC-15: 컨텍스트 데이터가 전부 없으면 LLM 호출 없이 즉시 반환
    has_context = (
        bool(context.get("disclosures"))
        or bool(context.get("news_headlines"))
        or context.get("volume_ratio") is not None
    )
    if not has_context:
        return _make_fallback_cause_result(stock_code)

    # 예산 초과 시 fallback
    if not budget_guard.can_call():
        return _make_fallback_cause_result(stock_code, reason="LLM 예산 초과 — 수동 검토 필요")

    # 프롬프트 구성
    disclosures_text = "\n".join(
        f"  - {d['report_name']}: {d.get('ai_summary') or '요약 없음'}"
        for d in context.get("disclosures", [])
    ) or "  없음"

    news_text = "\n".join(
        f"  - {n['title']}"
        for n in context.get("news_headlines", [])
    ) or "  없음"

    volume_text = (
        f"{context['volume_ratio']:.2f}배" if context.get("volume_ratio") is not None else "데이터 없음"
    )

    signal_text = "없음 (미탐지)"
    if our_signal:
        signal_text = (
            f"signal_type={our_signal.get('signal_type')}, "
            f"confidence={our_signal.get('confidence')}"
        )

    prompt = (
        f"종목코드: {stock_code}\n"
        f"당일 공시:\n{disclosures_text}\n"
        f"당일 뉴스:\n{news_text}\n"
        f"당일 거래량 배율: {volume_text}\n"
        f"우리 시스템 T-1 시그널: {signal_text}\n\n"
        "위 데이터를 바탕으로 이 종목이 당일 급등한 원인을 분석하고, "
        "우리 시스템이 미탐지했다면 어떤 탐지기가 발화했어야 하는지 제안하세요.\n\n"
        "반드시 아래 JSON 형식으로만 응답하세요:\n"
        "{\n"
        '  "root_cause": "공시"|"뉴스"|"거래량"|"테마"|"불명",\n'
        '  "should_have_fired": "탐지기명 또는 unknown",\n'
        '  "improvement_suggestion": "구체적인 개선 제안 (1~2문장)",\n'
        '  "confidence_note": "분석 신뢰도 메모"\n'
        "}"
    )

    try:
        text, model_used = await ask_ai_with_openai_fallback(prompt, free_only=True)
        await budget_guard.record_call()

        if not text or not text.strip():
            return _make_fallback_cause_result(stock_code, reason="LLM 빈 응답")

        # JSON 파싱 시도
        raw = text.strip()
        # 마크다운 코드블록 제거
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw

        parsed = json.loads(raw)
        root_cause = parsed.get("root_cause", "불명")
        if root_cause not in _VALID_ROOT_CAUSES:
            root_cause = "불명"

        return {
            "stock_code": stock_code,
            "root_cause": root_cause,
            "should_have_fired": str(parsed.get("should_have_fired", "unknown")),
            "improvement_suggestion": str(parsed.get("improvement_suggestion", "")),
            "confidence_note": str(parsed.get("confidence_note", "")),
        }

    except json.JSONDecodeError:
        # JSON 파싱 실패 → 자유 텍스트를 improvement_suggestion에 보존
        if text and text.strip():
            return {
                "stock_code": stock_code,
                "root_cause": "불명",
                "should_have_fired": "unknown",
                "improvement_suggestion": text.strip()[:500],
                "confidence_note": "JSON 파싱 실패 — 자유 텍스트 저장",
            }
        return _make_fallback_cause_result(stock_code, reason="JSON 파싱 실패")

    except Exception as e:
        logger.warning("[LLM 원인 분석] %s 실패: %s", stock_code, e)
        return _make_fallback_cause_result(stock_code, reason=f"LLM 오류: {e}")


async def analyze_true_positives_with_llm(
    tp_stocks: list[dict],
    db: Session,
    budget_guard: "_LLMBudgetGuard",
) -> list[dict]:
    """TP 종목의 급등 원인을 분석하여 강화 시그널을 반환한다.

    Args:
        tp_stocks: [{"stock_code": str, "change_rate": float, "stock_name": str}, ...]
        db: SQLAlchemy 동기 세션
        budget_guard: FN 분석과 공유하는 LLM 호출 예산 가드

    Returns:
        [{"stock_code": str, "winning_detector": str, "pattern_summary": str, "reinforce": bool}, ...]
    """
    results: list[dict] = []

    for stock in tp_stocks:
        stock_code = stock.get("stock_code", "?")

        if not budget_guard.can_call():
            results.append({
                "stock_code": stock_code,
                "winning_detector": "unknown",
                "pattern_summary": "예산 초과로 분석 생략",
                "reinforce": False,
            })
            continue

        try:
            context = enrich_surge_stock_context(stock_code, date.today(), db)
        except Exception as e:
            logger.debug("[TP 분석] %s 컨텍스트 수집 실패: %s", stock_code, e)
            context = {"disclosures": [], "news_headlines": [], "volume_ratio": None, "our_signal": None}

        our_signal = context.get("our_signal")

        # 시그널이 있으면 어떤 탐지기가 기여했는지 LLM에 묻는다
        contributions = {}
        if our_signal:
            contributions = our_signal.get("contributions", {})

        # 시그널 정보가 충분하면 LLM 호출
        if not budget_guard.can_call():
            results.append({
                "stock_code": stock_code,
                "winning_detector": "unknown",
                "pattern_summary": "예산 초과",
                "reinforce": False,
            })
            continue

        contributions_text = ", ".join(
            f"{k}={v}" for k, v in contributions.items()
            if isinstance(v, (int, float, str))
        ) if contributions else "없음"

        prompt = (
            f"종목코드 {stock_code} (등락률 {stock.get('change_rate', 0):.1f}%)가 "
            f"오늘 급등했으며 우리 시스템이 T-1에 예측에 성공했습니다.\n"
            f"탐지기 기여도: {contributions_text}\n\n"
            "어떤 탐지기가 가장 결정적이었으며, 이 패턴을 강화할 방법은 무엇인가요?\n"
            "JSON 형식으로만 응답하세요:\n"
            "{\n"
            '  "winning_detector": "탐지기명",\n'
            '  "pattern_summary": "핵심 패턴 요약 (1~2문장)",\n'
            '  "reinforce": true|false\n'
            "}"
        )

        try:
            text, _ = await ask_ai_with_openai_fallback(prompt, free_only=True)
            await budget_guard.record_call()

            raw = (text or "").strip()
            if raw.startswith("```"):
                lines = raw.split("\n")
                raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw

            parsed = json.loads(raw)
            results.append({
                "stock_code": stock_code,
                "winning_detector": str(parsed.get("winning_detector", "unknown")),
                "pattern_summary": str(parsed.get("pattern_summary", "")),
                "reinforce": bool(parsed.get("reinforce", False)),
            })
        except Exception as e:
            logger.debug("[TP LLM] %s 분석 실패: %s", stock_code, e)
            results.append({
                "stock_code": stock_code,
                "winning_detector": "unknown",
                "pattern_summary": f"분석 실패: {e}",
                "reinforce": False,
            })

    return results


def generate_detector_improvement_suggestions(
    analysis_results: list[dict],
) -> list[dict]:
    """FN 개별 분석 결과를 탐지기별로 집계하여 개선 제안을 생성한다.

    Args:
        analysis_results: analyze_surge_cause_with_llm() 결과 목록

    Returns:
        [
            {
                "detector": str,
                "missed_count": int,
                "sample_codes": list[str],
                "suggestion": str,
                "priority": "high"|"medium"|"low",
            },
            ...
        ]  # missed_count 내림차순 정렬
    """
    # 탐지기명 → {missed_count, sample_codes, suggestions}
    aggregated: dict[str, dict] = {}

    for item in analysis_results:
        detector = item.get("should_have_fired", "unknown") or "unknown"
        # 빈 문자열/None 정규화
        if not detector or not isinstance(detector, str):
            detector = "unknown"

        if detector not in aggregated:
            aggregated[detector] = {
                "missed_count": 0,
                "sample_codes": [],
                "suggestions": [],
            }

        agg = aggregated[detector]
        agg["missed_count"] += 1
        code = item.get("stock_code", "?")
        if code not in agg["sample_codes"]:
            agg["sample_codes"].append(code)
        suggestion = item.get("improvement_suggestion", "")
        if suggestion and suggestion not in agg["suggestions"]:
            agg["suggestions"].append(suggestion)

    # 정렬 및 변환
    suggestions: list[dict] = []
    for detector, agg in sorted(aggregated.items(), key=lambda x: -x[1]["missed_count"]):
        count = agg["missed_count"]
        priority = "high" if count >= 3 else ("medium" if count >= 2 else "low")
        merged_suggestion = " / ".join(agg["suggestions"][:3]) if agg["suggestions"] else "개선 제안 없음"
        suggestions.append({
            "detector": detector,
            "missed_count": count,
            "sample_codes": agg["sample_codes"][:5],
            "suggestion": merged_suggestion,
            "priority": priority,
        })

    return suggestions


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

    SPEC-AI-060: 종목별 컨텍스트 수집 + 개별 LLM 분석 + 탐지기별 집계 강화.
    시그니처는 변경 없음 (scheduler.py 호환 유지).

    Args:
        missed_stocks: 미스 종목 목록 (dict에 stock_code, change_rate 등 포함),
                       change_rate 내림차순 정렬 권장
        db: SQLAlchemy 동기 세션

    Returns:
        분석 결과 JSON 문자열 또는 fallback 텍스트 (caller가 miss_analysis_json에 저장)
    """
    if not missed_stocks:
        return "미스 종목 없음 (FN=0)"

    # 상위 5개만 분석 (API 비용 최적화)
    top_5 = sorted(missed_stocks, key=lambda x: x.get("change_rate", 0.0), reverse=True)[:5]

    # SPEC-AI-060: 종목별 컨텍스트 수집 및 LLM 개별 분석 시도
    try:
        budget_guard = _LLMBudgetGuard(max_calls=8, delay_sec=1.0)

        per_stock_results: list[dict] = []
        trading_date = date.today()

        for stock in top_5:
            stock_code = stock.get("stock_code", "?")
            try:
                context = enrich_surge_stock_context(stock_code, trading_date, db)
                our_signal = context.get("our_signal")
                result = await analyze_surge_cause_with_llm(
                    stock_code=stock_code,
                    context=context,
                    our_signal=our_signal,
                    db=db,
                    budget_guard=budget_guard,
                )
                result["change_rate"] = stock.get("change_rate", 0.0)
                result["stock_name"] = stock.get("stock_name", stock_code)
                per_stock_results.append(result)
            except Exception as e:
                logger.debug("[FN 분석] %s 처리 실패: %s", stock_code, e)
                per_stock_results.append({
                    "stock_code": stock_code,
                    "root_cause": "불명",
                    "should_have_fired": "unknown",
                    "improvement_suggestion": f"분석 실패: {e}",
                    "confidence_note": "",
                    "change_rate": stock.get("change_rate", 0.0),
                    "stock_name": stock.get("stock_name", stock_code),
                })

        # 탐지기별 집계
        detector_suggestions = generate_detector_improvement_suggestions(per_stock_results)

        output = {
            "analysis_type": "per_stock_v2",
            "fn_count": len(missed_stocks),
            "analyzed_count": len(per_stock_results),
            "llm_calls_used": budget_guard.used,
            "per_stock": per_stock_results,
            "detector_suggestions": detector_suggestions,
        }

        logger.info(
            "LLM 종목별 미스 분석 완료 (fn=%d, analyzed=%d, llm_calls=%d)",
            len(missed_stocks), len(per_stock_results), budget_guard.used,
        )
        return json.dumps(output, ensure_ascii=False)

    except Exception as e:
        logger.warning("종목별 분석 실패 — 기존 단순 LLM fallback 사용: %s", e)

    # 기존 단순 LLM fallback (SPEC-AI-041 동작 유지)
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
