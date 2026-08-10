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


def analyze_pool_precision_by_date(
    db: "Session", trading_date: date
) -> dict[str, dict[str, int | float | None]]:
    """REQ-AI104-005: 특정 거래일 풀별(A/B/C/D) 소속 전체 종목 중 실제 급등 비율(precision)을 계산한다.

    `analyze_no_signal_pool_attribution()`의 자매 함수 — 그 함수는 "무시그널 실제급등
    종목"이라는 이미 좁혀진 부분집합의 recall측 귀속만 다루는 반면, 본 함수는 pool_d
    "노이즈가 많은가"라는 원 우려에 직접 답하는 precision측(그 풀에 있는 종목 중 실제로
    몇 %가 진짜 급등이었는가)을 다룬다 — 두 지표는 서로 다른 질문이다(spec.md §Decisions D3).

    `SurgeUniverseMember.entry_pool` × `SurgeActualOutcome.was_surge` 조인만 사용한다.
    신규 DB 쓰기·마이그레이션 없음(REQ-AI104-005).

    Args:
        db: SQLAlchemy 동기 세션 (읽기 전용 조회만 수행, 쓰기 없음).
        trading_date: 평가 기준 날짜 (해당일 `SurgeUniverseMember.trading_date` +
            해당일 `SurgeActualOutcome.trading_date` — T-1 오프셋 없음).

    Returns:
        {"pool_a"|"pool_b"|"pool_c"|"pool_d": {"total": int, "surge_count": int,
        "precision": float | None}} — 해당 풀 소속 종목이 0건이면 precision은 None
        (division-by-zero guard, `measure_universe_detection_gap()`의 `*_gap_ratio`
        None-guard 관례 계승, AC-104-004).
    """
    from app.models.surge_actual_outcome import SurgeActualOutcome
    from app.models.surge_universe_member import SurgeUniverseMember

    member_rows = (
        db.query(SurgeUniverseMember.stock_code, SurgeUniverseMember.entry_pool)
        .filter(
            SurgeUniverseMember.trading_date == trading_date,
            SurgeUniverseMember.entry_pool.in_(_POOL_NAMES),
        )
        .all()
    )
    pool_codes: dict[str, set[str]] = {name: set() for name in _POOL_NAMES}
    for row in member_rows:
        pool_codes[row.entry_pool].add(row.stock_code)

    surge_rows = (
        db.query(SurgeActualOutcome.stock_code)
        .filter(
            SurgeActualOutcome.trading_date == trading_date,
            SurgeActualOutcome.was_surge.is_(True),
        )
        .all()
    )
    surge_codes = {row.stock_code for row in surge_rows}

    result: dict[str, dict[str, int | float | None]] = {}
    for pool in _POOL_NAMES:
        codes = pool_codes[pool]
        total = len(codes)
        surge_count = len(codes & surge_codes)
        # division-by-zero guard (AC-104-004 / 시나리오 2: 해당 풀 소속 종목 0건인 날)
        result[pool] = {
            "total": total,
            "surge_count": surge_count,
            "precision": (surge_count / total) if total > 0 else None,
        }

    return result


# SPEC-AI-105 REQ-AI105-003: shadow 계측은 pool_a/pool_c 한정(§Decisions D4 — pool_b는
# 하드코딩 배제). analyze_pool_precision_by_date()의 _POOL_NAMES(pool_a/b/c/d)와 달리
# 이 함수는 shadow 저장 자체가 pool_a/pool_c만 있을 수 있으므로 대상 풀을 좁게 고정한다.
_BRIDGE_SHADOW_POOL_NAMES: tuple[str, ...] = ("pool_a", "pool_c")


def analyze_bridge_shadow_precision_by_date(
    db: "Session", trading_date: date
) -> dict[str, dict[str, int | float | None]]:
    """REQ-AI105-003: 특정 거래일 bridge shadow 후보의 pool별(A/C) 정밀도를 계산한다.

    `analyze_pool_precision_by_date()`(SPEC-AI-104)의 자매 함수 — 대상 소스가
    `SurgeUniverseMember`(스캔 유니버스 전체 소속)가 아니라
    `SurgeBridgeShadowCandidate`(bridge shadow 계측이 실제로 점수화·승격시켰을 후보만)라는
    점이 다르다. `pool_a`/`pool_c`를 **절대 blended 합산하지 않고 분리** 반환한다
    (§Decisions D2 — pool_c의 bridge scoring이 사실상 무필터에 가까워 강한 pool_a
    정밀도가 약한 pool_c를 가릴 위험 방지).

    `SurgeBridgeShadowCandidate.entry_pool` × `SurgeActualOutcome.was_surge` 조인만
    사용한다. 신규 DB 쓰기·마이그레이션 없음(REQ-AI105-003 순수 읽기).

    Args:
        db: SQLAlchemy 동기 세션 (읽기 전용 조회만 수행, 쓰기 없음).
        trading_date: 평가 기준 날짜 (해당일 `SurgeBridgeShadowCandidate.trading_date` +
            해당일 `SurgeActualOutcome.trading_date` — T-1 오프셋 없음).

    Returns:
        {"pool_a"|"pool_c": {"total": int, "surge_count": int, "precision": float | None}} —
        해당 풀 소속 shadow 후보가 0건이면 precision은 None(division-by-zero guard,
        `analyze_pool_precision_by_date()`의 None-guard 관례 계승, AC-105-006).
    """
    from app.models.surge_actual_outcome import SurgeActualOutcome
    from app.models.surge_bridge_shadow_candidate import SurgeBridgeShadowCandidate

    member_rows = (
        db.query(
            SurgeBridgeShadowCandidate.stock_code,
            SurgeBridgeShadowCandidate.entry_pool,
        )
        .filter(
            SurgeBridgeShadowCandidate.trading_date == trading_date,
            SurgeBridgeShadowCandidate.entry_pool.in_(_BRIDGE_SHADOW_POOL_NAMES),
        )
        .all()
    )
    pool_codes: dict[str, set[str]] = {name: set() for name in _BRIDGE_SHADOW_POOL_NAMES}
    for row in member_rows:
        pool_codes[row.entry_pool].add(row.stock_code)

    surge_rows = (
        db.query(SurgeActualOutcome.stock_code)
        .filter(
            SurgeActualOutcome.trading_date == trading_date,
            SurgeActualOutcome.was_surge.is_(True),
        )
        .all()
    )
    surge_codes = {row.stock_code for row in surge_rows}

    result: dict[str, dict[str, int | float | None]] = {}
    for pool in _BRIDGE_SHADOW_POOL_NAMES:
        codes = pool_codes[pool]
        total = len(codes)
        surge_count = len(codes & surge_codes)
        # division-by-zero guard (AC-105-006 / 시나리오 2: 해당 풀 shadow 후보 0건인 날)
        result[pool] = {
            "total": total,
            "surge_count": surge_count,
            "precision": (surge_count / total) if total > 0 else None,
        }

    return result


def evaluate_bridge_activation_readiness(
    db: "Session",
    *,
    target_pool: str = "pool_a",
    min_trading_days: int = 10,
    min_precision_floor: float = 0.05,
    max_zero_precision_streak: int = 4,
) -> dict[str, object]:
    # @MX:NOTE: [AUTO] SPEC-AI-111 REQ-AI111-002/003 — bridge 실제 활성화 전
    # readiness gate. shadow 후보, 실제 outcome, non-null 평가 precision이 모두 있는 날짜만
    # eligible로 인정한다. DB 쓰기·네트워크 호출 없이 기존 계측 테이블만 읽는다.
    # @MX:SPEC: SPEC-AI-111 REQ-AI111-002, REQ-AI111-003
    """Pool A bridge canary 활성화 가능 여부를 읽기 전용으로 판단한다.

    Eligible day는 다음 세 가지를 모두 만족해야 한다.
    1. target_pool의 bridge shadow 후보가 존재한다.
    2. 같은 날짜의 `SurgeActualOutcome` 행이 존재한다.
    3. 같은 날짜의 `SurgePredictionEvaluation.precision`이 non-null이다.

    Pool A와 Pool C 정밀도는 `analyze_bridge_shadow_precision_by_date()`를 재사용해
    일자별로 분리 계산하며, target_pool 통과 여부에 다른 pool을 절대 blend하지 않는다.
    """
    if target_pool not in _BRIDGE_SHADOW_POOL_NAMES:
        return {
            "ready": False,
            "reason": "unsupported_pool",
            "target_pool": target_pool,
            "required_days": min_trading_days,
            "eligible_days": 0,
            "shadow_outcome_days": 0,
            "pool_total": 0,
            "pool_surge_count": 0,
            "pool_precision": None,
            "baseline_precision": None,
            "precision_threshold": None,
            "zero_precision_streak": 0,
            "daily": [],
        }
    if min_trading_days <= 0:
        raise ValueError("min_trading_days must be positive")

    from app.models.surge_actual_outcome import SurgeActualOutcome
    from app.models.surge_bridge_shadow_candidate import SurgeBridgeShadowCandidate
    from app.models.surge_prediction_evaluation import SurgePredictionEvaluation

    shadow_rows = (
        db.query(SurgeBridgeShadowCandidate.trading_date)
        .filter(SurgeBridgeShadowCandidate.entry_pool == target_pool)
        .distinct()
        .order_by(SurgeBridgeShadowCandidate.trading_date.desc())
        .all()
    )
    shadow_dates = [row.trading_date for row in shadow_rows]

    if shadow_dates:
        outcome_rows = (
            db.query(SurgeActualOutcome.trading_date)
            .filter(SurgeActualOutcome.trading_date.in_(shadow_dates))
            .distinct()
            .all()
        )
        outcome_dates = {row.trading_date for row in outcome_rows}
    else:
        outcome_dates = set()

    shadow_outcome_dates = [d for d in shadow_dates if d in outcome_dates]
    if len(shadow_outcome_dates) < min_trading_days:
        return {
            "ready": False,
            "reason": "insufficient_shadow_days",
            "target_pool": target_pool,
            "required_days": min_trading_days,
            "eligible_days": 0,
            "shadow_outcome_days": len(shadow_outcome_dates),
            "pool_total": 0,
            "pool_surge_count": 0,
            "pool_precision": None,
            "baseline_precision": None,
            "precision_threshold": None,
            "zero_precision_streak": 0,
            "daily": [],
        }

    baseline_rows = (
        db.query(
            SurgePredictionEvaluation.evaluation_date,
            SurgePredictionEvaluation.precision,
        )
        .filter(
            SurgePredictionEvaluation.evaluation_date.in_(shadow_outcome_dates),
            SurgePredictionEvaluation.precision.isnot(None),
        )
        .order_by(SurgePredictionEvaluation.evaluation_date.desc())
        .all()
    )
    baseline_by_date = {
        row.evaluation_date: float(row.precision)
        for row in baseline_rows
        if row.precision is not None
    }
    eligible_dates = [d for d in shadow_outcome_dates if d in baseline_by_date]

    if len(eligible_dates) < min_trading_days:
        return {
            "ready": False,
            "reason": "insufficient_baseline_days",
            "target_pool": target_pool,
            "required_days": min_trading_days,
            "eligible_days": len(eligible_dates),
            "shadow_outcome_days": len(shadow_outcome_dates),
            "pool_total": 0,
            "pool_surge_count": 0,
            "pool_precision": None,
            "baseline_precision": None,
            "precision_threshold": None,
            "zero_precision_streak": 0,
            "daily": [],
        }

    selected_dates = eligible_dates[:min_trading_days]
    pool_total = 0
    pool_surge_count = 0
    daily: list[dict[str, object]] = []
    target_precisions_by_date: dict[date, float | None] = {}

    for trading_date in selected_dates:
        pool_results = analyze_bridge_shadow_precision_by_date(db, trading_date)
        target_stats = pool_results[target_pool]
        target_total = int(target_stats["total"] or 0)
        target_surge_count = int(target_stats["surge_count"] or 0)
        pool_total += target_total
        pool_surge_count += target_surge_count
        target_precisions_by_date[trading_date] = (
            float(target_stats["precision"])
            if target_stats["precision"] is not None
            else None
        )
        daily.append(
            {
                "trading_date": trading_date,
                "baseline_precision": baseline_by_date[trading_date],
                "pools": pool_results,
            }
        )

    pool_precision = (pool_surge_count / pool_total) if pool_total > 0 else None
    baseline_precision = sum(baseline_by_date[d] for d in selected_dates) / len(
        selected_dates
    )
    precision_threshold = max(min_precision_floor, baseline_precision)

    current_zero_streak = 0
    max_seen_zero_streak = 0
    for trading_date in reversed(selected_dates):
        if target_precisions_by_date[trading_date] == 0.0:
            current_zero_streak += 1
            max_seen_zero_streak = max(max_seen_zero_streak, current_zero_streak)
        else:
            current_zero_streak = 0

    ready = True
    reason = "ready"
    if pool_precision is None:
        ready = False
        reason = "no_pool_candidates"
    elif max_seen_zero_streak > max_zero_precision_streak:
        ready = False
        reason = "zero_precision_streak"
    elif pool_precision < precision_threshold:
        ready = False
        reason = "low_precision"

    return {
        "ready": ready,
        "reason": reason,
        "target_pool": target_pool,
        "required_days": min_trading_days,
        "eligible_days": len(selected_dates),
        "eligible_dates": selected_dates,
        "shadow_outcome_days": len(shadow_outcome_dates),
        "pool_total": pool_total,
        "pool_surge_count": pool_surge_count,
        "pool_precision": pool_precision,
        "baseline_precision": baseline_precision,
        "precision_threshold": precision_threshold,
        "zero_precision_streak": max_seen_zero_streak,
        "daily": daily,
    }
