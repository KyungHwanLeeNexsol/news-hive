# SPEC-AI-115 Progress

Status: implemented
Created: 2026-08-10

## Planning State

- [x] Root cause mapped to conservative multi-stage filtering.
- [x] Shadow-first constraint added.
- [x] Plan audit completed during implementation.
- [x] Implementation completed.

## Queue Position

Priority 4 in the 2026-08-10 surge prediction recovery queue because it explains
where currently generated candidates are dropped before official prediction.

## Implementation Summary

- Added DB-backed gate/drop observations and migration `076_surge_gate_drop_observations`.
- Added relaxed threshold shadow profile `regime_threshold_minus_0_05`.
- Added guardrail report `scripts/spec_ai_115_gate_attribution_report.py`.
- Preserved official `surge_candidate` output; shadow candidates do not emit `FundSignal`.

## Verification

- `backend> .\.venv\Scripts\python.exe -m pytest tests\test_spec_ai_115.py -q`
  - 7 passed.
- `backend> .\.venv\Scripts\python.exe -m ruff check app\services\surge_gate_attribution_service.py app\services\surge_detector.py app\services\surge_evaluation_service.py app\models\surge_gate_drop_observation.py scripts\spec_ai_115_gate_attribution_report.py tests\test_spec_ai_115.py`
  - passed.
- `backend> .\.venv\Scripts\python.exe -m pytest tests\test_spec_ai_092.py tests\test_spec_ai_102.py tests\test_spec_ai_105.py tests\test_spec_ai_111.py tests\test_spec_ai_112.py tests\test_spec_ai_113.py tests\test_spec_ai_114.py tests\test_spec_ai_115.py tests\test_surge_eval_endpoints.py -q`
  - 105 passed, 3 warnings.
- `backend> .\.venv\Scripts\python.exe scripts\spec_ai_115_gate_attribution_report.py --compact`
  - `db_unavailable` on local PostgreSQL, as expected for this workspace.
