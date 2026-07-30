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


def _is_near_limit_up_carry_signal(surge_metadata_json: str | None) -> bool:
    """surge_metadata 문자열이 near_limit_up_carry 탐지 결과인지 판별한다.

    SPEC-AI-075: near_limit_up_carry(surge_detector.py:2649)는 signal_type=="surge_candidate"를
    표준 지평 탐지기와 공유하므로 signal_type 필터로는 배제할 수 없다. surge_basis 리스트
    멤버십(코드베이스 전반의 탐지기 귀속 정본)을 1차 판별 기준으로, 플랫 near_limit_up_carry
    키(True)를 OR 폴백으로 사용한다(surge_detector.py:2751-2756 — 탐지기는 두 키를 항상 함께
    쓰지만 향후 변형에도 견고하도록). JSON 파싱 실패(손상 데이터)는 표준 지평 시그널로 보수적
    포함한다(fail-safe) — 배제 로직 오류로 표준 시그널을 잘못 버리는 것보다 안전하다.
    """
    if not surge_metadata_json:
        return False
    try:
        metadata = json.loads(surge_metadata_json)
    except (TypeError, ValueError):
        return False
    if not isinstance(metadata, dict):
        return False
    surge_basis = metadata.get("surge_basis")
    if isinstance(surge_basis, list) and "near_limit_up_carry" in surge_basis:
        return True
    return metadata.get("near_limit_up_carry") is True


def _is_same_day_event_horizon_signal(surge_metadata_json: str | None) -> bool:
    """SPEC-AI-080 REQ-AI080-004 둘째 규칙: 급등 당일(T) 장중 접수된 즉시 발화 시그널
    (horizon=="same_day")은 표준 T-1→T predicted_set에서 배제하고 별도 same-day 서브지표로
    집계한다. disclosure_impact_scorer._create_immediate_surge_signal()이 T-1 종가 이후
    접수분에는 horizon="next_day"를, 09:00~배치컷오프 접수분에는 horizon="same_day"를
    부여한다(OQ-2). SPEC-AI-075의 near_limit_up_carry 배제 패턴(surge_metadata 내용 기반
    판별)을 그대로 재사용한다 — signal_type만으로는 구분 불가하므로(둘 다
    signal_type=="surge_candidate"를 공유). JSON 파싱 실패는 False(표준 지평 시그널로
    보수적 포함, fail-safe — SPEC-AI-075와 동일한 안전 원칙).
    """
    if not surge_metadata_json:
        return False
    try:
        metadata = json.loads(surge_metadata_json)
    except (TypeError, ValueError):
        return False
    if not isinstance(metadata, dict):
        return False
    return metadata.get("horizon") == "same_day"


def diagnose_non_scannable_causes(
    db: Session,
    trading_date: date,
) -> dict[str, str]:
    # @MX:NOTE: [AUTO] SPEC-AI-086 REQ-AI086-002 — non_scannable 실제급등주 원인 진단
    # (truncated vs absent). 신규 마이그레이션 없이 기존 테이블(SurgeActualOutcome,
    # Disclosure)만 재사용한다. Pool B(거래량200%+)는 장중 실시간 거래량이 사후 재구성
    # 불가능하므로 raw 재판정 대상에서 제외한다(plan.md R-1, 정직한 한계 문서화).
    # @MX:SPEC: SPEC-AI-086 REQ-AI086-002
    """trading_date(T)의 non_scannable 실제급등주를 truncated/absent로 분류한다.

    T-1 시점 Pool A(DART 공시)/Pool C(당일 등락률 5%+) raw 후보 자격을 재판정하여,
    자격이 있었으나(=상한/quota 절단으로 탈락) truncated, 자격 자체가 없었으면 absent로
    분류한다.

    Args:
        db: SQLAlchemy 동기 세션
        trading_date: 평가 기준 날짜 (T당일, SurgeActualOutcome.trading_date)

    Returns:
        {stock_code: "truncated" | "absent"} — non_scannable 종목이 없으면 빈 dict.
    """
    prev_business_day = _get_prev_business_day(trading_date)
    prev_day_str = prev_business_day.strftime("%Y%m%d")

    non_scannable_rows = (
        db.query(SurgeActualOutcome.stock_code)
        .filter(
            SurgeActualOutcome.trading_date == trading_date,
            SurgeActualOutcome.was_surge.is_(True),
            SurgeActualOutcome.surge_type == "non_scannable",
        )
        .all()
    )
    non_scannable_codes = [r.stock_code for r in non_scannable_rows]
    if not non_scannable_codes:
        return {}

    result: dict[str, str] = {}
    try:
        pool_a_raw_codes = {
            r.stock_code
            for r in db.query(Disclosure.stock_code)
            .filter(
                Disclosure.rcept_dt == prev_day_str,
                Disclosure.stock_code.in_(non_scannable_codes),
            )
            .all()
        }
        pool_c_raw_codes = {
            r.stock_code
            for r in db.query(SurgeActualOutcome.stock_code)
            .filter(
                SurgeActualOutcome.trading_date == prev_business_day,
                SurgeActualOutcome.stock_code.in_(non_scannable_codes),
                SurgeActualOutcome.change_rate.isnot(None),
                SurgeActualOutcome.change_rate >= 5.0,
            )
            .all()
        }
        truncated_bound_codes = pool_a_raw_codes | pool_c_raw_codes

        for code in non_scannable_codes:
            result[code] = "truncated" if code in truncated_bound_codes else "absent"
    except Exception as e:
        logger.warning("[급등평가] non_scannable 원인 진단 실패 (무시): %s", e)
        try:
            db.rollback()
        except Exception:
            pass
        return {}

    truncated_count = sum(1 for v in result.values() if v == "truncated")
    absent_count = len(result) - truncated_count
    logger.info(
        "[급등평가] non_scannable 원인 진단 완료 — date=%s truncated=%d absent=%d "
        "(Pool B는 사후 재구성 불가로 재판정 대상 제외)",
        trading_date, truncated_count, absent_count,
    )
    return result


def classify_scannable_denominator_expansion(
    *,
    prev_scannable_actual_count: int,
    prev_scan_universe_size: int,
    curr_scannable_actual_count: int,
    curr_scan_universe_size: int,
) -> bool:
    # @MX:NOTE: [AUTO] SPEC-AI-086 REQ-AI086-006 — scannable_recall 하락이 탐지 회귀가
    # 아니라 측정 분모(스캔 유니버스) 확장에 기인했음을 기계적으로 구분하기 위한 명명
    # 토큰. 순수 함수 — DB 접근 없음, 테스트에서 직접 assert 가능(D6 검증 기준).
    # @MX:SPEC: SPEC-AI-086 REQ-AI086-006
    """분모(스캔 유니버스) 확장 여부를 판정한다.

    True이면 이번 평가의 scan_universe_size(분모)가 이전 대비 확장되었고
    scannable_actual_count(실제급등 교집합)도 함께 늘었음을 의미한다 — 즉 "더 많이
    재는" 확장이지 탐지 실패가 아니다.
    """
    return (
        curr_scan_universe_size > prev_scan_universe_size
        and curr_scannable_actual_count >= prev_scannable_actual_count
    )


def restore_predicted_codes(evaluation: SurgePredictionEvaluation) -> list[str] | None:
    # @MX:NOTE: [AUTO] SPEC-AI-092 REQ-AI092-002 — evaluate_surge_predictions()가 저장한
    # predicted_codes_json 스냅샷에서 평가 당시 공식 predicted set을 복원한다.
    # FundSignal.created_at이 carry-over/update 경로로 후일 이동해도 영향받지 않는다.
    # 스냅샷 도입 이전 row(필드 없음) 또는 손상된 JSON은 None을 반환해 호출부가
    # 기존 방식(FundSignal 재조회)으로 fail-open할 수 있게 한다.
    # @MX:SPEC: SPEC-AI-092 REQ-AI092-002
    """평가 레코드의 predicted_codes_json 스냅샷을 파싱해 복원한다.

    Args:
        evaluation: SurgePredictionEvaluation 인스턴스

    Returns:
        복원된 종목코드 리스트. 스냅샷이 없거나 손상되었으면 None(fail-open).
    """
    if not evaluation.predicted_codes_json:
        return None
    try:
        codes = json.loads(evaluation.predicted_codes_json)
    except (TypeError, ValueError):
        return None
    if not isinstance(codes, list):
        return None
    return codes


def evaluate_surge_predictions(
    db: Session,
    trading_date: date,
    pool_counts: dict[str, int] | None = None,
    prior_scannable_metrics: dict[str, int] | None = None,
) -> SurgePredictionEvaluation:
    # @MX:NOTE: [AUTO] SPEC-AI-041 — T-1 급등 시그널 적중 평가. surge_metadata IS NOT NULL 필터로 시그널 식별
    # @MX:SPEC: SPEC-AI-041 REQ-AI041-002
    # @MX:NOTE: [AUTO] SPEC-AI-068 — Scannable Recall/Coverage 진단지표 추가. T-1 영속화 스캔
    # 유니버스(REQ-001)와 실제급등주의 교집합(scannable_actual)을 분모/분자로 사용해 알고리즘
    # 품질(scannable_recall)과 유니버스 설계 품질(coverage)을 분리 산출한다. 유니버스가 부재한
    # 과거 날짜는 둘 다 null(coverage-미상)이며, 레거시 recall 컬럼은 시장전체 기준 값을 유지한다
    # (REQ-AI068-004). TP/FP/FN/precision과 pool_counts 패스스루 로직은 변경하지 않는다.
    # @MX:SPEC: SPEC-AI-068 REQ-AI068-002, REQ-AI068-003, REQ-AI068-004, REQ-AI068-005
    """T-1 급등 시그널과 T 당일 실제 급등주를 비교하여 SurgePredictionEvaluation을 upsert한다.

    단계:
    1. trading_date의 직전 영업일(T-1) 산출
    2. T-1에 생성된 surge_candidate 시그널 집합(predicted_set) 조회
    3. trading_date의 실제 급등주 집합(actual_set) 조회 (시장전체 기준, 변경 없음)
    4. TP/FP/FN/precision/legacy_recall/f1 계산 (시장전체 기준, 변경 없음)
    5. T-1 영속화 스캔 유니버스(REQ-001) 조회 → scannable_actual = actual_set ∩ universe_set
       기준으로 scannable_recall/coverage 산출 (SPEC-AI-068 REQ-002/003/004)
    6. SurgePredictionEvaluation upsert (핵심 평가 결과 — 별도 커밋으로 보존)
    7. SurgeActualOutcome.surge_type 라벨링 (scannable/non_scannable, REQ-005,
       실패해도 6단계 결과는 보존되도록 별도 트랜잭션으로 격리)

    Args:
        db: SQLAlchemy 동기 세션
        trading_date: 평가 기준 날짜 (T당일)
        pool_counts: SPEC-AI-065 REQ-5 — 스캔 유니버스 pool 집계
                     {"pool_a": int, "pool_b": int, "pool_c": int, "scan_universe_size": int}
        prior_scannable_metrics: SPEC-AI-086 REQ-AI086-006(선택) — 이전 평가의
                     {"scannable_actual_count": int, "scan_universe_size": int}. 제공되면
                     scannable_denominator_expanded를 계산해 반환 객체의 동명 속성(비영속,
                     신규 컬럼 없음)에 설정하고 로그로 남긴다. 미제공(기본, 기존 호출부
                     전부 해당) 시 속성은 None — 기존 동작과 완전히 동일(REQ-AI086-007).

    Returns:
        저장된 SurgePredictionEvaluation 인스턴스 (scannable_denominator_expanded 속성은
        비영속 — DB 컬럼이 아니라 이 호출 결과에만 존재하는 런타임 속성)
    """
    # 1. T-1 영업일 산출
    prev_business_day = _get_prev_business_day(trading_date)
    logger.info(
        "급등 시그널 평가 시작: T=%s, T-1=%s", trading_date, prev_business_day
    )

    # 2. T-1 surge_candidate 시그널 조회 (created_at 날짜 기준)
    # preday_disclosure는 제외: 공시 기반 단기 반응 예측이므로 was_surge(10%+) 기준과 불일치
    # @MX:NOTE: [AUTO] SPEC-AI-080 — surge_metadata.isnot(None)은 즉시 발화 시그널이
    # predicted_set에 편입되기 위한 필수 조건이다. disclosure_impact_scorer가 non-None
    # surge_metadata(OQ-5 마커 포함)를 기록하지 않으면 signal_type·날짜가 맞아도 여기서
    # 조용히 배제된다(EC-8) — _create_immediate_surge_signal은 항상 non-None을 기록한다.
    # @MX:SPEC: SPEC-AI-080 REQ-AI080-004
    signal_rows = (
        db.query(FundSignal.stock_id, Stock.stock_code, FundSignal.surge_metadata)
        .join(Stock, FundSignal.stock_id == Stock.id)
        .filter(
            FundSignal.signal_type == "surge_candidate",
            FundSignal.surge_metadata.isnot(None),
            sqlfunc.date(FundSignal.created_at) == prev_business_day,
        )
        .all()
    )

    # @MX:NOTE: [AUTO] SPEC-AI-075 — near_limit_up_carry(surge_detector.py:2649)는
    # signal_type=="surge_candidate"를 표준 지평 탐지기와 공유하지만 target day가 시그널
    # 발행일(D) 자체라 지평이 다르다(표준 규칙은 T-1→T 비교). signal_type으로는 구분 불가하므로
    # surge_metadata 내용(surge_basis 리스트 멤버십 1차, 플랫 near_limit_up_carry 키 OR 폴백)으로
    # predicted_set 한 곳에서만 배제한다(actual_set/표준 버킷팅 규칙 불변). 라이브 데이터(2026-07-06/
    # 07-07)에서 near_limit_up_carry가 전체 surge_candidate 발신의 100%/75%를 차지해 evaluation
    # coverage/recall 지표를 오염시켰음을 확인(research.md §6).
    # @MX:SPEC: SPEC-AI-075 REQ-AI075-001, REQ-AI075-002
    # @MX:NOTE: [AUTO] SPEC-AI-080 — 즉시 발화 시그널 중 horizon=="same_day"(급등 당일 장중
    # 접수분)도 동일 패턴으로 predicted_set에서 배제하고 별도 same-day 서브지표로 집계한다
    # (REQ-AI080-004 둘째 규칙, Scenario 2).
    # @MX:SPEC: SPEC-AI-080 REQ-AI080-004
    predicted_set: set[str] = set()
    excluded_near_limit_up_carry_codes: list[str] = []
    excluded_same_day_event_codes: list[str] = []
    for row in signal_rows:
        if _is_near_limit_up_carry_signal(row.surge_metadata):
            excluded_near_limit_up_carry_codes.append(row.stock_code)
            continue
        if _is_same_day_event_horizon_signal(row.surge_metadata):
            excluded_same_day_event_codes.append(row.stock_code)
            continue
        predicted_set.add(row.stock_code)

    if excluded_near_limit_up_carry_codes:
        logger.info(
            "[급등평가] near_limit_up_carry 배제: %d건 (예시: %s) — SPEC-AI-075 평가 지평 불일치",
            len(excluded_near_limit_up_carry_codes),
            excluded_near_limit_up_carry_codes[:5],
        )

    if excluded_same_day_event_codes:
        # REQ-AI080-007(P2): same-day 이벤트 서브지표 — 신규 테이블/컬럼 없이 로그로만 집계
        # (DP-2: 파생 계산, 스키마 무변경). 표준 T-1→T scannable_recall과는 별도 지평.
        logger.info(
            "[급등평가] same-day 이벤트 서브지표(T→T, 표준 T-1→T 배제): %d건 (예시: %s) — "
            "SPEC-AI-080 지평 분리",
            len(excluded_same_day_event_codes),
            excluded_same_day_event_codes[:5],
        )

    logger.info(
        "T-1 surge_candidate 시그널: %d건 (T-1=%s)", len(predicted_set), prev_business_day
    )

    # 3. T당일 실제 급등주 조회 (시장전체 기준)
    # SPEC-AI-068 REQ-AI068-004: 과거 "surge_actual_outcome이 이미 스캔 유니버스"라는 전제는
    # 거짓이었다 — 실제로는 KOSPI/KOSDAQ 상위 100개 무버 기준으로 수집되어 우리가 스캔한
    # 유니버스와 무관하다(surge_actual_outcome_service.py 참조). 이 actual_set은 TP/FP/FN/
    # precision/legacy recall(시장전체 기준, 하위호환)과 coverage(REQ-003)의 분모로만 쓰이고,
    # Scannable Recall(REQ-002)의 분모는 아래 5단계에서 별도로 유니버스 교집합으로 산출한다.
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

    # 4. TP/FP/FN 계산 (시장전체 기준, 변경 없음)
    tp = len(predicted_set & actual_set)
    fp = len(predicted_set - actual_set)
    fn = len(actual_set - predicted_set)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    # 레거시(시장전체 기준) recall. Scannable Recall이 측정 가능(유니버스 존재)하면 아래에서
    # 최종 recall 컬럼 값이 scannable_recall로 대체되고, 유니버스 부재 시에는 이 값을 유지한다.
    legacy_recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (
        2 * precision * legacy_recall / (precision + legacy_recall)
        if (precision + legacy_recall) > 0
        else 0.0
    )

    logger.info(
        "평가 결과: TP=%d, FP=%d, FN=%d, precision=%.3f, legacy_recall=%.3f, f1=%.3f",
        tp, fp, fn, precision, legacy_recall, f1,
    )

    # 5. SPEC-AI-068 REQ-001/002/003/004: T-1 영속화 스캔 유니버스 조회 → Scannable Recall/Coverage
    #    Scannable Recall = |universe ∩ actual ∩ predicted| / |universe ∩ actual|
    #    Coverage         = |universe ∩ actual| / |actual|
    scannable_recall: float | None = None
    coverage: float | None = None
    scannable_actual_count = 0
    total_actual_count = len(actual_set)
    final_recall = legacy_recall
    # REQ-005 라벨링(하단)에서도 재사용 — 조회 실패 시 빈 집합으로 안전하게 폴백
    universe_set: set[str] = set()

    try:
        from app.services.surge_universe_pool_service import get_universe_members_for_date

        universe_set = get_universe_members_for_date(db, prev_business_day)
        # EC-2: 유니버스 코드가 없는(과거 미백필 등) 날짜는 "유니버스 부재"로 간주 —
        # scannable_recall/coverage 모두 null(coverage-미상), 레거시 recall만 유지.
        universe_exists = len(universe_set) > 0

        if universe_exists:
            scannable_actual = actual_set & universe_set
            scannable_actual_count = len(scannable_actual)

            # EC-1: 유니버스 교집합(scannable_actual) 0 → scannable_recall=null(측정 불가)
            if scannable_actual_count > 0:
                scannable_recall = len(scannable_actual & predicted_set) / scannable_actual_count

            # EC-3: 전체 실제급등주 0 → coverage=null
            if total_actual_count > 0:
                coverage = scannable_actual_count / total_actual_count

            final_recall = scannable_recall
    except Exception as _se:
        # 지표 계산 실패는 평가 잡 전체를 죽이지 않는다 — 지표만 null 처리(REQ-004 리스크 완화)
        logger.warning("[급등평가] Scannable Recall/Coverage 계산 실패 (지표 null 처리): %s", _se)
        try:
            db.rollback()
        except Exception:
            pass
        scannable_recall = None
        coverage = None
        scannable_actual_count = 0
        final_recall = legacy_recall

    logger.info(
        "Scannable 지표: scannable_actual=%d, total_actual=%d, scannable_recall=%s, coverage=%s",
        scannable_actual_count, total_actual_count, scannable_recall, coverage,
    )

    # SPEC-AI-065 REQ-5: pool_counts 정규화
    _pool_a = (pool_counts or {}).get("pool_a", 0)
    _pool_b = (pool_counts or {}).get("pool_b", 0)
    _pool_c = (pool_counts or {}).get("pool_c", 0)
    _scan_universe_size = (pool_counts or {}).get("scan_universe_size", 0)

    # SPEC-AI-092 REQ-AI092-002: 평가 당시 공식 predicted set(near-limit carry/same-day
    # horizon 배제 이후 확정된 predicted_set) 스냅샷. FundSignal.created_at 이동에 영향받지
    # 않는다 — 이 시점에 이미 확정된 predicted_set을 그대로 직렬화한다.
    predicted_codes_json = json.dumps(sorted(predicted_set), ensure_ascii=False)

    # 6. SurgePredictionEvaluation upsert (evaluation_date PK 기준)
    existing = (
        db.query(SurgePredictionEvaluation)
        .filter(SurgePredictionEvaluation.evaluation_date == trading_date)
        .first()
    )

    if existing is not None:
        existing.predicted_count = len(predicted_set)
        existing.predicted_codes_json = predicted_codes_json
        existing.actual_surge_count = len(actual_set)
        existing.true_positive = tp
        existing.false_positive = fp
        existing.false_negative = fn
        existing.precision = precision
        existing.recall = final_recall
        existing.f1_score = f1
        existing.scannable_recall = scannable_recall
        existing.coverage = coverage
        existing.scannable_actual_count = scannable_actual_count
        existing.total_actual_count = total_actual_count
        # SPEC-AI-065 REQ-5: pool_counts 업데이트
        if pool_counts is not None:
            existing.scan_universe_size = _scan_universe_size
            existing.pool_a_count = _pool_a
            existing.pool_b_count = _pool_b
            existing.pool_c_count = _pool_c
        db.flush()
        evaluation = existing
    else:
        evaluation = SurgePredictionEvaluation(
            evaluation_date=trading_date,
            predicted_count=len(predicted_set),
            predicted_codes_json=predicted_codes_json,
            actual_surge_count=len(actual_set),
            true_positive=tp,
            false_positive=fp,
            false_negative=fn,
            precision=precision,
            recall=final_recall,
            f1_score=f1,
            scannable_recall=scannable_recall,
            coverage=coverage,
            scannable_actual_count=scannable_actual_count,
            total_actual_count=total_actual_count,
            # SPEC-AI-065 REQ-5: pool_counts 초기화
            scan_universe_size=_scan_universe_size,
            pool_a_count=_pool_a,
            pool_b_count=_pool_b,
            pool_c_count=_pool_c,
        )
        db.add(evaluation)
        db.flush()

    db.commit()
    db.refresh(evaluation)

    # 7. SPEC-AI-068 REQ-005: 급등 유형 라벨링 (scannable/non_scannable)
    # AI-061 B01/B02 패턴과 동일하게 핵심 평가 결과(위 commit) 이후 별도 트랜잭션으로
    # 격리한다 — 라벨링 실패가 이미 저장된 precision/recall/scannable_recall/coverage를
    # 훼손하지 않도록 한다.
    # @MX:NOTE: [AUTO] SPEC-AI-068 REQ-005 — 실제급등주를 T-1 유니버스 포함 여부로 라벨링.
    # scannable(T-1 유니버스 포함, 선행형·공식 예측 목표) / non_scannable(미포함, 당일
    # 뉴스·공시 촉매형). non_scannable 집단은 향후 별도 "장중 실시간 조기탐지 트랙"에
    # 귀속될 경계만 정의하며, 그 실시간 파이프라인 자체는 본 SPEC 범위 밖이다
    # (Exclusions #1 — 별도 후속 SPEC에서 구현).
    # @MX:SPEC: SPEC-AI-068 REQ-AI068-005
    try:
        outcome_rows = (
            db.query(SurgeActualOutcome)
            .filter(
                SurgeActualOutcome.trading_date == trading_date,
                SurgeActualOutcome.was_surge.is_(True),
            )
            .all()
        )
        for row in outcome_rows:
            row.surge_type = "scannable" if row.stock_code in universe_set else "non_scannable"
        db.commit()
    except Exception as _le:
        logger.warning("[급등평가] surge_type 라벨링 실패 (무시, 핵심 평가 결과는 보존됨): %s", _le)
        try:
            db.rollback()
        except Exception:
            pass

    # 8. SPEC-AI-086 REQ-AI086-006: scannable_denominator_expanded 명명 토큰(선택, 비영속).
    # prior_scannable_metrics가 제공된 경우에만 계산 — 미제공 시 None(REQ-AI086-007 백워드
    # 호환, 신규 DB 컬럼 없음 — 이 호출 결과 객체에만 존재하는 런타임 속성).
    evaluation.scannable_denominator_expanded = None
    if prior_scannable_metrics is not None:
        try:
            evaluation.scannable_denominator_expanded = classify_scannable_denominator_expansion(
                prev_scannable_actual_count=int(
                    prior_scannable_metrics.get("scannable_actual_count", 0)
                ),
                prev_scan_universe_size=int(
                    prior_scannable_metrics.get("scan_universe_size", 0)
                ),
                curr_scannable_actual_count=scannable_actual_count,
                curr_scan_universe_size=len(universe_set),
            )
            logger.info(
                "[급등평가] scannable_denominator_expanded=%s (분모 %d→%d, scannable_actual %d→%d)",
                evaluation.scannable_denominator_expanded,
                prior_scannable_metrics.get("scan_universe_size", 0), len(universe_set),
                prior_scannable_metrics.get("scannable_actual_count", 0), scannable_actual_count,
            )
        except Exception as _de:
            logger.warning("[급등평가] scannable_denominator_expanded 계산 실패 (무시): %s", _de)
            evaluation.scannable_denominator_expanded = None

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


# ---------------------------------------------------------------------------
# SPEC-AI-092 REQ-AI092-006: 운영 평가 누락 감시
# ---------------------------------------------------------------------------

def detect_missing_evaluation_records(db: Session, trading_date: date) -> dict[str, Any]:
    # @MX:NOTE: [AUTO] SPEC-AI-092 REQ-AI092-006 — 순수 읽기 전용 감지. 부작용이 없으므로
    # 몇 번을 호출해도 동일 결과를 반환한다(idempotent).
    # @MX:SPEC: SPEC-AI-092 REQ-AI092-006
    """당일 surge_actual_outcome/surge_prediction_evaluation 레코드 존재 여부를 감지한다.

    Args:
        db: SQLAlchemy 동기 세션
        trading_date: 확인할 거래일 (보통 오늘 KST)

    Returns:
        {"trading_date": str, "actual_outcome_missing": bool, "evaluation_missing": bool}
    """
    actual_exists = (
        db.query(SurgeActualOutcome.stock_code)
        .filter(SurgeActualOutcome.trading_date == trading_date)
        .first()
        is not None
    )
    evaluation_exists = (
        db.query(SurgePredictionEvaluation.evaluation_date)
        .filter(SurgePredictionEvaluation.evaluation_date == trading_date)
        .first()
        is not None
    )
    return {
        "trading_date": str(trading_date),
        "actual_outcome_missing": not actual_exists,
        "evaluation_missing": not evaluation_exists,
    }


async def _send_missing_evaluation_alert(status: dict[str, Any]) -> bool:
    """SPEC-AI-092 REQ-AI092-006: 텔레그램 admin 채널로 누락 경보를 발송한다.

    TELEGRAM_ADMIN_CHAT_ID 미설정 또는 발송 실패 시 False를 반환한다(fail-open —
    plan.md TASK-006: "알림 연동은 기존 Telegram admin 채널이 있으면 사용하고,
    없으면 warning log로 fail-open한다").
    """
    import os

    from app.services.telegram_service import send_telegram_message

    chat_id = os.environ.get("TELEGRAM_ADMIN_CHAT_ID")
    if not chat_id:
        logger.warning(
            "[급등평가누락감시] TELEGRAM_ADMIN_CHAT_ID 미설정 — 경보 발송 스킵(로그만 기록): %s",
            status,
        )
        return False

    missing_tables = []
    if status.get("actual_outcome_missing"):
        missing_tables.append("surge_actual_outcome")
    if status.get("evaluation_missing"):
        missing_tables.append("surge_prediction_evaluation")

    text = (
        "<b>⚠️ [급등예측 평가 누락 감시]</b>\n"
        f"날짜: {status.get('trading_date')}\n"
        f"누락 테이블: {', '.join(missing_tables) if missing_tables else '(없음)'}"
    )
    try:
        return await send_telegram_message(chat_id=chat_id, text=text, parse_mode="HTML")
    except Exception as exc:
        logger.error("[급등평가누락감시] 텔레그램 발송 예외: %s", exc)
        return False


def check_and_alert_missing_evaluation(
    db: Session,
    trading_date: date | None = None,
) -> dict[str, Any]:
    # @MX:NOTE: [AUTO] SPEC-AI-092 REQ-AI092-006 — 장마감 이후 지정 시각 스케줄러 잡에서
    # 호출되는 진입점. 감지(순수 읽기) + 누락 시 경보(fail-open). 여러 번 호출해도 안전하다
    # (idempotent — 경보 발송 자체는 상태를 변경하지 않으며, 중복 발송 억제는 스케줄러
    # max_instances=1 설정이 담당한다).
    # @MX:SPEC: SPEC-AI-092 REQ-AI092-006
    """당일 평가 누락을 감지하고 필요 시 텔레그램 admin 경보를 발송한다.

    Args:
        db: SQLAlchemy 동기 세션
        trading_date: 확인 대상 날짜. None이면 오늘(KST)을 사용한다.

    Returns:
        detect_missing_evaluation_records()와 동일한 shape의 dict
    """
    if trading_date is None:
        from zoneinfo import ZoneInfo

        trading_date = datetime.now(ZoneInfo("Asia/Seoul")).date()

    status = detect_missing_evaluation_records(db, trading_date)

    if status["actual_outcome_missing"] or status["evaluation_missing"]:
        logger.warning("[급등평가누락감시] 누락 감지: %s", status)
        try:
            asyncio.run(_send_missing_evaluation_alert(status))
        except Exception as exc:
            logger.warning("[급등평가누락감시] 경보 발송 실패 (무시): %s", exc)
    else:
        logger.info("[급등평가누락감시] 누락 없음: date=%s", status["trading_date"])

    return status
