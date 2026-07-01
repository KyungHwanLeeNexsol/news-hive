"""SPEC-AI-065 REQ-5: 스캔 유니버스 pool 집계 영속화 서비스.

gather_surge_candidates()가 라이브 시그널 생성(10:00/15:20 KST) 중
build_scan_universe()로 계산한 Pool A/B/C 집계는 기존에는 개별 후보
entry_pool 태깅에만 쓰이고 그 자체는 어디에도 저장되지 않았다.

이 서비스는 해당 pool_counts를 날짜별로 저장하고, 이후 예측 평가 잡
(18:30 KST, _run_surge_verify_predictions)이 T-1(예측일) 값을 조회하여
evaluate_surge_predictions()의 pool_counts 인자로 전달할 수 있게 한다.

SQLite/PostgreSQL 양쪽에서 동작하도록 postgres 전용 upsert 대신
조회 후 갱신/삽입하는 방식을 사용한다 (일 1~2회만 기록되므로 경합 위험 낮음).
"""

import logging
from datetime import date

from sqlalchemy.orm import Session

from app.models.surge_universe_pool_history import SurgeUniversePoolHistory

logger = logging.getLogger(__name__)


def persist_pool_counts(
    db: Session,
    pool_date: date,
    pool_counts: dict,
) -> SurgeUniversePoolHistory:
    """pool_counts를 surge_universe_pool_history 테이블에 upsert한다.

    date 컬럼의 UNIQUE 제약 덕분에 동일 날짜 재실행(10:00, 15:20 등)
    시 기존 레코드를 최신 값으로 갱신한다 (idempotent 보장).

    Args:
        db: SQLAlchemy 세션
        pool_date: 집계 기준 날짜
        pool_counts: {"pool_a": int, "pool_b": int, "pool_c": int, "scan_universe_size": int}

    Returns:
        저장된 SurgeUniversePoolHistory 인스턴스
    """
    values = {
        "pool_a_count": int(pool_counts.get("pool_a", 0) or 0),
        "pool_b_count": int(pool_counts.get("pool_b", 0) or 0),
        "pool_c_count": int(pool_counts.get("pool_c", 0) or 0),
        "scan_universe_size": int(pool_counts.get("scan_universe_size", 0) or 0),
    }

    existing = (
        db.query(SurgeUniversePoolHistory)
        .filter(SurgeUniversePoolHistory.date == pool_date)
        .first()
    )
    if existing is not None:
        for key, value in values.items():
            setattr(existing, key, value)
        db.flush()
        row = existing
    else:
        row = SurgeUniversePoolHistory(date=pool_date, **values)
        db.add(row)
        db.flush()

    logger.info(
        "[스캔유니버스] pool_counts 영속화 완료 — date=%s, A=%d B=%d C=%d size=%d",
        pool_date,
        values["pool_a_count"],
        values["pool_b_count"],
        values["pool_c_count"],
        values["scan_universe_size"],
    )
    return row


def get_pool_counts_for_date(db: Session, target_date: date) -> dict | None:
    """지정 날짜의 저장된 pool_counts를 조회한다.

    Args:
        db: SQLAlchemy 세션
        target_date: 조회 대상 날짜 (보통 T-1, 예측일)

    Returns:
        {"pool_a": int, "pool_b": int, "pool_c": int, "scan_universe_size": int}
        레코드가 없으면 None (호출부는 fail-open으로 pool_counts=None 처리)
    """
    row = (
        db.query(SurgeUniversePoolHistory)
        .filter(SurgeUniversePoolHistory.date == target_date)
        .first()
    )
    if row is None:
        return None

    return {
        "pool_a": row.pool_a_count or 0,
        "pool_b": row.pool_b_count or 0,
        "pool_c": row.pool_c_count or 0,
        "scan_universe_size": row.scan_universe_size or 0,
    }
