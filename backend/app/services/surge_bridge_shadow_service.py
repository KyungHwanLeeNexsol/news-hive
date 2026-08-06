"""SPEC-AI-105 REQ-AI105-002: bridge shadow 후보 영속화 서비스.

`generate_scan_universe_bridge_candidates()`(SPEC-AI-092/102)를 마스터 스위치만
override한 config 사본으로 재호출해 산출한 shadow 후보(pool_a/pool_c 한정,
§Decisions D4)를 거래일별로 저장한다. `SurgeUniverseMember.persist_universe_members()`
(SPEC-AI-068, `surge_universe_pool_service.py:110`)와 동일한 composite PK +
일자당 replace(DELETE-then-insert) semantics를 그대로 재사용한다.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING

from app.models.surge_bridge_shadow_candidate import SurgeBridgeShadowCandidate

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.services.surge_detector import SurgeCandidate

logger = logging.getLogger(__name__)


def persist_bridge_shadow_candidates(
    db: "Session",
    trading_date: date,
    shadow_candidates: list["SurgeCandidate"],
) -> int:
    # @MX:NOTE: [AUTO] SPEC-AI-105 REQ-AI105-002 — bridge shadow 후보 영속화. 일자당
    # replace(DELETE-then-insert) semantics — SurgeUniverseMember.persist_universe_members()
    # 관례를 그대로 재사용한다.
    # @MX:REASON: 동일 날짜 재실행(예: 10:00 → 15:20 스캔) 시 이전 실행의 스테일 shadow
    # 후보가 잔존하면 analyze_bridge_shadow_precision_by_date()의 분모가 부풀려진다.
    # 따라서 매 실행마다 해당 trading_date의 기존 레코드를 전량 삭제한 뒤 재삽입한다.
    # @MX:SPEC: SPEC-AI-105 REQ-AI105-002
    """bridge shadow 후보를 surge_bridge_shadow_candidates 테이블에 일자당 replace로 저장한다.

    shadow 계측 wiring(surge_detector.py, `scan_universe_bridge_shadow_enabled=true`일 때만)이
    generate_scan_universe_bridge_candidates()의 shadow 재호출 결과를 이 함수로 전달한다.
    shadow 후보는 pool_a/pool_c 한정이다(§Decisions D4 — 호출부에서 pool_b를 이미 배제).

    Args:
        db: SQLAlchemy 세션
        trading_date: shadow 계측 기준 날짜
        shadow_candidates: generate_scan_universe_bridge_candidates()가 shadow config로
            반환한 SurgeCandidate 목록 (entry_pool/bridge_score 속성 필요)

    Returns:
        저장된 레코드 수
    """
    # 일자당 replace: 기존 레코드 전량 삭제 후 재삽입
    db.query(SurgeBridgeShadowCandidate).filter(
        SurgeBridgeShadowCandidate.trading_date == trading_date
    ).delete(synchronize_session=False)

    if not shadow_candidates:
        db.flush()
        logger.info(
            "[브리지섀도우] shadow 후보 영속화 완료(빈 후보) — date=%s, count=0",
            trading_date,
        )
        return 0

    # 중복 코드 제거(순서 보존)
    seen: set[str] = set()
    rows: list[SurgeBridgeShadowCandidate] = []
    for candidate in shadow_candidates:
        code = candidate.stock_code
        if code in seen:
            continue
        seen.add(code)
        rows.append(
            SurgeBridgeShadowCandidate(
                trading_date=trading_date,
                stock_code=code,
                entry_pool=candidate.entry_pool,
                bridge_score=candidate.bridge_score,
            )
        )

    db.add_all(rows)
    db.flush()

    logger.info(
        "[브리지섀도우] shadow 후보 영속화 완료 — date=%s, count=%d",
        trading_date,
        len(rows),
    )
    return len(rows)
