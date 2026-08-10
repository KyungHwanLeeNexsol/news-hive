# SPEC-AI-112 Progress

Status: implemented
Created: 2026-08-10
Updated: 2026-08-10

## Planning State

- [x] Root cause linked to recent operating metrics.
- [x] Scope limited to attribution/reporting; no signal emission.
- [x] Dependencies mapped to SPEC-AI-092/096/104/105/109/110.
- [x] Plan audit not separately run; implementation proceeded under explicit user kickoff.
- [x] Implementation kickoff approved by user request: "우선순위대로 spec 구현 진행".

## Implementation State

- [x] Added read-only absent miss attribution service.
- [x] Reused `predicted_codes_json` restore and standard T-1 exclusion helper semantics.
- [x] Added deterministic primary bucket precedence and secondary evidence tags.
- [x] Added compact news/disclosure/signal/liquidity/theme evidence payloads without article body.
- [x] Added script operator path with default `--days 20`.
- [x] Added DB-unavailable JSON status for script execution when local PostgreSQL is not running.
- [x] Added acceptance tests for AC-112-001 through AC-112-007.

## Queue Position

Priority 1 in the 2026-08-10 surge prediction recovery queue because it addresses
the largest measured cause: actual surges absent from the active candidate surface.

## Verification

- `backend`: `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_spec_ai_112.py -q`
  - Result: 8 passed.
- `backend`: `.\\.venv\\Scripts\\python.exe -m ruff check app\\services\\surge_absent_attribution_service.py scripts\\spec_ai_112_absent_attribution_report.py tests\\test_spec_ai_112.py`
  - Result: all checks passed.
- `backend`: `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_spec_ai_092.py tests\\test_spec_ai_104.py tests\\test_spec_ai_111.py tests\\test_spec_ai_112.py -q`
  - Result: 51 passed, 2 warnings from existing `datetime.utcnow()` test fixture usage.
- `backend`: `.\\.venv\\Scripts\\python.exe -m mypy ...`
  - Result: not run; `mypy` is not installed in `backend/.venv`.
- `backend`: `.\\.venv\\Scripts\\python.exe scripts\\spec_ai_112_absent_attribution_report.py --days 1 --compact`
  - Result: `db_unavailable`; default local PostgreSQL `localhost:5432` refused connection.
