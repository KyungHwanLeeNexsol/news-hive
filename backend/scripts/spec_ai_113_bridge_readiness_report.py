#!/usr/bin/env python
"""SPEC-AI-113 Pool A bridge readiness and rollback JSON report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.services.surge_bridge_readiness_service import (
    evaluate_pool_a_bridge_rollback_guardrails,
    run_pool_a_bridge_readiness,
)
from app.surge_config.surge_settings import get_surge_config


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SPEC-AI-113 Pool A bridge readiness JSON report"
    )
    parser.add_argument(
        "--include-rollback",
        action="store_true",
        help="include rollback guardrail status for the current config",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="print compact JSON instead of pretty JSON",
    )
    args = parser.parse_args()

    report = run_pool_a_bridge_readiness()
    if args.include_rollback and report.get("reason") != "database_unavailable":
        db = SessionLocal()
        try:
            report["rollback_monitor"] = evaluate_pool_a_bridge_rollback_guardrails(
                db,
                get_surge_config(),
            )
        finally:
            db.close()

    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=None if args.compact else 2,
        )
    )
    if report.get("status") != "go":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
