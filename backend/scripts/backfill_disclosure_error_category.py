#!/usr/bin/env python
"""SPEC-AI-028 REQ-005: 과거 공시 기반 시그널의 error_category 백필 스크립트.

멱등 실행: error_category가 이미 채워진 행은 건드리지 않음.
사용: uv run python scripts/backfill_disclosure_error_category.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.disclosure import Disclosure
from app.models.fund_signal import FundSignal

# 공급 역전 키워드 목록 (signal_verifier._SUPPLY_KEYWORDS와 동일)
_SUPPLY_KEYWORDS: tuple[str, ...] = (
    "유상증자", "전환사채", "신주인수권부사채", "배정", "희석"
)


def _backfill_with_session(db: Session) -> int:
    """주어진 세션으로 백필을 수행하고 업데이트된 행 수를 반환한다.

    테스트에서 직접 호출할 수 있도록 세션을 인자로 받는다.
    멱등성: error_category가 이미 채워진 행은 건드리지 않음.
    """
    # 대상: is_correct=False, surge_candidate, error_category IS NULL
    candidates = (
        db.query(FundSignal)
        .filter(
            FundSignal.is_correct.is_(False),
            FundSignal.signal_type == "surge_candidate",
            FundSignal.error_category.is_(None),
        )
        .all()
    )

    updated = 0
    for signal in candidates:
        # 공시 기반 시그널 여부 확인
        is_disclosure_based = signal.disclosure_id is not None
        if not is_disclosure_based and signal.surge_metadata:
            try:
                meta = json.loads(signal.surge_metadata)
                if "immediate_disclosure" in meta.get("surge_basis", []):
                    is_disclosure_based = True
            except (json.JSONDecodeError, TypeError):
                pass

        if not is_disclosure_based:
            continue

        # 연결 공시에서 공급 키워드 탐색
        disc_text = ""
        if signal.disclosure_id:
            disc = db.query(Disclosure).filter(Disclosure.id == signal.disclosure_id).first()
            if disc:
                disc_text = (disc.report_name or "") + " " + (disc.ai_summary or "")

        if any(kw in disc_text for kw in _SUPPLY_KEYWORDS):
            signal.error_category = "supply_reversal"
        else:
            signal.error_category = "sector_contagion"
        updated += 1

    return updated


def main() -> None:
    """프로덕션 실행 진입점."""
    db = SessionLocal()
    try:
        updated = _backfill_with_session(db)
        db.commit()
        print(f"Backfill complete: {updated} rows updated")
    finally:
        db.close()


if __name__ == "__main__":
    main()
