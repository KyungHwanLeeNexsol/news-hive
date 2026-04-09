"""AI 자기개선 피드백 루프 서비스 — SPEC-AI-006.

검증된 시그널 데이터를 분석하여 프롬프트와 팩터 가중치를 자동 개선한다.
개선 루프 주기:
  - 실패 패턴 집계: 매일 18:30 KST
  - 프롬프트 개선: 매주 일요일 22:00 KST
  - A/B 테스트 평가: 매주 일요일 22:30 KST
  - 팩터 가중치 조정: 매월 1일 23:00 KST
"""
import json
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.factor_weight import FactorWeightHistory
from app.models.fund_signal import FundSignal
from app.models.improvement_log import ImprovementLog
from app.models.prompt_version import PromptVersion
from app.services.factor_scoring import DEFAULT_WEIGHTS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 실패 패턴 집계
# ---------------------------------------------------------------------------

async def aggregate_failure_patterns(db: Session, days: int = 30) -> dict | None:
    """최근 ``days``일간 검증된 시그널을 집계하여 실패 패턴을 분석한다.

    Args:
        db: SQLAlchemy 세션
        days: 분석 기간 (일)

    Returns:
        집계 결과 dict 또는 검증 시그널 부족 시 None.
        키: total_verified, accuracy_rate, error_category_dist,
            signal_type_accuracy, avg_return_correct, avg_return_incorrect,
            factor_score_avg, low_accuracy_signal_types
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # 검증 완료된 시그널 조회
    signals = (
        db.query(FundSignal)
        .filter(
            FundSignal.verified_at.isnot(None),
            FundSignal.is_correct.isnot(None),
            FundSignal.created_at >= cutoff,
        )
        .all()
    )

    # 최소 5건 미만이면 분석 불가
    if len(signals) < 5:
        logger.info("실패 패턴 집계: 검증 시그널 %d건 (최소 5건 필요)", len(signals))
        return None

    total = len(signals)
    correct_count = sum(1 for s in signals if s.is_correct)
    accuracy_rate = correct_count / total if total > 0 else 0.0

    # 오류 카테고리 분포
    error_category_dist: dict[str, int] = {}
    for s in signals:
        if not s.is_correct and s.error_category:
            error_category_dist[s.error_category] = error_category_dist.get(s.error_category, 0) + 1

    # 시그널 유형별 적중률
    signal_type_accuracy: dict[str, dict[str, Any]] = {}
    for s in signals:
        stype = s.signal_type or s.signal  # signal_type 없으면 buy/sell/hold 사용
        if stype not in signal_type_accuracy:
            signal_type_accuracy[stype] = {"total": 0, "correct": 0, "accuracy": 0.0}
        signal_type_accuracy[stype]["total"] += 1
        if s.is_correct:
            signal_type_accuracy[stype]["correct"] += 1

    for stype, data in signal_type_accuracy.items():
        if data["total"] > 0:
            data["accuracy"] = data["correct"] / data["total"]

    # 적중/미적중별 평균 수익률
    returns_correct = [s.return_pct for s in signals if s.is_correct and s.return_pct is not None]
    returns_incorrect = [s.return_pct for s in signals if not s.is_correct and s.return_pct is not None]

    avg_return_correct = sum(returns_correct) / len(returns_correct) if returns_correct else 0.0
    avg_return_incorrect = sum(returns_incorrect) / len(returns_incorrect) if returns_incorrect else 0.0

    # 팩터 점수 평균 (적중/미적중 분리)
    factor_score_avg: dict[str, dict[str, float]] = {}
    factor_keys = ["news_sentiment", "technical", "supply_demand", "valuation"]

    for factor in factor_keys:
        correct_scores = []
        incorrect_scores = []
        for s in signals:
            if s.factor_scores:
                try:
                    scores_dict = json.loads(s.factor_scores)
                    score_val = scores_dict.get(factor)
                    if score_val is not None:
                        if s.is_correct:
                            correct_scores.append(float(score_val))
                        else:
                            incorrect_scores.append(float(score_val))
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass
        factor_score_avg[factor] = {
            "correct_avg": sum(correct_scores) / len(correct_scores) if correct_scores else 0.0,
            "incorrect_avg": sum(incorrect_scores) / len(incorrect_scores) if incorrect_scores else 0.0,
        }

    # 적중률 50% 미만 + 5건 이상인 시그널 유형
    low_accuracy_signal_types = [
        stype
        for stype, data in signal_type_accuracy.items()
        if data["total"] >= 5 and data["accuracy"] < 0.5
    ]

    return {
        "total_verified": total,
        "accuracy_rate": round(accuracy_rate, 4),
        "error_category_dist": error_category_dist,
        "signal_type_accuracy": signal_type_accuracy,
        "avg_return_correct": round(avg_return_correct, 2),
        "avg_return_incorrect": round(avg_return_incorrect, 2),
        "factor_score_avg": factor_score_avg,
        "low_accuracy_signal_types": low_accuracy_signal_types,
    }


# ---------------------------------------------------------------------------
# AI 프롬프트 자동 생성
# ---------------------------------------------------------------------------

async def generate_improved_prompt(db: Session, failure_summary: dict) -> str | None:
    """실패 패턴 요약을 바탕으로 Gemini에게 개선된 프롬프트를 생성 요청한다.

    Args:
        db: SQLAlchemy 세션
        failure_summary: aggregate_failure_patterns()의 반환 결과

    Returns:
        개선된 프롬프트 텍스트, 실패 시 None.
    """
    from app.services.ai_client import ask_ai_free as _ask_ai

    # 현재 활성 프롬프트 템플릿 조회 (없으면 기본 안내 사용)
    current_template = _get_current_prompt_template(db)

    # 최저 성과 시그널 유형 상위 5개 추출 (적중률 기준 오름차순)
    signal_accuracy = failure_summary.get("signal_type_accuracy", {})
    worst_signals = sorted(
        [
            (stype, data)
            for stype, data in signal_accuracy.items()
            if data["total"] >= 3
        ],
        key=lambda x: x[1]["accuracy"],
    )[:5]

    worst_signals_text = "\n".join(
        f"- {stype}: 적중률 {data['accuracy'] * 100:.1f}% ({data['correct']}/{data['total']}건)"
        for stype, data in worst_signals
    )

    error_dist_text = "\n".join(
        f"- {cat}: {cnt}건"
        for cat, cnt in failure_summary.get("error_category_dist", {}).items()
    )

    meta_prompt = f"""당신은 AI 투자 시그널 시스템의 프롬프트 엔지니어입니다.

## 현재 프롬프트 (일부)
{current_template[:2000] if current_template else "(기본 프롬프트 사용 중)"}

## 최근 30일 성과 분석
- 전체 검증 시그널: {failure_summary.get("total_verified", 0)}건
- 전체 적중률: {failure_summary.get("accuracy_rate", 0) * 100:.1f}%
- 적중 시 평균 수익률: {failure_summary.get("avg_return_correct", 0):.2f}%
- 미적중 시 평균 수익률: {failure_summary.get("avg_return_incorrect", 0):.2f}%

## 주요 실패 유형
{error_dist_text if error_dist_text else "(실패 유형 없음)"}

## 저성과 시그널 유형 (적중률 하위 5개)
{worst_signals_text if worst_signals_text else "(데이터 없음)"}

## 요청사항
위 실패 패턴을 분석하여 투자 시그널 생성 프롬프트를 개선해주세요.
개선된 프롬프트는 아래 조건을 반드시 충족해야 합니다:
1. 현재 프롬프트의 CoT(Chain-of-Thought) 5단계 구조 유지
2. 주요 실패 유형을 방지하는 구체적 지시사항 추가
3. 저성과 시그널 유형에 대한 주의 사항 포함
4. 한국어로 작성

개선된 프롬프트 전문을 반환하세요. 설명 없이 프롬프트 내용만 반환하세요."""

    try:
        result = await _ask_ai(meta_prompt)
        if result and len(result.strip()) > 100:
            return result.strip()
        logger.warning("AI 프롬프트 생성 결과 너무 짧음: %d자", len(result) if result else 0)
        return None
    except Exception as e:
        logger.error("AI 프롬프트 생성 실패: %s", e)
        return None


def _get_current_prompt_template(db: Session) -> str | None:
    """현재 활성 대조군 프롬프트 템플릿을 반환한다."""
    version = (
        db.query(PromptVersion)
        .filter(
            PromptVersion.template_key == "signal",
            PromptVersion.is_active == True,  # noqa: E712
            PromptVersion.is_control == True,  # noqa: E712
            PromptVersion.prompt_template.isnot(None),
        )
        .first()
    )
    return version.prompt_template if version else None


# ---------------------------------------------------------------------------
# 새 프롬프트 버전 등록
# ---------------------------------------------------------------------------

async def register_treatment_version(
    db: Session, prompt_text: str, rationale: str
) -> PromptVersion:
    """개선된 프롬프트를 새 실험군 PromptVersion으로 등록한다.

    Args:
        db: SQLAlchemy 세션
        prompt_text: AI가 생성한 개선 프롬프트 텍스트
        rationale: 생성 근거 설명 (실패 요약 포함)

    Returns:
        생성된 PromptVersion 객체
    """
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")

    # 버전 번호 결정 (기존 최대 버전 + 1)
    existing = db.query(PromptVersion).filter(
        PromptVersion.template_key == "signal"
    ).all()
    next_ver = len(existing) + 1

    version_name = f"v{next_ver}-ai-generated-{today_str}"

    # 기존 실험군(treatment) 비활성화
    old_treatment = (
        db.query(PromptVersion)
        .filter(
            PromptVersion.template_key == "signal",
            PromptVersion.is_active == True,  # noqa: E712
            PromptVersion.is_control == False,  # noqa: E712
        )
        .first()
    )
    if old_treatment:
        old_treatment.is_active = False
        logger.info("기존 실험군 비활성화: %s", old_treatment.version_name)

    # 새 실험군 등록
    new_version = PromptVersion(
        version_name=version_name,
        description=f"AI 자동 생성 — {today_str}",
        template_key="signal",
        is_active=True,
        is_control=False,
        prompt_template=prompt_text,
        generation_source=json.dumps({"rationale": rationale}, ensure_ascii=False),
    )
    db.add(new_version)

    # 개선 로그 기록
    _log_improvement(
        db,
        action_type="prompt_generation",
        details={
            "version_name": version_name,
            "prompt_length": len(prompt_text),
            "rationale_summary": rationale[:200],
        },
    )

    db.commit()
    db.refresh(new_version)
    logger.info("새 실험군 프롬프트 등록: %s", version_name)
    return new_version


# ---------------------------------------------------------------------------
# 팩터 가중치 자동 조정
# ---------------------------------------------------------------------------

async def adapt_factor_weights(db: Session, days: int = 60) -> dict | None:
    """검증된 시그널 데이터를 바탕으로 팩터 가중치를 조정한다.

    알고리즘:
    1. 최근 ``days``일간 factor_scores가 있는 검증 시그널 조회
    2. 팩터별 피어슨 상관계수 (팩터 점수 vs is_correct) 계산
    3. 상관계수를 정규화하여 가중치로 변환 (합산=1.0, 각 0.10~0.40)
    4. 급격한 변화 방지: 변화량 > 0.10이면 반걸음 적용
    5. DB에 새 FactorWeightHistory 저장

    Args:
        db: SQLAlchemy 세션
        days: 분석 기간 (일)

    Returns:
        새 가중치 dict 또는 데이터 부족 시 None.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # factor_scores가 있는 검증 완료 시그널 조회
    signals = (
        db.query(FundSignal)
        .filter(
            FundSignal.verified_at.isnot(None),
            FundSignal.is_correct.isnot(None),
            FundSignal.factor_scores.isnot(None),
            FundSignal.created_at >= cutoff,
        )
        .all()
    )

    if len(signals) < 30:
        logger.info("팩터 가중치 조정: 검증 시그널 %d건 (최소 30건 필요)", len(signals))
        return None

    factor_keys = ["news_sentiment", "technical", "supply_demand", "valuation"]

    # 각 팩터별 (점수, is_correct) 쌍 수집
    factor_data: dict[str, list[tuple[float, int]]] = {k: [] for k in factor_keys}

    for s in signals:
        try:
            scores_dict = json.loads(s.factor_scores)
        except (json.JSONDecodeError, TypeError):
            continue
        is_correct_val = 1 if s.is_correct else 0
        for factor in factor_keys:
            score_val = scores_dict.get(factor)
            if score_val is not None:
                try:
                    factor_data[factor].append((float(score_val), is_correct_val))
                except (TypeError, ValueError):
                    pass

    # 팩터별 피어슨 상관계수 계산
    correlations: dict[str, float] = {}
    for factor, pairs in factor_data.items():
        if len(pairs) < 10:
            correlations[factor] = 0.0
            continue
        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        corr = _pearson_correlation(xs, ys)
        correlations[factor] = corr if not math.isnan(corr) else 0.0

    # 상관계수를 가중치로 변환 (음수를 0으로 처리 후 정규화)
    raw_weights = {k: max(0.0, correlations[k] + 0.5) for k in factor_keys}  # 최소 0.5 기반
    total_raw = sum(raw_weights.values())

    if total_raw <= 0:
        logger.warning("팩터 가중치 조정: 모든 상관계수가 0 이하 — 기본 가중치 유지")
        return None

    # 정규화 + 범위 제한 [0.10, 0.40]
    normalized = {k: raw_weights[k] / total_raw for k in factor_keys}
    clamped = {k: max(0.10, min(0.40, normalized[k])) for k in factor_keys}

    # 합산이 1.0이 되도록 재조정
    total_clamped = sum(clamped.values())
    target_weights = {k: clamped[k] / total_clamped for k in factor_keys}

    # 현재 활성 가중치 조회
    current_weights = get_active_factor_weights(db)

    # 급격한 변화 방지: 변화량 > 0.10이면 반걸음 적용 (dampening)
    final_weights: dict[str, float] = {}
    dampening_applied = False
    for factor in factor_keys:
        change = abs(target_weights[factor] - current_weights[factor])
        if change > 0.10:
            dampening_applied = True
            # 현재값에서 목표값 방향으로 절반만 이동
            final_weights[factor] = current_weights[factor] + (
                target_weights[factor] - current_weights[factor]
            ) * 0.5
        else:
            final_weights[factor] = target_weights[factor]

    # 최종 합산이 1.0이 되도록 정규화
    total_final = sum(final_weights.values())
    final_weights = {k: round(v / total_final, 4) for k, v in final_weights.items()}
    # 반올림 오차 보정 (가장 큰 팩터에 잔여 부여)
    diff = 1.0 - sum(final_weights.values())
    if abs(diff) > 0.0001:
        max_factor = max(final_weights, key=final_weights.get)
        final_weights[max_factor] = round(final_weights[max_factor] + diff, 4)

    # 기존 활성 가중치 비활성화
    old_active = (
        db.query(FactorWeightHistory)
        .filter(FactorWeightHistory.is_active == True)  # noqa: E712
        .first()
    )
    if old_active:
        old_active.is_active = False

    # 새 가중치 저장
    new_weight = FactorWeightHistory(
        news_sentiment=final_weights["news_sentiment"],
        technical=final_weights["technical"],
        supply_demand=final_weights["supply_demand"],
        valuation=final_weights["valuation"],
        correlations=json.dumps(correlations),
        sample_size=len(signals),
        is_active=True,
    )
    db.add(new_weight)

    # 개선 로그 기록
    _log_improvement(
        db,
        action_type="weight_update",
        details={
            "previous_weights": current_weights,
            "new_weights": final_weights,
            "correlations": correlations,
            "sample_size": len(signals),
            "dampening_applied": dampening_applied,
        },
    )

    db.commit()
    logger.info(
        "팩터 가중치 조정 완료: %s (dampening=%s, samples=%d)",
        final_weights,
        dampening_applied,
        len(signals),
    )
    return final_weights


def get_active_factor_weights(db: Session) -> dict[str, float]:
    """현재 활성 팩터 가중치를 반환한다.

    DB에 활성 가중치가 없으면 DEFAULT_WEIGHTS를 반환한다.

    Args:
        db: SQLAlchemy 세션

    Returns:
        팩터 가중치 dict (합산=1.0)
    """
    active = (
        db.query(FactorWeightHistory)
        .filter(FactorWeightHistory.is_active == True)  # noqa: E712
        .first()
    )
    if active is None:
        return dict(DEFAULT_WEIGHTS)

    return {
        "news_sentiment": active.news_sentiment,
        "technical": active.technical,
        "supply_demand": active.supply_demand,
        "valuation": active.valuation,
    }


# ---------------------------------------------------------------------------
# 오래된 A/B 테스트 종료
# ---------------------------------------------------------------------------

async def resolve_stale_ab_test(db: Session, max_days: int = 30) -> bool:
    """통계적 유의성 없이 max_days를 초과한 A/B 테스트를 미결론으로 종료한다.

    Args:
        db: SQLAlchemy 세션
        max_days: 최대 실험 기간 (일)

    Returns:
        종료 처리 여부 (True = 미결론 종료, False = 활성 실험 없거나 아직 기간 내)
    """
    # 활성 실험군 조회
    treatment = (
        db.query(PromptVersion)
        .filter(
            PromptVersion.template_key == "signal",
            PromptVersion.is_active == True,  # noqa: E712
            PromptVersion.is_control == False,  # noqa: E712
        )
        .first()
    )

    if treatment is None:
        logger.debug("종료 대상 A/B 테스트 없음")
        return False

    # 실험 기간 확인
    created = treatment.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    elapsed_days = (datetime.now(timezone.utc) - created).days

    if elapsed_days <= max_days:
        logger.info(
            "A/B 테스트 진행 중: %s (%d일 경과, 최대 %d일)",
            treatment.version_name,
            elapsed_days,
            max_days,
        )
        return False

    # 미결론 — 실험군 비활성화
    treatment.is_active = False
    _log_improvement(
        db,
        action_type="ab_resolution",
        details={
            "version": treatment.version_name,
            "result": "inconclusive",
            "elapsed_days": elapsed_days,
            "max_days": max_days,
        },
    )
    db.commit()
    logger.info(
        "A/B 테스트 미결론 종료: %s (%d일 경과)", treatment.version_name, elapsed_days
    )
    return True


# ---------------------------------------------------------------------------
# 모델 건강 상태 조회
# ---------------------------------------------------------------------------

def get_model_health(db: Session) -> dict:
    """AI 모델의 종합 건강 상태를 반환한다.

    Returns:
        dict 키:
        - current_prompt_version: 현재 대조군 프롬프트 버전명
        - prompt_accuracy_30d: 최근 30일 적중률 (float)
        - ab_test_active: A/B 테스트 활성 여부 (bool)
        - ab_test_status: 활성 A/B 테스트 정보 (dict, 없으면 None)
        - factor_weights: 현재 vs 기본 가중치 비교
        - signal_type_accuracy: 시그널 유형별 적중률
        - improvement_history: 최근 10건 개선 이력
    """
    from app.services.prompt_versioner import get_ab_versions

    # 현재 대조군 버전
    control, treatment = get_ab_versions(db)

    # 최근 30일 적중률
    cutoff_30d = datetime.now(timezone.utc) - timedelta(days=30)
    signals_30d = (
        db.query(FundSignal)
        .filter(
            FundSignal.verified_at.isnot(None),
            FundSignal.is_correct.isnot(None),
            FundSignal.created_at >= cutoff_30d,
        )
        .all()
    )
    accuracy_30d = 0.0
    if signals_30d:
        accuracy_30d = sum(1 for s in signals_30d if s.is_correct) / len(signals_30d)

    # A/B 테스트 상태
    ab_test_active = treatment is not None
    ab_test_status = None
    if ab_test_active:
        treatment_ver = (
            db.query(PromptVersion)
            .filter(PromptVersion.version_name == treatment)
            .first()
        )
        ab_test_status = {
            "control": control,
            "treatment": treatment,
            "started_at": treatment_ver.created_at.isoformat() if treatment_ver and treatment_ver.created_at else None,
        }

    # 현재 팩터 가중치
    current_weights = get_active_factor_weights(db)
    factor_weights = {
        "current": current_weights,
        "default": dict(DEFAULT_WEIGHTS),
        "is_customized": current_weights != dict(DEFAULT_WEIGHTS),
    }

    # 시그널 유형별 적중률 (30일)
    signal_type_accuracy: dict[str, dict[str, Any]] = {}
    for s in signals_30d:
        stype = s.signal_type or s.signal
        if stype not in signal_type_accuracy:
            signal_type_accuracy[stype] = {"total": 0, "correct": 0, "accuracy": 0.0}
        signal_type_accuracy[stype]["total"] += 1
        if s.is_correct:
            signal_type_accuracy[stype]["correct"] += 1
    for stype, data in signal_type_accuracy.items():
        if data["total"] > 0:
            data["accuracy"] = round(data["correct"] / data["total"], 4)

    # 최근 10건 개선 이력
    recent_logs = (
        db.query(ImprovementLog)
        .order_by(ImprovementLog.created_at.desc())
        .limit(10)
        .all()
    )
    improvement_history = [
        {
            "id": log.id,
            "action_type": log.action_type,
            "details": log.details,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in recent_logs
    ]

    return {
        "current_prompt_version": control,
        "prompt_accuracy_30d": round(accuracy_30d, 4),
        "ab_test_active": ab_test_active,
        "ab_test_status": ab_test_status,
        "factor_weights": factor_weights,
        "signal_type_accuracy": signal_type_accuracy,
        "improvement_history": improvement_history,
    }


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------

def _pearson_correlation(xs: list[float], ys: list[float]) -> float:
    """두 리스트 간의 피어슨 상관계수를 계산한다.

    Args:
        xs: 독립 변수 (팩터 점수)
        ys: 종속 변수 (is_correct 0/1)

    Returns:
        피어슨 상관계수 (-1.0 ~ 1.0), 계산 불가 시 0.0
    """
    n = len(xs)
    if n != len(ys) or n < 2:
        return 0.0

    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    cov = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
    std_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    std_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))

    if std_x == 0 or std_y == 0:
        return 0.0

    return cov / (std_x * std_y)


def _log_improvement(db: Session, action_type: str, details: dict) -> None:
    """ImprovementLog 레코드를 추가한다 (commit 없음 — 호출자가 커밋).

    Args:
        db: SQLAlchemy 세션
        action_type: 작업 유형 (prompt_generation / ab_resolution / weight_update / failure_aggregation)
        details: 상세 내용 dict (JSON 직렬화하여 저장)
    """
    log = ImprovementLog(
        action_type=action_type,
        details=json.dumps(details, ensure_ascii=False, default=str),
    )
    db.add(log)
