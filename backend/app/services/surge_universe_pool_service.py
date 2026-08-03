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

from app.models.surge_universe_member import SurgeUniverseMember
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
        pool_counts: {"pool_a": int, "pool_b": int, "pool_c": int, "pool_d": int,
            "scan_universe_size": int} — "pool_d" 키는 SPEC-AI-096 REQ-AI096-002 신규
            항목이며, 없으면 하위 호환으로 0 처리한다.

    Returns:
        저장된 SurgeUniversePoolHistory 인스턴스
    """
    values = {
        "pool_a_count": int(pool_counts.get("pool_a", 0) or 0),
        "pool_b_count": int(pool_counts.get("pool_b", 0) or 0),
        "pool_c_count": int(pool_counts.get("pool_c", 0) or 0),
        "pool_d_count": int(pool_counts.get("pool_d", 0) or 0),
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
        "[스캔유니버스] pool_counts 영속화 완료 — date=%s, A=%d B=%d C=%d D=%d size=%d",
        pool_date,
        values["pool_a_count"],
        values["pool_b_count"],
        values["pool_c_count"],
        values["pool_d_count"],
        values["scan_universe_size"],
    )
    return row


def get_pool_counts_for_date(db: Session, target_date: date) -> dict | None:
    """지정 날짜의 저장된 pool_counts를 조회한다.

    Args:
        db: SQLAlchemy 세션
        target_date: 조회 대상 날짜 (보통 T-1, 예측일)

    Returns:
        {"pool_a": int, "pool_b": int, "pool_c": int, "pool_d": int,
        "scan_universe_size": int}
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
        "pool_d": row.pool_d_count or 0,
        "scan_universe_size": row.scan_universe_size or 0,
    }


def persist_universe_members(
    db: Session,
    trading_date: date,
    universe_codes: list[str],
    entry_pool_map: dict[str, str],
) -> int:
    # @MX:NOTE: [AUTO] SPEC-AI-068 REQ-001 — 스캔 유니버스 종목코드 영속화. 일자당
    # replace(DELETE-then-insert) semantics — 단순 upsert가 아님에 유의.
    # @MX:REASON: 동일 날짜 재실행(예: 10:00 → 15:20 유니버스 축소) 시 이전 실행의
    # 스테일 종목코드가 잔존하면 Scannable Recall/Coverage 분모가 부풀려진다(EC-5).
    # 따라서 매 실행마다 해당 trading_date의 기존 레코드를 전량 삭제한 뒤 재삽입한다.
    # @MX:SPEC: SPEC-AI-068 REQ-AI068-001
    """스캔 유니버스 종목코드를 surge_universe_members 테이블에 일자당 replace로 저장한다.

    build_scan_universe()가 확정한 결과(universe_codes, entry_pool_map)를 호출부(fund_manager
    gather_surge_candidates)와 동일 트랜잭션에서 기록한다. build_scan_universe의 우선순위·상한
    로직 자체는 변경하지 않으며, 이 함수는 그 결과만 영속화한다.

    Args:
        db: SQLAlchemy 세션
        trading_date: 유니버스 확정 기준 날짜
        universe_codes: build_scan_universe가 반환한 최종 유니버스 종목코드 목록
        entry_pool_map: {stock_code: entry_pool} — pool_a/pool_b/pool_c/existing

    Returns:
        저장된 레코드 수
    """
    # 일자당 replace: 기존 레코드 전량 삭제 후 재삽입 (EC-5 스테일 코드 방지)
    db.query(SurgeUniverseMember).filter(
        SurgeUniverseMember.trading_date == trading_date
    ).delete(synchronize_session=False)

    if not universe_codes:
        db.flush()
        logger.info(
            "[스캔유니버스] 유니버스 멤버 영속화 완료(빈 유니버스) — date=%s, count=0",
            trading_date,
        )
        return 0

    # 중복 코드 제거(순서 보존)하며 entry_pool 태깅
    seen: set[str] = set()
    rows: list[SurgeUniverseMember] = []
    for code in universe_codes:
        if code in seen:
            continue
        seen.add(code)
        rows.append(
            SurgeUniverseMember(
                trading_date=trading_date,
                stock_code=code,
                entry_pool=entry_pool_map.get(code, "existing"),
            )
        )

    db.add_all(rows)
    db.flush()

    logger.info(
        "[스캔유니버스] 유니버스 멤버 영속화 완료 — date=%s, count=%d",
        trading_date,
        len(rows),
    )
    return len(rows)


def get_universe_members_for_date(db: Session, target_date: date) -> set[str]:
    # @MX:NOTE: [AUTO] SPEC-AI-068 REQ-001/T-003 — 지정 거래일의 영속화된 스캔 유니버스
    # 종목코드 집합을 조회한다. 레코드가 없으면(과거 날짜 미백필 등) 빈 집합을 반환하며,
    # 호출부(evaluate_surge_predictions)는 이를 "유니버스 부재"로 간주해 scannable_recall을
    # null 처리해야 한다(EC-2).
    # @MX:SPEC: SPEC-AI-068 REQ-AI068-002
    """지정 날짜에 영속화된 스캔 유니버스 종목코드 집합을 조회한다.

    Args:
        db: SQLAlchemy 세션
        target_date: 조회 대상 날짜 (보통 T-1, 예측일)

    Returns:
        종목코드 집합. 레코드가 없으면 빈 집합(EC-2, 유니버스 부재와 구분 불가 —
        호출부에서 별도로 레코드 존재 여부를 판단해야 하는 경우 COUNT 쿼리를 병행할 것)
    """
    rows = (
        db.query(SurgeUniverseMember.stock_code)
        .filter(SurgeUniverseMember.trading_date == target_date)
        .all()
    )
    return {row.stock_code for row in rows}
