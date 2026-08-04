#!/usr/bin/env python
"""SPEC-AI-098 REQ-AI098-002: 종목명 별칭 후보 제안 스크립트.

`surge_detector.py`의 `_STOCK_NAME_ALIASES`(11개 대형주 전용 하드코딩 딕셔너리)에서
관찰되는 "한글 음역 영문 법인 접미어" 패턴(에스=S, 케이=K, 엘지=LG, 디=D 등)에 해당하는
미등록 종목명을 후보로 나열한다.

**순수 후보 목록 전용 [HARD]**: 이 스크립트는 애초에 `--execute` 모드가 없다 — DB나 코드
파일을 수정하는 경로 자체가 존재하지 않는다. `_STOCK_NAME_ALIASES` 딕셔너리는 사람이 후보를
검토한 뒤 수동으로 추가한다(SPEC-AI-098 §Decisions D2).

사용법:
    cd backend
    uv run python scripts/suggest_stock_name_aliases.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.stock import Stock  # noqa: E402
from app.services.surge_detector import _STOCK_NAME_ALIASES  # noqa: E402

# 기존 11개 별칭에서 관찰되는 "한글 음역 영문 법인 접미어" 패턴.
# 복합 세그먼트(예: "에스케이")를 단일 문자 세그먼트(예: "에스", "케이")보다 먼저
# 매칭해야 "SK" 같은 정확한 치환이 우선 적용된다 — dict 순서가 매칭 우선순위다.
_TRANSLITERATION_SEGMENTS: dict[str, str] = {
    "에스케이": "SK",
    "에스디에스": "SDS",
    "엘지": "LG",
    "에스": "S",
    "케이": "K",
    "디": "D",
}


def _find_candidate_alias(stock_name: str) -> tuple[str, str, str] | None:
    """종목명에서 음역 세그먼트를 찾아 (매칭 세그먼트, 영문 치환, 후보 별칭)을 반환한다.

    복수 세그먼트가 매칭될 수 있으나, 첫 번째(우선순위가 높은) 매칭만 사용한다.
    매칭이 없으면 None을 반환한다.
    """
    for segment, replacement in _TRANSLITERATION_SEGMENTS.items():
        if segment in stock_name:
            candidate = stock_name.replace(segment, replacement, 1)
            return segment, replacement, candidate
    return None


def suggest_candidates(db: Session | None = None) -> list[dict]:
    """DB 전체 종목명을 스캔해 별칭 후보 목록을 생성한다(읽기 전용).

    Args:
        db: 기존 세션(테스트 등에서 주입). None이면 SessionLocal()로 신규 세션을 열고
            조회 후 닫는다(스크립트 단독 실행 시의 기본 경로).

    Returns:
        각 항목이 {stock_code, stock_name, matched_segment, replacement, candidate_alias}인 목록.
    """
    if db is not None:
        stocks = db.query(Stock.stock_code, Stock.name).all()
    else:
        _db = SessionLocal()
        try:
            stocks = _db.query(Stock.stock_code, Stock.name).all()
        finally:
            _db.close()

    # 이미 등록된 별칭 키 집합과의 차집합만 후보로 제시한다 (spec.md §D Edge Cases).
    registered_names = set(_STOCK_NAME_ALIASES.keys())

    candidates: list[dict] = []
    for stock_code, name in stocks:
        if not name or name in registered_names:
            continue
        found = _find_candidate_alias(name)
        if found is None:
            continue
        segment, replacement, candidate_alias = found
        candidates.append(
            {
                "stock_code": stock_code,
                "stock_name": name,
                "matched_segment": segment,
                "replacement": replacement,
                "candidate_alias": candidate_alias,
            }
        )
    return candidates


def main() -> None:
    candidates = suggest_candidates()
    if not candidates:
        print("별칭 후보 없음 (미등록 종목명 중 음역 패턴 매칭 결과 0건)")
        return

    print(f"별칭 후보 {len(candidates)}건 (사람 검토 필요 — 자동 수정되지 않음):\n")
    for c in candidates:
        print(
            f"  {c['stock_code']}  {c['stock_name']!r}"
            f"  근거: '{c['matched_segment']}' → '{c['replacement']}'"
            f"  후보: {c['candidate_alias']!r}"
        )
    print(
        "\n_STOCK_NAME_ALIASES 딕셔너리는 이 스크립트가 자동 수정하지 않습니다. "
        "검토 후 backend/app/services/surge_detector.py 에 수동으로 추가하세요."
    )


if __name__ == "__main__":
    main()
