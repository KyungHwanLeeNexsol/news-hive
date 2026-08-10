#!/usr/bin/env python
"""SPEC-AI-115 gate/drop attribution shadow report."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.exc import SQLAlchemyError

from app.database import SessionLocal
from app.models.disclosure import Disclosure as _Disclosure  # noqa: F401
from app.models.fund_signal import FundSignal as _FundSignal  # noqa: F401
from app.models.stock import Stock as _Stock  # noqa: F401
from app.services.surge_gate_attribution_service import (
    generate_gate_drop_shadow_report,
)


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SPEC-AI-115 gate/drop attribution shadow JSON report"
    )
    parser.add_argument("--days", type=int, default=20, help="eligible evaluation days")
    parser.add_argument(
        "--end-date",
        type=_parse_date,
        default=None,
        help="inclusive end date in YYYY-MM-DD format",
    )
    parser.add_argument(
        "--min-eligible-days",
        type=int,
        default=10,
        help="minimum evaluation days before GO recommendation",
    )
    parser.add_argument(
        "--max-candidate-multiplier",
        type=float,
        default=2.0,
        help="NO-GO if relaxed candidates exceed this multiplier without precision gain",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="print compact JSON instead of pretty JSON",
    )
    args = parser.parse_args()

    db = SessionLocal()
    exit_code = 0
    try:
        report = generate_gate_drop_shadow_report(
            db,
            days=args.days,
            end_date=args.end_date,
            min_eligible_days=args.min_eligible_days,
            max_candidate_multiplier=args.max_candidate_multiplier,
        )
        if report.get("status") != "go":
            exit_code = 1
    except SQLAlchemyError as exc:
        exit_code = 2
        report = {
            "status": "db_unavailable",
            "reason": "database_unavailable",
            "error_type": exc.__class__.__name__,
            "message": str(exc).splitlines()[0],
        }
    finally:
        db.close()

    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=None if args.compact else 2,
        )
    )
    if exit_code:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
