#!/usr/bin/env python
"""SPEC-AI-112 absent actual attribution report.

Usage:
    python scripts/spec_ai_112_absent_attribution_report.py --days 20

The script is read-only and prints JSON to stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.exc import SQLAlchemyError

from app.database import SessionLocal
from app.services.surge_absent_attribution_service import (
    generate_absent_miss_attribution_report,
)


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SPEC-AI-112 absent actual attribution JSON report"
    )
    parser.add_argument("--days", type=int, default=20, help="eligible trading days")
    parser.add_argument(
        "--end-date",
        type=_parse_date,
        default=None,
        help="inclusive end date in YYYY-MM-DD format",
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
        report = generate_absent_miss_attribution_report(
            db,
            days=args.days,
            end_date=args.end_date,
        )
    except SQLAlchemyError as exc:
        exit_code = 2
        report = {
            "status": "db_unavailable",
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
            sort_keys=False,
        )
    )
    if exit_code:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
