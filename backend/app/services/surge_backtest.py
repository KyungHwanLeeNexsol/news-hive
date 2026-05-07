"""SPEC-AI-012: 급등 징후 탐지 백테스트 서비스.

surge_candidate 시그널의 적중률, 평균 수익률, 탐지기 조합별 성능을 계산한다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.fund_signal import FundSignal

logger = logging.getLogger(__name__)


@dataclass
class SurgeBacktestResult:
    """백테스트 결과 집계."""

    total_signals: int
    # 방향성 적중률: price_after_5d > price_at_signal 비율
    directional_accuracy: float
    # 평균 5일 수익률 (%)
    average_return_pct: float
    # 탐지기 조합별 통계: {콤보 문자열 -> {count, accuracy, avg_return}}
    by_combination: dict[str, dict] = field(default_factory=dict)


# @MX:ANCHOR: [AUTO] GET /fund/surge-backtest API 경계 — 라우터에서 직접 호출
# @MX:REASON: 공개 API 진입점으로 인터페이스 변경 시 라우터 + 테스트 동시 수정 필요
# @MX:SPEC: SPEC-AI-012
def compute_surge_backtest(
    db: Session,
    *,
    days: int = 30,
) -> SurgeBacktestResult:
    """surge_candidate 시그널 백테스트를 수행한다 (AC-SURGE-006).

    price_after_5d와 price_at_signal이 모두 있는 시그널만 대상.
    검증 기간 내 생성된 시그널의 방향성 적중률과 평균 수익률을 계산한다.

    Args:
        db: SQLAlchemy 동기 세션
        days: 최근 N일 이내 시그널만 분석 (기본 30일)

    Returns:
        SurgeBacktestResult 집계 객체
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    signals = (
        db.query(FundSignal)
        .filter(
            FundSignal.signal_type == "surge_candidate",
            FundSignal.price_at_signal.isnot(None),
            FundSignal.price_after_5d.isnot(None),
            FundSignal.created_at >= cutoff,
        )
        .all()
    )

    if not signals:
        return SurgeBacktestResult(
            total_signals=0,
            directional_accuracy=0.0,
            average_return_pct=0.0,
        )

    total = len(signals)
    correct_count = 0
    total_return = 0.0

    # 탐지기 조합별 집계: {콤보 키 -> {correct, total, returns}}
    combo_stats: dict[str, dict] = {}

    for signal in signals:
        # 방향성 적중 판정: 5일 후 가격 > 시그널 시점 가격
        price_at = signal.price_at_signal or 0
        price_after = signal.price_after_5d or 0

        is_correct = price_after > price_at if price_at > 0 else False
        return_pct = ((price_after - price_at) / price_at * 100) if price_at > 0 else 0.0

        if is_correct:
            correct_count += 1
        total_return += return_pct

        # surge_basis에서 탐지기 조합 추출
        combo_key = _extract_combo_key(signal)

        if combo_key not in combo_stats:
            combo_stats[combo_key] = {"correct": 0, "total": 0, "returns": []}

        combo_stats[combo_key]["total"] += 1
        if is_correct:
            combo_stats[combo_key]["correct"] += 1
        combo_stats[combo_key]["returns"].append(return_pct)

    # 탐지기 조합별 통계 계산
    by_combination: dict[str, dict] = {}
    for combo, stats in combo_stats.items():
        cnt = stats["total"]
        acc = stats["correct"] / cnt if cnt > 0 else 0.0
        avg_ret = sum(stats["returns"]) / cnt if cnt > 0 else 0.0
        by_combination[combo] = {
            "count": cnt,
            "accuracy": round(acc, 4),
            "avg_return": round(avg_ret, 4),
        }

    accuracy = correct_count / total if total > 0 else 0.0
    avg_return = total_return / total if total > 0 else 0.0

    logger.info(
        "[급등백테스트] 총 %d개 시그널, 적중률=%.1f%%, 평균수익률=%.2f%%",
        total,
        accuracy * 100,
        avg_return,
    )

    return SurgeBacktestResult(
        total_signals=total,
        directional_accuracy=round(accuracy, 4),
        average_return_pct=round(avg_return, 4),
        by_combination=by_combination,
    )


def _extract_combo_key(signal: FundSignal) -> str:
    """시그널의 surge_metadata에서 탐지기 조합 키를 추출한다.

    surge_metadata가 없거나 파싱 실패 시 "unknown" 반환.
    """
    if not signal.surge_metadata:
        return "unknown"
    try:
        meta = json.loads(signal.surge_metadata)
        basis = meta.get("surge_basis", [])
        if not basis:
            return "unknown"
        # 정렬하여 순서 무관 동일 조합으로 취급
        return "+".join(sorted(basis))
    except (json.JSONDecodeError, TypeError):
        return "unknown"
