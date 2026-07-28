"""SPEC-AI-090 M1: 연속성 계열 탐지기 평가 기준 재검토 측정 스파이크 — 읽기 전용 파생 계산.

momentum_continuation/near_limit_up_carry 두 "연속성(continuation)" 계열 탐지기의
solo-attributed 시그널을, 기존 was_surge(scannable, >=10%) 기준 외에 "연속성에 적합한"
완화된 대안 성공 기준(기준 B "미반전"/기준 C "추가 상승")으로 병렬 재채점한다.

측정 전용 계층이다 — 신호 생성 경로(detect_momentum_continuation/
detect_near_limit_up_carries/compute_ensemble_score)와 기존 기여도 집계 경로
(evaluate_detector_contribution/surge_detector_contribution 테이블 upsert)를 어떤
방식으로도 호출·수정하지 않는다(REQ-AI090-004 [HARD]). solo attribution 판별 방식은
evaluate_detector_contribution()의 정의(T-1 surge_basis == [detector])를 참고하되,
기존 함수를 임포트/호출하지 않고 별도 모듈에서 동일 로직을 완전히 독립적으로 재현한다.
신규 DB 스키마 없음 — 이 모듈의 모든 함수는 DB에 아무것도 쓰지 않으며, 반환값은
리포트/로그 아티팩트 생성 전용이다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date as date_
from typing import Literal, Optional

from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from app.models.fund_signal import FundSignal
from app.models.stock import Stock
from app.models.surge_actual_outcome import SurgeActualOutcome
from app.services.surge_trading_service import _get_prev_business_day

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# REQ-AI090-002: 대안 성공 기준 임계값 — 명명된 상수(하드코딩 금지, AC-090-002)
# ---------------------------------------------------------------------------

#: 기준 B("미반전", floor 기준) — T당일 변화율이 이 값 이상이면 성공
BAR_B_FLOOR_THRESHOLD_PCT: float = 0.0

#: 기준 C("추가 상승", incremental-gain 기준) — 완화 임계 1 (+3.0%)
BAR_C_GAIN_THRESHOLD_LOW_PCT: float = 3.0

#: 기준 C("추가 상승", incremental-gain 기준) — 완화 임계 2 (+5.0%)
BAR_C_GAIN_THRESHOLD_HIGH_PCT: float = 5.0

#: REQ-AI090-003 측정 대상 "연속성" 계열 탐지기 2종
CONTINUATION_DETECTORS: tuple[str, ...] = ("momentum_continuation", "near_limit_up_carry")

#: 4-기준 병렬 재채점 라벨(REQ-AI090-003) — 기존 was_surge + 기준 B + 기준 C(2개 임계값)
CRITERION_WAS_SURGE = "was_surge"
CRITERION_BAR_B = "bar_b_floor_0pct"
CRITERION_BAR_C_LOW = "bar_c_gain_3pct"
CRITERION_BAR_C_HIGH = "bar_c_gain_5pct"

CRITERIA: tuple[str, ...] = (
    CRITERION_WAS_SURGE,
    CRITERION_BAR_B,
    CRITERION_BAR_C_LOW,
    CRITERION_BAR_C_HIGH,
)

Classification = Literal["success", "fail", "unmeasurable"]


def classify_continuation_outcome(
    t1_change_rate: float,
    t_change_rate: Optional[float],
    threshold_pct: float,
) -> Classification:
    """REQ-AI090-002: 기준 B/C 판정 순수 함수 — DB/네트워크 접근 없음.

    기존 was_surge(>=10.0%) 판정과 별개로, 완화된 임계(threshold_pct)를 기준으로
    성공/실패/측정불가를 판정한다. 동일 입력에 대해 항상 동일한 결과를 반환한다
    (AC-090-002).

    Args:
        t1_change_rate: 시그널의 근거가 된 T-1 변화율(%). 기준 B/C는 "T-1 변화율이
            양수였던 종목"에 대해서만 정의된다(REQ-002). momentum_continuation
            ([5,15)%)/near_limit_up_carry([15,29.99]%) 후보는 후보 선정 범위상 구조적으로
            항상 양수이므로, 이 분기는 실무에서는 도달하지 않는 방어적 가드다 — 그러나
            함수를 다른 문맥에서 재사용할 가능성에 대비해 명시적으로 unmeasurable 처리한다.
        t_change_rate: T당일 변화율(%). 해당 종목·날짜의 SurgeActualOutcome 행이 없으면
            None — 이 경우 "측정불가"로 판정하고 분모에서 제외한다(REQ-002).
        threshold_pct: 판정 임계값. 기준 B는 BAR_B_FLOOR_THRESHOLD_PCT(0.0), 기준 C는
            BAR_C_GAIN_THRESHOLD_LOW_PCT(3.0) 또는 BAR_C_GAIN_THRESHOLD_HIGH_PCT(5.0).

    Returns:
        "success" | "fail" | "unmeasurable"
    """
    if t1_change_rate <= 0:
        return "unmeasurable"
    if t_change_rate is None:
        return "unmeasurable"
    return "success" if t_change_rate >= threshold_pct else "fail"


def _parse_surge_basis(surge_metadata_raw: Optional[str]) -> list[str]:
    """FundSignal.surge_metadata(JSON string)에서 surge_basis 리스트를 파싱한다.

    surge_contribution_service._parse_surge_basis_raw와 동일한 파싱 로직을 이 모듈에서
    완전히 독립적으로 재현한다(REQ-AI090-003 구현 참고 — 기존 함수를 임포트/호출하지
    않음. 신호 생성 경로를 변경하지 않는다).
    """
    if not surge_metadata_raw:
        return []
    try:
        meta = json.loads(surge_metadata_raw)
    except (json.JSONDecodeError, TypeError):
        return []
    basis = meta.get("surge_basis", [])
    if not isinstance(basis, list):
        return []
    return [str(b) for b in basis if b]


def _extract_t1_change_rate(
    db: Session,
    detector: str,
    surge_metadata_raw: Optional[str],
    stock_code: str,
    prev_business_day: date_,
) -> Optional[float]:
    """탐지기별 T-1 변화율 추출(REQ-AI090-002 구현 참고 원문).

    - near_limit_up_carry: surge_metadata.yesterday_change_pct — 시그널 생성 시점에
      이미 영속화되어 있다(surge_detector.py detect_near_limit_up_carries).
    - momentum_continuation(및 그 외 탐지기): surge_candidate_to_signal_metadata가
      momentum_continuation_score만 남기고 T-1 변화율 자체는 surge_metadata에
      영속화하지 않으므로, SurgeActualOutcome.change_rate를 T-1 날짜·종목코드로
      직접 조회한다.
    """
    if detector == "near_limit_up_carry":
        if not surge_metadata_raw:
            return None
        try:
            meta = json.loads(surge_metadata_raw)
        except (json.JSONDecodeError, TypeError):
            return None
        value = meta.get("yesterday_change_pct")
        return float(value) if value is not None else None

    row = (
        db.query(SurgeActualOutcome.change_rate)
        .filter(
            SurgeActualOutcome.trading_date == prev_business_day,
            SurgeActualOutcome.stock_code == stock_code,
        )
        .first()
    )
    return float(row.change_rate) if row is not None and row.change_rate is not None else None


def _fetch_t_change_rate(db: Session, sample_date: date_, stock_code: str) -> Optional[float]:
    """T당일 SurgeActualOutcome.change_rate 조회 — 없으면 None(측정불가 입력)."""
    row = (
        db.query(SurgeActualOutcome.change_rate)
        .filter(
            SurgeActualOutcome.trading_date == sample_date,
            SurgeActualOutcome.stock_code == stock_code,
        )
        .first()
    )
    return float(row.change_rate) if row is not None and row.change_rate is not None else None


def _fetch_scannable_codes(db: Session, sample_date: date_) -> set[str]:
    """T당일 scannable 실제급등주 종목코드 집합.

    evaluate_detector_contribution()과 정확히 동일한 정의(SurgeActualOutcome.surge_type
    == "scannable")를 이 모듈에서 독립적으로 재현한다 — 기존 was_surge/scannable 집계
    정의 자체는 변경하지 않는다(REQ-AI090-004).
    """
    rows = (
        db.query(SurgeActualOutcome.stock_code)
        .filter(
            SurgeActualOutcome.trading_date == sample_date,
            SurgeActualOutcome.surge_type == "scannable",
        )
        .all()
    )
    return {row.stock_code for row in rows}


def _new_criterion_counter() -> dict[str, object]:
    return {"hit": 0, "miss": 0, "unmeasurable": 0, "hit_rate": None}


def _finalize_hit_rate(counter: dict[str, object]) -> None:
    denom = counter["hit"] + counter["miss"]
    counter["hit_rate"] = round(counter["hit"] / denom, 4) if denom > 0 else None


@dataclass
class ContinuationBarResult:
    """탐지기 1개의 4-기준 병렬 재채점 결과(REQ-AI090-003) — 리포트 렌더링 편의 래퍼."""

    detector: str
    solo_signal_count: int = 0
    measured_dates: list[date_] = field(default_factory=list)
    criteria: dict[str, dict] = field(default_factory=dict)


def measure_continuation_detector_bars(
    db: Session,
    sample_dates: list[date_],
    detectors: tuple[str, ...] = CONTINUATION_DETECTORS,
) -> dict[str, dict]:
    """REQ-AI090-003: solo-attributed 시그널을 4-기준으로 병렬 재채점한다(읽기 전용).

    evaluate_detector_contribution()과 동일한 attribution 방식(T-1 surge_basis ==
    [detector]인 solo 시그널 집합)을 별도로 재현한 읽기 전용 쿼리로 구현하며, 기존
    함수를 호출·수정하지 않는다(REQ-AI090-004). 이 함수는 DB에 아무것도 쓰지 않는다.

    Args:
        db: SQLAlchemy 동기 세션
        sample_dates: 표본 거래일(T) 목록 — REQ-AI090-001에서 재현 확인된 날짜 중
            호출부가 선택한 값. 탐지기별 solo_count는 날짜마다 다를 수 있으므로, 이
            함수는 각 표본일에서 실제로 solo 시그널이 존재하는 경우만 집계에 반영한다
            (solo_count == 0인 날짜는 자동으로 건너뛴다 — 별도 사전 필터링 불필요).
        detectors: 측정 대상 탐지기(기본값: momentum_continuation, near_limit_up_carry).

    Returns:
        {detector: {"solo_signal_count": int, "measured_dates": [date, ...],
                     "criteria": {criterion: {"hit": int, "miss": int,
                     "unmeasurable": int, "hit_rate": float | None}, ...}}}
    """
    results: dict[str, ContinuationBarResult] = {
        d: ContinuationBarResult(
            detector=d,
            criteria={c: _new_criterion_counter() for c in CRITERIA},
        )
        for d in detectors
    }

    for sample_date in sample_dates:
        prev_business_day = _get_prev_business_day(sample_date)

        signal_rows = (
            db.query(FundSignal.surge_metadata, Stock.stock_code)
            .join(Stock, FundSignal.stock_id == Stock.id)
            .filter(
                FundSignal.signal_type == "surge_candidate",
                FundSignal.surge_metadata.isnot(None),
                sqlfunc.date(FundSignal.created_at) == prev_business_day,
            )
            .all()
        )

        scannable_codes = _fetch_scannable_codes(db, sample_date)
        day_solo_count: dict[str, int] = {d: 0 for d in detectors}

        for surge_metadata_raw, stock_code in signal_rows:
            basis = _parse_surge_basis(surge_metadata_raw)
            if len(basis) != 1:
                continue  # solo 시그널이 아님 — REQ-003 attribution 범위 밖
            detector = basis[0]
            if detector not in results:
                continue  # 측정 대상 2종 외 탐지기

            day_solo_count[detector] += 1
            metrics = results[detector].criteria

            # (a) 기존 was_surge(scannable) 기준 — evaluate_detector_contribution과 동일 정의.
            # 이 기준은 t1_change_rate/t_change_rate와 무관하게 항상 판정 가능하다.
            if stock_code in scannable_codes:
                metrics[CRITERION_WAS_SURGE]["hit"] += 1
            else:
                metrics[CRITERION_WAS_SURGE]["miss"] += 1

            t1_change_rate = _extract_t1_change_rate(
                db, detector, surge_metadata_raw, stock_code, prev_business_day
            )
            t_change_rate = _fetch_t_change_rate(db, sample_date, stock_code)

            for criterion, threshold in (
                (CRITERION_BAR_B, BAR_B_FLOOR_THRESHOLD_PCT),
                (CRITERION_BAR_C_LOW, BAR_C_GAIN_THRESHOLD_LOW_PCT),
                (CRITERION_BAR_C_HIGH, BAR_C_GAIN_THRESHOLD_HIGH_PCT),
            ):
                if t1_change_rate is None:
                    verdict: Classification = "unmeasurable"
                else:
                    verdict = classify_continuation_outcome(t1_change_rate, t_change_rate, threshold)

                if verdict == "success":
                    metrics[criterion]["hit"] += 1
                elif verdict == "fail":
                    metrics[criterion]["miss"] += 1
                else:
                    metrics[criterion]["unmeasurable"] += 1

        for detector, count in day_solo_count.items():
            if count > 0:
                results[detector].solo_signal_count += count
                results[detector].measured_dates.append(sample_date)

    output: dict[str, dict] = {}
    for detector, result in results.items():
        for counter in result.criteria.values():
            _finalize_hit_rate(counter)
        output[detector] = {
            "solo_signal_count": result.solo_signal_count,
            "measured_dates": result.measured_dates,
            "criteria": result.criteria,
        }

    logger.info(
        "[continuation_bar_measurement] 표본 거래일=%d개, 탐지기=%s 측정 완료",
        len(sample_dates),
        list(detectors),
    )

    return output
