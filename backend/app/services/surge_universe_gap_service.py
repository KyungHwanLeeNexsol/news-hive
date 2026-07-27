"""SPEC-AI-089 M1: 스캔 유니버스↔탐지망 배선 측정 스파이크 — 측정 전용 서비스.

REQ-AI089-001: `gather_surge_candidates()`가 이미 계산한 `_universe_codes`/
`_entry_pool_map`(build_scan_universe 반환값)과 `merged`(탐지 후보 딕셔너리) 두
인메모리 구조체만 소비하는 순수 함수. 신규 DB 쓰기·네트워크 조회 없음.

REQ-AI089-002: 표본 거래일의 무시그널(disclosure_impact/preday_disclosure/
volume_anomaly/gap_pullback_candidate/sector_ripple/surge_candidate 전부 부재)
실제 급등 종목이 T-1 스캔 유니버스의 어느 풀(A/B/C/D/부재)에 속했는지 오프라인
귀속 분류한다. `SurgeActualOutcome` × `SurgeUniverseMember`(SPEC-AI-068) ×
`FundSignal` 조인만 사용 — 신규 마이그레이션 없음(research.md 확인).

본 모듈은 SPEC-AI-068의 `surge_universe_pool_service.py`와 자매 모듈이다
(design.md § M1 측정 아키텍처 근거) — `surge_detector.py`의 탐지 로직은
어떤 방식으로도 수정하지 않는다(REQ-AI089-003 [HARD]).
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import func as sqlfunc

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.services.surge_detector import SurgeCandidate

# SPEC-AI-089 REQ-AI089-002 구현 참고: 무시그널 판정 시 "시그널이 하나라도 존재하는가"를
# 확인하는 signal_type 목록. spec.md REQ-002 구현 참고 블록과 정확히 일치시킨다.
NO_SIGNAL_CHECK_TYPES: tuple[str, ...] = (
    "disclosure_impact",
    "preday_disclosure",
    "volume_anomaly",
    "gap_pullback_candidate",
    "sector_ripple",
    "surge_candidate",
)

_POOL_NAMES: tuple[str, ...] = ("pool_a", "pool_b", "pool_c", "pool_d")


def measure_universe_detection_gap(
    universe_codes: list[str],
    entry_pool_map: dict[str, str],
    merged_candidates: dict[str, "SurgeCandidate"],
) -> dict[str, int | float | None]:
    """스캔 유니버스 풀별(A/B/C/D) raw 개수와 탐지망(merged) 커버 개수를 계산한다.

    순수 인메모리 집합 연산 — DB 조회·네트워크 호출 없음(REQ-AI089-001/003/004).

    Args:
        universe_codes: build_scan_universe()가 반환한 최종 스캔 유니버스 코드 목록.
        entry_pool_map: {stock_code: entry_pool} — pool_a/pool_b/pool_c/pool_d/existing.
        merged_candidates: gather_surge_candidates() 내부 병합된 탐지 후보 딕셔너리
            (호출부는 이 딕셔너리를 절대 변경하지 않고 읽기만 전달해야 한다).

    Returns:
        pool_x_total(raw 개수) / pool_x_covered(탐지망 교집합) / pool_x_gap(미탐지망
        차집합) / pool_x_gap_ratio(gap/total, total==0이면 None — division-by-zero
        guard) 필드를 pool in {a,b,c,d}별로 포함하는 딕셔너리.
    """
    detected_codes = set(merged_candidates.keys())

    pool_codes: dict[str, set[str]] = {name: set() for name in _POOL_NAMES}
    for code in universe_codes:
        pool = entry_pool_map.get(code, "existing")
        # "existing"(기존 탐지기 결과) 및 미지정 풀은 A/B/C/D 카운트에 영향 없음
        # (기존 build_scan_universe 시맨틱과 일치 — acceptance.md 엣지 케이스).
        if pool in pool_codes:
            pool_codes[pool].add(code)

    result: dict[str, int | float | None] = {}
    for pool in _POOL_NAMES:
        codes = pool_codes[pool]
        total = len(codes)
        covered = len(codes & detected_codes)
        gap = total - covered
        result[f"{pool}_total"] = total
        result[f"{pool}_covered"] = covered
        result[f"{pool}_gap"] = gap
        # division-by-zero guard (acceptance.md 엣지 케이스: 모든 풀이 비어있는 날)
        result[f"{pool}_gap_ratio"] = (gap / total) if total > 0 else None

    return result


def analyze_no_signal_pool_attribution(db: "Session", trading_date: date) -> dict:
    """REQ-AI089-002: 표본 거래일의 무시그널 실제급등 종목을 T-1 스캔 유니버스 풀로 귀속 분류한다.

    무시그널 판정 기준(spec.md REQ-002 구현 참고): `NO_SIGNAL_CHECK_TYPES`의 signal_type이
    trading_date(T, 실제 급등일) 당일 전부 부재.
    풀 귀속은 T-1(직전 영업일) `SurgeUniverseMember.entry_pool` 조회 — pool_a/b/c/d에
    없으면 "absent"(소스 부재형, 유니버스 배선으로 해결되지 않음 — design.md § 열린 질문 3).

    Args:
        db: SQLAlchemy 동기 세션 (읽기 전용 조회만 수행, 쓰기 없음).
        trading_date: 평가 기준 날짜 (T당일, SurgeActualOutcome.trading_date).

    Returns:
        {
            "trading_date": date,
            "sample_present": bool,  # False면 해당일 실제급등 종목 자체가 0건
            "actual_surge_count": int,
            "no_signal_codes": list[str],
            "attribution": {stock_code: "pool_a"|"pool_b"|"pool_c"|"pool_d"|"absent"},
            "attribution_summary": {pool: count},
        }
    """
    from app.models.fund_signal import FundSignal
    from app.models.stock import Stock
    from app.models.surge_actual_outcome import SurgeActualOutcome
    from app.models.surge_universe_member import SurgeUniverseMember
    from app.services.surge_trading_service import _get_prev_business_day

    actual_rows = (
        db.query(SurgeActualOutcome.stock_code)
        .filter(
            SurgeActualOutcome.trading_date == trading_date,
            SurgeActualOutcome.was_surge.is_(True),
        )
        .all()
    )
    actual_codes = [row.stock_code for row in actual_rows]

    if not actual_codes:
        # 엣지 케이스: 표본일 데이터가 없는 경우 — 빈 리포트를 명시적으로 반환
        # (조용히 스킵하지 않음, acceptance.md 엣지 케이스).
        return {
            "trading_date": trading_date,
            "sample_present": False,
            "actual_surge_count": 0,
            "no_signal_codes": [],
            "attribution": {},
            "attribution_summary": {},
        }

    signaled_rows = (
        db.query(Stock.stock_code)
        .join(FundSignal, FundSignal.stock_id == Stock.id)
        .filter(
            Stock.stock_code.in_(actual_codes),
            FundSignal.signal_type.in_(NO_SIGNAL_CHECK_TYPES),
            sqlfunc.date(FundSignal.created_at) == trading_date,
        )
        .distinct()
        .all()
    )
    signaled_codes = {row.stock_code for row in signaled_rows}
    no_signal_codes = [code for code in actual_codes if code not in signaled_codes]

    prev_business_day = _get_prev_business_day(trading_date)
    pool_by_code: dict[str, str] = {}
    if no_signal_codes:
        universe_rows = (
            db.query(SurgeUniverseMember.stock_code, SurgeUniverseMember.entry_pool)
            .filter(
                SurgeUniverseMember.trading_date == prev_business_day,
                SurgeUniverseMember.stock_code.in_(no_signal_codes),
            )
            .all()
        )
        pool_by_code = {row.stock_code: row.entry_pool for row in universe_rows}

    attribution: dict[str, str] = {}
    attribution_summary: dict[str, int] = {}
    for code in no_signal_codes:
        pool = pool_by_code.get(code, "absent")
        attribution[code] = pool
        attribution_summary[pool] = attribution_summary.get(pool, 0) + 1

    return {
        "trading_date": trading_date,
        "sample_present": True,
        "actual_surge_count": len(actual_codes),
        "no_signal_codes": no_signal_codes,
        "attribution": attribution,
        "attribution_summary": attribution_summary,
    }
