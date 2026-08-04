"""SPEC-AI-099: 피처 스냅샷 정답 라벨 백필 + 축적 상태 카운터.

SurgeFeatureSnapshot(종목별·사이클별 그레인)의 정답 라벨(outcome_*) 백필과
독립적인 축적 상태 카운터를 제공한다. ml_feature_engineering.py의
check_ml_readiness()(MLFeatureSnapshot, 일 단위 집계 그레인)는 무수정으로
둔다 — REQ-AI099-005.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.models.surge_actual_outcome import SurgeActualOutcome
from app.models.surge_feature_snapshot import SurgeFeatureSnapshot

logger = logging.getLogger(__name__)

# SPEC-AI-099 REQ-AI099-005: 기존 ML_READINESS_THRESHOLD_DAYS(90)와 동일한 기준을
# 신규 테이블에 독립적으로 적용한다(고유 스캔 일수 기준).
FEATURE_SNAPSHOT_READINESS_THRESHOLD_DAYS = 90


def _next_trading_date(from_date: date) -> date:
    """다음 거래일을 계산한다 (주말만 건너뜀 — 최소 구현, 공휴일 미처리).

    spec.md §Open Questions 3 / plan.md §E 리스크: 공휴일이 낀 주는 실제로는
    거래가 없는 날을 가리켜 백필이 영구히 NULL로 남을 수 있다 — 이는 잘못된
    라벨을 채우는 것보다 안전한 fail-safe로 간주한다(AC-099-006).
    """
    next_day = from_date + timedelta(days=1)
    while next_day.weekday() >= 5:  # 토(5)/일(6)
        next_day += timedelta(days=1)
    return next_day


def backfill_outcome_labels(db: Session) -> dict:
    """SPEC-AI-099 REQ-AI099-003: 정답 라벨(outcome_change_rate/was_surge)이 아직
    확정되지 않은 스냅샷 행에 SurgeActualOutcome을 조회해 채운다.

    outcome_trading_date가 비어 있으면 scanned_at 기준 다음 거래일로 채운 뒤 조회를
    시도한다. 아직 SurgeActualOutcome이 존재하지 않으면 NULL로 그대로 남긴다
    (AC-099-006 — 0이나 임의값으로 채우지 않는다).
    """
    pending = (
        db.query(SurgeFeatureSnapshot)
        .filter(SurgeFeatureSnapshot.outcome_change_rate.is_(None))
        .all()
    )

    filled = 0
    for snapshot in pending:
        if snapshot.outcome_trading_date is None:
            snapshot.outcome_trading_date = _next_trading_date(snapshot.scanned_at.date())

        outcome = (
            db.query(SurgeActualOutcome)
            .filter(
                SurgeActualOutcome.stock_code == snapshot.stock_code,
                SurgeActualOutcome.trading_date == snapshot.outcome_trading_date,
            )
            .first()
        )
        if outcome is None:
            continue

        snapshot.outcome_change_rate = outcome.change_rate
        snapshot.outcome_was_surge = outcome.was_surge
        filled += 1

    db.commit()
    logger.info(
        "[피처스냅샷백필] 대상=%d개, 채움=%d개",
        len(pending),
        filled,
    )
    return {"scanned": len(pending), "filled": filled}


def check_feature_snapshot_readiness(db: Session) -> dict:
    """SPEC-AI-099 REQ-AI099-005: SurgeFeatureSnapshot 축적 상태를 기존
    check_ml_readiness()(MLFeatureSnapshot, 일 단위 집계)와 독립적으로 계측한다.

    고유 스캔 일수(scanned_at::date)를 90일 기준과 비교해 ready 여부를 반환한다.
    응답 형태는 check_ml_readiness()와 동일하다(ready/days/message).
    """
    unique_days = (
        db.query(
            sa_func.count(sa_func.distinct(sa_func.date(SurgeFeatureSnapshot.scanned_at)))
        ).scalar()
        or 0
    )

    if unique_days >= FEATURE_SNAPSHOT_READINESS_THRESHOLD_DAYS:
        return {
            "ready": True,
            "days": unique_days,
            "message": (
                f"피처 스냅샷 학습 데이터 축적 완료: {unique_days}일분. "
                f"SPEC-AI-099 후속 모델링 SPEC 착수를 검토하세요."
            ),
        }
    return {
        "ready": False,
        "days": unique_days,
        "message": (
            f"피처 스냅샷 축적 중: {unique_days}/{FEATURE_SNAPSHOT_READINESS_THRESHOLD_DAYS}일 "
            f"({FEATURE_SNAPSHOT_READINESS_THRESHOLD_DAYS - unique_days}일 남음)"
        ),
    }
