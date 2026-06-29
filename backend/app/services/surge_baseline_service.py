"""SPEC-AI-065 REQ-1: 종목별 탐지기 z-score 기준선 서비스.

Welford's online algorithm으로 30거래일 롤링 통계를 순수 Python으로 계산한다.
numpy/scipy 미사용.

사용 흐름:
    1. get_baselines(db, stock_codes, detector_names) → dict[(code, detector), BaselineStats]
    2. 시그널 점수 계산 완료 후 update_baselines(db, observations) 호출
    3. compute_zscore(raw, stats) → float | None (cold-start 시 None)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import NamedTuple

from sqlalchemy.orm import Session

from app.models.stock_signal_baseline import StockSignalBaseline

logger = logging.getLogger(__name__)

# 최소 샘플 수: 이 이하면 cold-start로 절대값 사용
_DEFAULT_MIN_BASELINE_SAMPLES = 10
# 최대 윈도우 크기 (30거래일)
_MAX_WINDOW = 30


@dataclass
class BaselineStats:
    """Welford's algorithm 누적 통계."""

    rolling_mean: float = 0.0
    rolling_m2: float = 0.0  # 분산 누적 (M2)
    sample_count: int = 0

    @property
    def rolling_std(self) -> float:
        """표본 표준편차 (n-1 방식). sample_count < 2이면 0.0 반환."""
        if self.sample_count < 2:
            return 0.0
        variance = self.rolling_m2 / (self.sample_count - 1)
        return math.sqrt(max(0.0, variance))


class Observation(NamedTuple):
    """탐지기 점수 관측값."""

    stock_code: str
    detector_name: str
    score: float  # 0.0 ~ 1.0 범위의 원시 점수


def compute_zscore(
    raw_score: float,
    stats: BaselineStats,
    min_samples: int = _DEFAULT_MIN_BASELINE_SAMPLES,
) -> float | None:
    """원시 점수에서 z-score를 계산한다.

    cold-start 조건(sample_count < min_samples 또는 rolling_std == 0)이면 None을 반환한다.
    호출자는 None을 받으면 raw_score를 그대로 사용해야 한다 (절대값 fallback).

    Args:
        raw_score: 탐지기에서 계산한 원시 점수 (0.0~1.0)
        stats: 해당 (stock_code, detector_name)의 BaselineStats
        min_samples: cold-start 판단 최소 샘플 수 (기본 10)

    Returns:
        z-score 또는 None (cold-start)
    """
    if stats.sample_count < min_samples:
        return None
    std = stats.rolling_std
    if std == 0.0:
        return None
    return (raw_score - stats.rolling_mean) / std


def zscore_to_score(z: float) -> float:
    """z-score를 sigmoid로 [0, 1] 범위 점수로 변환한다.

    z=0 (평균) → 0.5
    z=2 (2 표준편차 이상) → 0.88
    z=-2 → 0.12
    """
    return 1.0 / (1.0 + math.exp(-z))


def get_baselines(
    db: Session,
    stock_codes: list[str],
    detector_names: list[str],
) -> dict[tuple[str, str], BaselineStats]:
    """(stock_code, detector_name) 쌍의 기준선을 일괄 조회한다.

    결과가 없으면 빈 BaselineStats()를 반환한다.

    Args:
        db: SQLAlchemy 동기 세션
        stock_codes: 조회할 종목 코드 목록
        detector_names: 조회할 탐지기 이름 목록

    Returns:
        {(stock_code, detector_name): BaselineStats} 딕셔너리
    """
    # @MX:NOTE: [AUTO] SPEC-AI-065 REQ-1 — cold-start 기본값(빈 BaselineStats)은 호출자가 처리
    result: dict[tuple[str, str], BaselineStats] = {}

    if not stock_codes or not detector_names:
        return result

    try:
        rows = (
            db.query(StockSignalBaseline)
            .filter(
                StockSignalBaseline.stock_code.in_(stock_codes),
                StockSignalBaseline.detector_name.in_(detector_names),
            )
            .all()
        )
        for row in rows:
            key = (row.stock_code, row.detector_name)
            result[key] = BaselineStats(
                rolling_mean=row.rolling_mean,
                rolling_m2=row.rolling_m2,
                sample_count=row.sample_count,
            )
    except Exception as e:
        logger.warning("[baseline] 기준선 조회 실패 (fail-open): %s", e)

    return result


def update_baselines(
    db: Session,
    observations: list[Observation],
    max_window: int = _MAX_WINDOW,
) -> None:
    """관측값으로 기준선 롤링 통계를 업데이트한다.

    Welford's online algorithm을 사용하여 분산을 수치적으로 안정적으로 계산한다.
    max_window 이상의 샘플은 오래된 것부터 지수 감쇠(EMA-style) 방식으로 반영한다.

    Args:
        db: SQLAlchemy 동기 세션
        observations: (stock_code, detector_name, score) 관측값 목록
        max_window: 최대 윈도우 크기 (기본 30)
    """
    if not observations:
        return

    try:
        # 기존 기준선 일괄 조회
        codes = list({o.stock_code for o in observations})
        detectors = list({o.detector_name for o in observations})

        existing_map: dict[tuple[str, str], StockSignalBaseline] = {}
        rows = (
            db.query(StockSignalBaseline)
            .filter(
                StockSignalBaseline.stock_code.in_(codes),
                StockSignalBaseline.detector_name.in_(detectors),
            )
            .all()
        )
        for row in rows:
            existing_map[(row.stock_code, row.detector_name)] = row

        for obs in observations:
            key = (obs.stock_code, obs.detector_name)
            row = existing_map.get(key)

            if row is None:
                # 신규 생성
                row = StockSignalBaseline(
                    stock_code=obs.stock_code,
                    detector_name=obs.detector_name,
                    rolling_mean=0.0,
                    rolling_m2=0.0,
                    sample_count=0,
                )
                db.add(row)

            # Welford's online update
            n = min(row.sample_count + 1, max_window)
            old_mean = row.rolling_mean
            # EMA-style: 윈도우 포화 시 새 샘플 가중치 = 1/max_window
            alpha = 1.0 / n
            new_mean = old_mean + alpha * (obs.score - old_mean)
            # M2 업데이트 (분산 누적)
            delta = obs.score - old_mean
            delta2 = obs.score - new_mean
            new_m2 = row.rolling_m2 + delta * delta2
            # 윈도우 포화 시 분산도 EMA 감쇠 (신선도 유지)
            if row.sample_count >= max_window:
                new_m2 = row.rolling_m2 * (1 - alpha) + delta * delta2 * alpha

            row.rolling_mean = new_mean
            row.rolling_m2 = max(0.0, new_m2)
            row.sample_count = n

        db.flush()
        logger.debug("[baseline] %d개 기준선 업데이트 완료", len(observations))

    except Exception as e:
        logger.warning("[baseline] 기준선 업데이트 실패 (무시): %s", e)
