#!/usr/bin/env python
"""SPEC-AI-089 M1: 스캔 유니버스↔탐지망 배선 측정 리포트 생성 스크립트.

읽기 전용(SELECT만 수행, 쓰기 없음). REQ-AI089-002의 무시그널 실제급등 종목 풀
귀속 분석(`analyze_no_signal_pool_attribution`)을 최근 표본 거래일 각각에 대해
실행하고, 사람이 읽을 수 있는 마크다운 리포트를 `.moai/reports/surge-universe-gap/`
아래에 생성한다.

SPEC-AI-104 REQ-AI104-001/006: 거래일별 표에 누락되어 있던 pool_d 열을 추가하고,
`analyze_pool_precision_by_date()`(REQ-AI104-005)의 precision측 지표(pool_d 및
pool_a/b/c baseline)를 신규 "Pool별 정밀도" 섹션으로 동일 리포트에 병기한다.

사용: uv run python scripts/measure_universe_detection_gap_report.py [--days N]

주의: `SurgeUniverseMember`(SPEC-AI-068) 영속화가 시작된 이후 날짜만 유효한 표본이다.
과거 데이터 백필은 수행하지 않는다(spec.md Out of Scope — 전진 적용만).
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.surge_actual_outcome import SurgeActualOutcome
from app.services.surge_universe_gap_service import (
    analyze_no_signal_pool_attribution,
    analyze_pool_precision_by_date,
)

_REPORTS_DIR = Path(__file__).parent.parent.parent / ".moai" / "reports" / "surge-universe-gap"


def _recent_actual_surge_dates(db: Session, limit: int) -> list[date]:
    rows = (
        db.query(SurgeActualOutcome.trading_date)
        .filter(SurgeActualOutcome.was_surge.is_(True))
        .distinct()
        .order_by(SurgeActualOutcome.trading_date.desc())
        .limit(limit)
        .all()
    )
    return sorted(r.trading_date for r in rows)


def _fmt_precision_cell(pool_stat: dict[str, int | float | None]) -> str:
    """SPEC-AI-104 REQ-AI104-006: 풀 1개의 {total,surge_count,precision}을 `T/S/P%` 셀로 렌더링.

    total==0(division-by-zero guard, AC-104-004)이면 precision은 표기하지 않고 N/A로 대체.
    """
    total = pool_stat["total"]
    surge_count = pool_stat["surge_count"]
    precision = pool_stat["precision"]
    if precision is None:
        return f"{total}/{surge_count}/N/A"
    return f"{total}/{surge_count}/{100.0 * precision:.1f}%"


def _render_report(
    results: list[dict],
    precision_results: list[tuple[date, dict[str, dict[str, int | float | None]]]],
) -> str:
    lines = [
        "# SPEC-AI-089 M1 측정 리포트 — 스캔 유니버스↔탐지망 간극",
        "",
        f"생성 시각: {datetime.now(timezone.utc).isoformat()}",
        "",
        "REQ-AI089-002: 표본 거래일별 무시그널(disclosure_impact/preday_disclosure/"
        "volume_anomaly/gap_pullback_candidate/sector_ripple/surge_candidate 전부 부재) "
        "실제급등 종목의 T-1 스캔 유니버스 풀 귀속 분류.",
        "",
        "| T | 실제급등 | 무시그널 | 무시그널% | pool_a | pool_b | pool_c | pool_d | absent |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    total_actual = 0
    total_no_signal = 0
    agg = {"pool_a": 0, "pool_b": 0, "pool_c": 0, "pool_d": 0, "absent": 0}

    for r in results:
        if not r["sample_present"]:
            continue
        actual = r["actual_surge_count"]
        no_sig = len(r["no_signal_codes"])
        pct = (100.0 * no_sig / actual) if actual else 0.0
        summ = r["attribution_summary"]
        lines.append(
            f"| {r['trading_date']} | {actual} | {no_sig} | {pct:.1f}% | "
            f"{summ.get('pool_a', 0)} | {summ.get('pool_b', 0)} | "
            f"{summ.get('pool_c', 0)} | {summ.get('pool_d', 0)} | {summ.get('absent', 0)} |"
        )
        total_actual += actual
        total_no_signal += no_sig
        for pool, count in summ.items():
            agg[pool] = agg.get(pool, 0) + count

    lines.append("")
    lines.append("## 표본 합산")
    lines.append("")
    if total_actual:
        lines.append(f"- 표본 거래일 수: {sum(1 for r in results if r['sample_present'])}")
        lines.append(f"- 실제 급등 합계: {total_actual}")
        lines.append(
            f"- 무시그널 합계: {total_no_signal} "
            f"({100.0 * total_no_signal / total_actual:.1f}%)"
        )
        if total_no_signal:
            for pool in ("absent", "pool_a", "pool_b", "pool_c", "pool_d"):
                n = agg.get(pool, 0)
                lines.append(f"  - {pool}: {n} ({100.0 * n / total_no_signal:.1f}%)")
    else:
        lines.append("- 표본 데이터 없음")

    # SPEC-AI-104 REQ-AI104-006: precision측(그 풀 소속 전체 종목 중 실제 급등 비율) —
    # 위 recall측(무시그널 실제급등 종목의 풀 귀속)과는 다른 질문에 답한다(spec.md §Decisions D3).
    # 셀 형식: total/surge_count/precision% — total==0이면 precision은 N/A(division-by-zero guard).
    lines.append("")
    lines.append("## Pool별 정밀도(Precision)")
    lines.append("")
    lines.append(
        "REQ-AI104-005: 해당 거래일 풀 소속 전체 종목 중 실제 급등 비율 — pool_d의 노이즈 "
        "여부를 pool_a/b/c baseline과 나란히 비교한다. 셀 형식 `total/surge_count/precision%`."
    )
    lines.append("")
    lines.append("| T | pool_a | pool_b | pool_c | pool_d |")
    lines.append("|---|---|---|---|---|")
    for trading_date, precision in precision_results:
        lines.append(
            f"| {trading_date} | {_fmt_precision_cell(precision['pool_a'])} | "
            f"{_fmt_precision_cell(precision['pool_b'])} | "
            f"{_fmt_precision_cell(precision['pool_c'])} | "
            f"{_fmt_precision_cell(precision['pool_d'])} |"
        )
    if not precision_results:
        lines.append("| (표본 데이터 없음) | - | - | - | - |")

    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="SPEC-AI-089 M1 측정 리포트 생성")
    parser.add_argument("--days", type=int, default=15, help="표본 거래일 최대 개수")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        sample_dates = _recent_actual_surge_dates(db, args.days)
        results = [analyze_no_signal_pool_attribution(db, d) for d in sample_dates]
        # SPEC-AI-104 REQ-AI104-006: precision측 지표를 동일 표본 거래일 집합에 대해 병기.
        precision_results = [
            (d, analyze_pool_precision_by_date(db, d)) for d in sample_dates
        ]
    finally:
        db.close()

    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _REPORTS_DIR / f"{date.today().isoformat()}.md"
    out_path.write_text(_render_report(results, precision_results), encoding="utf-8")
    print(f"리포트 생성 완료: {out_path}")


if __name__ == "__main__":
    main()
