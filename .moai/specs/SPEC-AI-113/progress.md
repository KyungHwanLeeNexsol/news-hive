# SPEC-AI-113 Progress

Status: implemented-no-go
Created: 2026-08-10
Updated: 2026-08-10

## Planning State

- [x] Follow-up from SPEC-AI-111 no-go identified.
- [x] Pool A-only canary values preserved from SPEC-AI-111.
- [x] Rollback triggers copied into explicit requirements.
- [x] Plan audit not separately run; implementation proceeded under explicit user kickoff.
- [x] Implementation kickoff approved by user request: "우선순위대로 spec 구현 진행".

## Implementation State

- [x] Added production-safe readiness runner service.
- [x] Added operator JSON script for Pool A readiness.
- [x] Added non-secret data source identity reporting.
- [x] Added `database_unavailable` NO-GO result with actionable context.
- [x] Added GO-only Pool A config copy helper; repo YAML remains unchanged because readiness is NO-GO.
- [x] Added rollback guardrail evaluator and scheduler monitor callback.
- [x] Added bridge candidate count observability to evaluation/history responses.
- [x] Added acceptance tests for AC-113-001 through AC-113-007.

## Readiness Result

Status: NO-GO

Reason: `database_unavailable`

Evidence:

```text
backend> .\.venv\Scripts\python.exe scripts\spec_ai_113_bridge_readiness_report.py --compact
{"status":"no_go","reason":"database_unavailable","target_pool":"pool_a","data_source":{"scheme":"postgresql","host":"localhost","port":5432,"database":"news_hive"},"error_type":"OperationalError",...}
```

Config state:

- `backend/app/surge_config/surge_detection.yaml` still does not set
  `scan_universe_bridge_candidates_enabled`.
- `scan_universe_bridge_shadow_enabled: true` remains present.
- Pool A-only GO config was not applied.

SPEC-AI-111 closure link:

- SPEC-AI-111 previous blocker is not resolved in this workspace because no
  production-equivalent DB/API source was available.
- The blocker is now repeatably observable through
  `backend/scripts/spec_ai_113_bridge_readiness_report.py`.

## Queue Position

Priority 2 in the 2026-08-10 surge prediction recovery queue because it addresses
the second measured cause: scan-universe members are observed but not promoted into
official predictions.

## Verification

- `backend`: `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_spec_ai_113.py -q`
  - Result: 8 passed.
- `backend`: `.\\.venv\\Scripts\\python.exe -m ruff check app\\services\\surge_bridge_readiness_service.py scripts\\spec_ai_113_bridge_readiness_report.py app\\routers\\surge_trading.py app\\services\\scheduler.py tests\\test_spec_ai_113.py`
  - Result: all checks passed.
- `backend`: `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_spec_ai_092.py tests\\test_spec_ai_102.py tests\\test_spec_ai_105.py tests\\test_spec_ai_111.py tests\\test_spec_ai_112.py tests\\test_spec_ai_113.py tests\\test_surge_eval_endpoints.py -q`
  - Result: 93 passed, 2 warnings from existing `datetime.utcnow()` test fixture usage.
- `backend`: `.\\.venv\\Scripts\\python.exe scripts\\spec_ai_113_bridge_readiness_report.py --help`
  - Result: help rendered successfully.
- `backend`: `.\\.venv\\Scripts\\python.exe scripts\\spec_ai_113_bridge_readiness_report.py --compact`
  - Result: NO-GO `database_unavailable`.
