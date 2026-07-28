#!/usr/bin/env python
"""SPEC-AI-091 M3: `stocks.keywords` 오염 데이터 정화(리셋 후 재백필) 스크립트.

REQ-AI091-007: 자동 태깅 기원으로 판단된 종목의 `stocks.keywords`를 NULL로 리셋한 뒤,
REQ-AI091-001~003이 반영된 수정 알고리즘(``extract_theme_keywords``)으로
``backfill_stock_keywords()``를 재실행해 정화된 상태로 재채운다.

**dry-run 기본값 [HARD]**: ``--execute`` 플래그 없이 실행하면 진단 결과만 출력하고
DB를 전혀 변경하지 않는다. 실제 리셋+재백필은 ``--execute``를 명시해야만 실행된다.

REQ-AI091-008: provenance(자동/수동 기원) 컬럼이 `stocks` 테이블에 없어 구조적으로
구분할 수 없으므로(spec.md §2 [E-12]), 비어있지 않은 keywords를 가진 전체 종목을
리셋 대상에 포함하는 보수적 기본 처리를 따른다. 참고용으로 SPEC-AI-084 최초 배치
백필일(2026-07-22) 이전 생성된 종목 수를 "provenance 불명 후보"로 별도 집계해
진단 로그에 보고한다(실제 리셋 여부에는 영향을 주지 않음 — 보수적 기본값 유지).

멱등성: `backfill_stock_keywords()`의 기존 멱등 계약을 그대로 상속한다 — `--execute`를
연속 실행해도 세 번째 실행과 동일한 최종 상태로 수렴한다(§C 엣지 케이스 4).

사용법:
    cd backend
    uv run python scripts/remediate_keyword_tagging.py            # dry-run(기본값, 진단만)
    uv run python scripts/remediate_keyword_tagging.py --execute  # 실제 리셋+재백필 실행
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.stock import Stock  # noqa: E402
from app.services.keyword_tagging_service import (  # noqa: E402
    DEFAULT_MAX_KEYWORDS_PER_STOCK,
    KeywordTaggingResult,
    backfill_stock_keywords,
)

# SPEC-AI-084 최초 배치 백필 실행일(spec.md §2 [E-12] 근거) — provenance 불명 후보
# 진단(참고용 카운트)의 기준일. 이 날짜 이전에 생성된 종목은 SPEC-AI-084 자동 태깅
# 인프라가 존재하기 전이므로 수동 설정 가능성이 상대적으로 높은 후보군으로 본다.
_SPEC_AI_084_FIRST_BACKFILL_DATE = date(2026, 7, 22)

# REQ-AI091-010: 확정 오탐 종목 스팟체크 대상 (각 ≤3개 키워드 기대).
_SPOT_CHECK_STOCK_CODES: tuple[str, ...] = ("023790", "105560", "192080")


def _is_before_cutoff(created_at: datetime | None, cutoff: date) -> bool:
    """``created_at``이 기준일보다 이전인지 확인한다(타임존 유무에 안전)."""
    if created_at is None:
        return False
    return created_at.date() < cutoff


def diagnose(db: Session) -> dict:
    """REQ-AI091-008/009: 정화 대상 진단 — 리셋 후보 수 + 키워드 길이 분포를 계산한다.

    실제 DB 변경 없이 읽기 전용으로 수행된다(dry-run/execute 양쪽에서 공유).
    """
    stocks = db.query(Stock).all()
    tagged = [s for s in stocks if s.keywords]

    total_stocks = len(stocks)
    tagged_count = len(tagged)
    unknown_provenance_count = sum(
        1 for s in tagged if _is_before_cutoff(s.created_at, _SPEC_AI_084_FIRST_BACKFILL_DATE)
    )

    lengths = sorted(len(s.keywords) for s in tagged)
    full_cap_count = sum(1 for n in lengths if n == DEFAULT_MAX_KEYWORDS_PER_STOCK)
    full_cap_pct = (full_cap_count / tagged_count * 100.0) if tagged_count else 0.0
    median_length = median(lengths) if lengths else 0.0

    return {
        "total_stocks": total_stocks,
        "tagged_stocks": tagged_count,
        "unknown_provenance_count": unknown_provenance_count,
        "full_cap_count": full_cap_count,
        "full_cap_pct": full_cap_pct,
        "median_length": median_length,
    }


def reset_keywords(db: Session) -> int:
    """REQ-AI091-007(a)/008: 비어있지 않은 keywords를 가진 전체 종목을 NULL로 리셋한다.

    provenance 컬럼이 없어 자동/수동 기원을 구조적으로 구분할 수 없으므로(§2 [E-12]
    spec.md), REQ-AI091-008의 보수적 기본 처리에 따라 전체를 리셋 대상으로 삼는다.
    이 함수는 ``--execute`` 경로에서만 호출된다 — dry-run 경로에서는 절대 호출되지 않는다.
    """
    stocks = db.query(Stock).all()
    reset_count = 0
    for stock in stocks:
        if stock.keywords:
            stock.keywords = None
            reset_count += 1
    if reset_count:
        db.commit()
    return reset_count


def spot_check(db: Session) -> dict[str, int]:
    """REQ-AI091-010: 확정 오탐 종목 3개의 정화 후 keywords 길이를 반환한다."""
    result: dict[str, int] = {}
    for code in _SPOT_CHECK_STOCK_CODES:
        stock = db.query(Stock).filter(Stock.stock_code == code).first()
        result[code] = len(stock.keywords) if stock and stock.keywords else 0
    return result


def run_remediation(
    db: Session, execute: bool = False, theme_keywords: list[str] | None = None
) -> dict:
    """REQ-AI091-007: 리셋 후 재백필 정화를 실행한다.

    Args:
        execute: False(기본값)이면 진단만 수행하고 DB를 변경하지 않는다(dry-run).
            True이면 진단 → 리셋 → 수정된 알고리즘(REQ-AI091-001~003)으로 재백필을
            실제로 실행한다.
        theme_keywords: 재백필에 사용할 테마 어휘. None이면
            ``backfill_stock_keywords``의 기본값(``ThemeClusterConfig.keywords``)을
            사용한다(테스트에서 고정 어휘를 주입할 수 있도록 통과 인자로 노출).

    Returns:
        진단/리셋/재백필/스팟체크 결과를 담은 report dict. dry-run 모드에서는
        ``reset_count=0``, ``backfill_result=None``, ``after==before``,
        ``spot_check=None``으로 채워진다(변경 없음을 report 구조로도 드러낸다).
    """
    before = diagnose(db)
    report: dict = {
        "mode": "execute" if execute else "dry-run",
        "before": before,
    }

    if not execute:
        report["reset_count"] = 0
        report["backfill_result"] = None
        report["after"] = before
        report["spot_check"] = None
        return report

    reset_count = reset_keywords(db)
    backfill_result: KeywordTaggingResult = backfill_stock_keywords(
        db, theme_keywords=theme_keywords
    )
    after = diagnose(db)

    report["reset_count"] = reset_count
    report["backfill_result"] = backfill_result
    report["after"] = after
    report["spot_check"] = spot_check(db)
    return report


def _print_report(report: dict) -> None:
    before = report["before"]
    print("=== [SPEC-AI-091] stocks.keywords 정화 스크립트 ===")
    print(f"모드: {report['mode']}")
    print(
        f"진단(정화 전): 전체 {before['total_stocks']}개 종목 중 태깅됨 "
        f"{before['tagged_stocks']}개"
    )
    print(
        f"  - 10개(상한) 보유: {before['full_cap_count']}개 "
        f"({before['full_cap_pct']:.1f}%)"
    )
    print(f"  - 중앙값 키워드 개수: {before['median_length']}")
    print(
        "  - provenance 불명 후보(SPEC-AI-084 최초 백필일 이전 생성) 종목: "
        f"{before['unknown_provenance_count']}개 (참고용, 리셋 대상 판단에는 미반영, "
        "REQ-AI091-008 보수적 기본 처리)"
    )

    if report["mode"] == "dry-run":
        print(
            "\n[DRY RUN] --execute 플래그 없이 실행됨. DB 변경 없음. "
            "실제 리셋+재백필은 --execute 플래그를 명시하세요."
        )
        return

    print(f"\n리셋 완료: {report['reset_count']}개 종목의 keywords를 NULL로 초기화")
    br: KeywordTaggingResult = report["backfill_result"]
    print(
        f"재백필 완료: 스캔 {br.stocks_scanned}개, 신규 태깅 {br.stocks_tagged}개, "
        f"기존 보존(스킵) {br.stocks_skipped_existing}개"
    )

    after = report["after"]
    print(f"\n진단(정화 후): 태깅됨 {after['tagged_stocks']}개")
    print(
        f"  - 10개(상한) 보유: {after['full_cap_count']}개 "
        f"({after['full_cap_pct']:.1f}%)  (목표: AC-AI091-009 <= 5%)"
    )
    print(f"  - 중앙값 키워드 개수: {after['median_length']} (목표: AC-AI091-009 <= 4)")

    print("\n스팟체크 (AC-AI091-010, 각 <= 3개 기대):")
    for code, length in report["spot_check"].items():
        print(f"  - {code}: {length}개")


def main() -> None:
    """프로덕션 실행 진입점."""
    parser = argparse.ArgumentParser(
        description="SPEC-AI-091: stocks.keywords 정화(리셋 후 재백필)"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="실제 리셋+재백필 실행 (기본값: dry-run 진단만, DB 변경 없음)",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        report = run_remediation(db, execute=args.execute)
        _print_report(report)
    finally:
        db.close()


if __name__ == "__main__":
    main()
