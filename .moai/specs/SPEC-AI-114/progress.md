# SPEC-AI-114 Progress

Status: implemented
Created: 2026-08-10
Updated: 2026-08-10

## Planning State

- [x] Root cause mapped to horizon mismatch.
- [x] Standard T-1 metric preservation stated as hard requirement.
- [x] Plan audit not separately run; implementation proceeded under explicit user kickoff.
- [x] Implementation kickoff approved by user request: "우선순위대로 spec 구현 진행".

## Implementation State

- [x] Added lane classifier: next-day, same-day, and excluded near-limit carry.
- [x] Added same-day metric computation: predicted count, TP, FP, precision, actual coverage, denominator basis.
- [x] Added compact same-day catalyst evidence DTO.
- [x] Added nested lane objects to evaluation list/detail/history API responses.
- [x] Preserved existing T-1 stored evaluation fields and SPEC-AI-110 metric fields.
- [x] Added mixed-lane regression tests proving same-day signals do not enter standard T-1 predicted set.

## Queue Position

Priority 3 in the 2026-08-10 surge prediction recovery queue because it separates
T-1 forecast skill from same-day catalyst response.

## Verification

- `backend`: `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_spec_ai_114.py -q`
  - Result: 5 passed.
- `backend`: `.\\.venv\\Scripts\\python.exe -m ruff check app\\services\\surge_lane_metrics_service.py app\\routers\\surge_trading.py tests\\test_spec_ai_114.py`
  - Result: all checks passed.
- `backend`: `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_spec_ai_092.py tests\\test_spec_ai_102.py tests\\test_spec_ai_105.py tests\\test_spec_ai_111.py tests\\test_spec_ai_112.py tests\\test_spec_ai_113.py tests\\test_spec_ai_114.py tests\\test_surge_eval_endpoints.py -q`
  - Result: 98 passed, 2 warnings from existing `datetime.utcnow()` test fixture usage.
- Attempted `tests\\test_spec_ai_110.py` in one regression command; file does not exist, so the command was corrected and rerun with existing tests.
