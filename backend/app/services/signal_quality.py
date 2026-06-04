"""SPEC-AI-036 M4: 시그널 품질 지표 서비스.

composite_score 채움률, confidence 분포, Brier Score, ECE를 제공한다.
DB 예외 발생 시 insufficient_data 상태로 응답 (HTTP 에러 전파 없음).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.fund_signal import FundSignal

logger = logging.getLogger(__name__)

# confidence 버킷 경계 (10개 버킷, 각 0.1 폭)
_BUCKET_COUNT = 10


def _bucket_index(val: float) -> int:
    """0.0~1.0 값을 0~9 버킷 인덱스로 변환한다."""
    idx = int(val * _BUCKET_COUNT)
    return min(idx, _BUCKET_COUNT - 1)


def get_signal_quality_metrics(db: Session, lookback_days: int = 30) -> dict:
    """SPEC-AI-036 M4: 시그널 품질 지표를 반환한다.

    # @MX:NOTE: router의 GET /api/fund/signal-quality 엔드포인트에서 호출.
    # 모든 DB 예외를 catch하여 insufficient_data 상태 반환 → HTTP 에러 전파 안 함.
    # REQ-036-004 준수: surge와 llm의 composite_score 스케일 분리 보고.

    Args:
        db: SQLAlchemy Session
        lookback_days: 조회 기간 (일), 기본 30

    Returns:
        {
            "status": "ok" | "insufficient_data",
            "confidence_distribution": {bucket_label: count, ...},
            "composite_score_fill_rate": float (0.0~1.0),
            "brier_score": float | None,
            "ece": float | None,
            "sample_counts": {"total_surge": int, "verified": int},
            "scale_info": {
                "surge": "0.0~1.0",
                "llm": "0~100"
            }
        }
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    try:
        # 전체 surge_candidate 시그널
        total_surges = (
            db.query(FundSignal)
            .filter(
                FundSignal.signal_type == "surge_candidate",
                FundSignal.created_at >= cutoff,
            )
            .all()
        )

        total_count = len(total_surges)

        if total_count == 0:
            return {
                "status": "insufficient_data",
                "reason": "surge_candidate 시그널 없음",
                "composite_score_fill_rate": 0.0,
                "confidence_distribution": {},
                "brier_score": None,
                "ece": None,
                "sample_counts": {"total_surge": 0, "verified": 0},
                "scale_info": {"surge": "0.0~1.0", "llm": "0~100"},
            }

        # composite_score 채움률
        filled = sum(1 for s in total_surges if s.composite_score is not None)
        fill_rate = round(filled / total_count, 4) if total_count else 0.0

        # confidence 분포 (10개 버킷)
        bucket_counts: dict[str, int] = {}
        for i in range(_BUCKET_COUNT):
            lo = i / _BUCKET_COUNT
            hi = (i + 1) / _BUCKET_COUNT
            label = f"[{lo:.1f},{hi:.1f})"
            bucket_counts[label] = 0

        for s in total_surges:
            idx = _bucket_index(s.confidence)
            lo = idx / _BUCKET_COUNT
            hi = (idx + 1) / _BUCKET_COUNT
            label = f"[{lo:.1f},{hi:.1f})"
            bucket_counts[label] = bucket_counts.get(label, 0) + 1

        # 검증된 surge_candidate (is_correct 확정)
        verified = [
            s for s in total_surges
            if s.is_correct is not None and s.verified_at is not None
        ]
        verified_count = len(verified)

        brier_score: float | None = None
        ece: float | None = None

        if verified_count >= 10:
            # Brier Score: mean((predicted - actual)^2)
            brier_sum = 0.0
            for s in verified:
                actual = 1.0 if s.is_correct else 0.0
                predicted = s.confidence
                brier_sum += (predicted - actual) ** 2
            brier_score = round(brier_sum / verified_count, 6)

            # ECE: |avg_confidence - fraction_correct| per bucket
            bucket_pred: dict[int, list[float]] = {}
            bucket_act: dict[int, list[float]] = {}
            for s in verified:
                idx = _bucket_index(s.confidence)
                bucket_pred.setdefault(idx, []).append(s.confidence)
                bucket_act.setdefault(idx, []).append(1.0 if s.is_correct else 0.0)

            ece_sum = 0.0
            for idx in bucket_pred:
                preds = bucket_pred[idx]
                acts = bucket_act.get(idx, [])
                if not preds or not acts:
                    continue
                avg_pred = sum(preds) / len(preds)
                avg_act = sum(acts) / len(acts)
                ece_sum += abs(avg_pred - avg_act) * len(preds) / verified_count
            ece = round(ece_sum, 6)

        return {
            "status": "ok",
            "confidence_distribution": bucket_counts,
            "composite_score_fill_rate": fill_rate,
            "brier_score": brier_score,
            "ece": ece,
            "sample_counts": {
                "total_surge": total_count,
                "verified": verified_count,
            },
            "scale_info": {"surge": "0.0~1.0", "llm": "0~100"},
        }

    except Exception:
        logger.warning("get_signal_quality_metrics 실패", exc_info=True)
        return {
            "status": "insufficient_data",
            "reason": "내부 오류",
            "composite_score_fill_rate": None,
            "confidence_distribution": {},
            "brier_score": None,
            "ece": None,
            "sample_counts": {"total_surge": 0, "verified": 0},
            "scale_info": {"surge": "0.0~1.0", "llm": "0~100"},
        }
