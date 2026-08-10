# SPEC-AI-116 Progress

Status: implemented
Created: 2026-08-10

## Planning State

- [x] Root cause mapped to missing trigger classes.
- [x] Shadow-first and horizon compatibility requirements added.
- [x] Plan audit completed during implementation.
- [x] Implementation completed.

## Queue Position

Priority 5 in the 2026-08-10 surge prediction recovery queue because trigger expansion
should follow attribution, bridge canary, horizon separation, and gate-drop measurement.

## Implementation Summary

- Added model and migration `077_surge_missing_trigger_shadow_candidate`.
- Added shadow detector pack service `surge_missing_trigger_detector_service.py`.
- Added operator script `scripts/spec_ai_116_missing_trigger_shadow_report.py`.
- Added config flags for missing-trigger shadow mode and independent detector-family enablement.
- Added per-family readiness guardrails and separate same-day/next-day shadow lane reporting.
- Preserved production behavior: no shadow candidate emits `FundSignal` or changes standard T-1 predicted-set metrics.

## Verification

- `backend> .\.venv\Scripts\python.exe -m pytest tests\test_spec_ai_116.py -q`
  - 7 passed.
- `backend> .\.venv\Scripts\python.exe -m ruff check app\services\surge_missing_trigger_detector_service.py app\models\surge_missing_trigger_shadow_candidate.py scripts\spec_ai_116_missing_trigger_shadow_report.py tests\test_spec_ai_116.py app\surge_config\surge_settings.py`
  - passed.
- `backend> .\.venv\Scripts\python.exe -m pytest tests\test_spec_ai_092.py tests\test_spec_ai_102.py tests\test_spec_ai_105.py tests\test_spec_ai_111.py tests\test_spec_ai_112.py tests\test_spec_ai_113.py tests\test_spec_ai_114.py tests\test_spec_ai_115.py tests\test_spec_ai_116.py tests\test_surge_eval_endpoints.py -q`
  - 112 passed, 3 warnings.
- `backend> .\.venv\Scripts\python.exe scripts\spec_ai_116_missing_trigger_shadow_report.py --help`
  - passed.
- `backend> .\.venv\Scripts\python.exe scripts\spec_ai_116_missing_trigger_shadow_report.py --compact`
  - `db_unavailable` on local PostgreSQL, as expected for this workspace.
