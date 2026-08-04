"""SPEC-AI-101: SPEC-AI-100 섀도우→프로덕션 전환 게이트 3요건 판정.

REQ-AI101-005: SurgeHorizonShadowObservation을 집계해 (1) 관측된 고유 거래일 수,
(2) 관측된 시장 레짐 집합, (3) 관측 기간 중 qualified 집합 최대 변화폭(%)을 참고
정보로만 반환한다. 이 함수의 반환값을 근거로 `horizon_aware_thresholds.enabled`를
자동으로 전환하는 코드는 어디에도 없다(D5) — 사람이 검토해 전환 여부를 결정하는
입력으로만 쓰인다.
"""
from __future__ import annotations

from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from app.models.surge_horizon_shadow_observation import SurgeHorizonShadowObservation

# SPEC-AI-100 REQ-AI100-009 전환 게이트 3요건 최소값 (spec.md HISTORY, design.md §G).
_MIN_OBSERVED_TRADING_DAYS = 10
_REQUIRED_REGIMES = {"BULL", "SIDEWAYS", "BEAR"}
_MAX_CHANGE_PCT_THRESHOLD = 30.0


def check_horizon_transition_readiness(db: Session) -> dict:
    """SPEC-AI-100 REQ-AI100-009 3요건 판정 참고 정보를 반환한다.

    # @MX:NOTE: [AUTO] SPEC-AI-101 — 이 함수의 반환값은 사람이 검토하는 참고 정보다.
    # `all_criteria_met`이 True여도 horizon_aware_thresholds.enabled를 자동으로
    # True로 전환하는 코드는 이 함수를 포함해 어디에도 없다(D5, REQ-AI101-005 필수
    # 조건 — grep 검증 대상).
    # @MX:SPEC: SPEC-AI-101 REQ-AI101-005

    Args:
        db: SQLAlchemy 동기 세션

    Returns:
        {"observed_trading_days": int, "regimes_observed": set[str],
         "max_change_pct": float, "all_criteria_met": bool}
    """
    rows = (
        db.query(
            sqlfunc.date(SurgeHorizonShadowObservation.observed_at).label("obs_date"),
            SurgeHorizonShadowObservation.market_regime,
            SurgeHorizonShadowObservation.change_pct,
        )
        .all()
    )

    observed_days = {row.obs_date for row in rows}
    regimes_observed: set[str] = {row.market_regime for row in rows}
    max_change_pct = max((row.change_pct for row in rows), default=0.0)

    all_criteria_met = (
        len(observed_days) >= _MIN_OBSERVED_TRADING_DAYS
        and _REQUIRED_REGIMES.issubset(regimes_observed)
        and max_change_pct <= _MAX_CHANGE_PCT_THRESHOLD
    )

    return {
        "observed_trading_days": len(observed_days),
        "regimes_observed": regimes_observed,
        "max_change_pct": max_change_pct,
        "all_criteria_met": all_criteria_met,
    }
