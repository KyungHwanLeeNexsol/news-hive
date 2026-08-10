#!/usr/bin/env python
"""SPEC-AI-116 missing trigger detector shadow/readiness report."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.exc import SQLAlchemyError

from app.database import SessionLocal
from app.services.surge_missing_trigger_detector_service import (
    generate_missing_trigger_shadow_readiness_report,
    run_missing_trigger_shadow_detector_pack,
    select_missing_trigger_detector_families,
)
from app.surge_config.surge_settings import get_surge_config


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SPEC-AI-116 missing trigger detector shadow JSON report"
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
        help="minimum evaluated shadow days before GO",
    )
    parser.add_argument(
        "--run-shadow",
        action="store_true",
        help="run and persist shadow detector candidates for --date",
    )
    parser.add_argument(
        "--date",
        type=_parse_date,
        default=None,
        help="shadow run trading date in YYYY-MM-DD format",
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
        if args.run_shadow:
            if args.date is None:
                parser.error("--run-shadow requires --date")
            report = run_missing_trigger_shadow_detector_pack(
                db,
                args.date,
                get_surge_config(),
            )
        else:
            readiness = generate_missing_trigger_shadow_readiness_report(
                db,
                days=args.days,
                end_date=args.end_date,
                min_eligible_days=args.min_eligible_days,
            )
            selection = select_missing_trigger_detector_families(
                db,
                days=args.days,
                min_eligible_days=args.min_eligible_days,
            )
            report = {"readiness": readiness, "selection": selection}
            if readiness.get("status") != "ok":
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
