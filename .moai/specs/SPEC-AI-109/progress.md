# SPEC-AI-109 Progress

## Plan

plan_status: completed
plan_complete_at: 2026-08-07

## Run

cycle_type: ddd
status: completed

Implemented:

- Added `repair_missing_surge_evaluation()` to compose actual outcome collection and
  prediction evaluation safely.
- Wired `_run_surge_missing_evaluation_check()` to attempt one automatic repair when
  missing rows are detected.
- Added admin-only `POST /api/surge-trading/evaluation-backfill` for date range
  backfill.
- Guarded historical actual collection by default because the existing actual collector
  uses current top-mover data.
- Added focused service, scheduler, and API tests.

Verification:

- `& .\backend\.venv\Scripts\python.exe -m pytest .\backend\tests\test_spec_ai_092.py::TestMissingEvaluationMonitor .\backend\tests\test_surge_eval_endpoints.py::TestEvaluationBackfill -q`
  - Result: 11 passed
- `& .\backend\.venv\Scripts\python.exe -m pytest .\backend\tests\test_spec_ai_092.py .\backend\tests\test_surge_eval_endpoints.py -q`
  - Result: 38 passed
- `& .\backend\.venv\Scripts\python.exe -m ruff check .\backend\app\services\surge_evaluation_service.py .\backend\app\services\scheduler.py .\backend\app\routers\surge_trading.py .\backend\tests\test_spec_ai_092.py .\backend\tests\test_surge_eval_endpoints.py`
  - Result: All checks passed
