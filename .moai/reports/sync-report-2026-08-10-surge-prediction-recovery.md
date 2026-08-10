# Sync Report — Surge Prediction Recall Recovery

Date: 2026-08-10
Mode: explicit `moai sync`
Scope: SPEC-AI-112 through SPEC-AI-116
Delivery: PR-ready, not committed or pushed

## Summary

The surge prediction recovery batch is synchronized across SPEC documents, ROADMAP, CHANGELOG,
project living docs, DB migration notes, and verification evidence.

## SPEC Status

| SPEC | Status | Notes |
|------|--------|-------|
| SPEC-AI-112 | implemented | Absent actual attribution and source-pool discovery implemented. |
| SPEC-AI-113 | implemented-no-go | Bridge readiness/canary guardrails implemented; production GO waits for operating evidence. |
| SPEC-AI-114 | implemented | Same-day catalyst lane and horizon-specific metrics implemented. |
| SPEC-AI-115 | implemented | Gate/drop attribution and relaxed gate shadow observation implemented. |
| SPEC-AI-116 | implemented | Missing-trigger detector pack implemented as shadow-only. |

## Documentation Updated

- `CHANGELOG.md`: added SPEC-AI-112~116 release notes and deployment notes.
- `.moai/specs/ROADMAP.md`: Phase 9 queue now shows SPEC-AI-116 as implemented.
- `.moai/project/product.md`: added surge prediction recovery observation capability.
- `.moai/project/structure.md`: added new services and models.
- `.moai/project/tech.md`: added SPEC-AI-112~116 implementation history.
- `.moai/project/db/migrations.md`: added pending migrations 076 and 077.
- `.moai/project/db/schema.md`: added shadow observation/candidate tables and indexes.
- `.moai/specs/SPEC-AI-112` through `.moai/specs/SPEC-AI-116`: no draft status remains in the recovery batch.

## Implementation Divergence

No blocking divergence remains for the recovery batch. The implementation intentionally keeps
high-recall changes in shadow mode:

- SPEC-AI-115 relaxed gate candidates are persisted as observations only.
- SPEC-AI-116 missing-trigger candidates are persisted as shadow candidates only.
- SPEC-AI-113 remains implemented-no-go until bridge canary readiness data passes.

This is expected and preserves official `FundSignal` behavior until operating evidence supports
promotion.

## Verification Evidence

- `backend> .\.venv\Scripts\python.exe -m pytest tests\test_spec_ai_116.py -q`
  - 7 passed.
- `backend> .\.venv\Scripts\python.exe -m ruff check app\services\surge_missing_trigger_detector_service.py app\models\surge_missing_trigger_shadow_candidate.py scripts\spec_ai_116_missing_trigger_shadow_report.py tests\test_spec_ai_116.py app\surge_config\surge_settings.py`
  - passed.
- `backend> .\.venv\Scripts\python.exe -m pytest tests\test_spec_ai_092.py tests\test_spec_ai_102.py tests\test_spec_ai_105.py tests\test_spec_ai_111.py tests\test_spec_ai_112.py tests\test_spec_ai_113.py tests\test_spec_ai_114.py tests\test_spec_ai_115.py tests\test_spec_ai_116.py tests\test_surge_eval_endpoints.py -q`
  - 112 passed, 3 warnings.
- `moai spec lint .moai\specs\SPEC-AI-112\spec.md` through `SPEC-AI-116`
  - no findings.
- `backend> .\.venv\Scripts\python.exe scripts\spec_ai_115_gate_attribution_report.py --compact`
  - local DB unavailable, expected in this workspace.
- `backend> .\.venv\Scripts\python.exe scripts\spec_ai_116_missing_trigger_shadow_report.py --compact`
  - local DB unavailable, expected in this workspace.

## Deployment Notes

Apply migrations before enabling production operator runs:

1. `076_surge_gate_drop_observations`
2. `077_surge_missing_trigger_shadow_candidate`

After deployment, monitor at least 10 eligible trading days before production promotion:

- `scripts/spec_ai_115_gate_attribution_report.py --compact`
- `scripts/spec_ai_116_missing_trigger_shadow_report.py --compact`

## Delivery Decision

No commit or PR was created during this sync. The repository has a broad pre-existing dirty
worktree including MoAI framework/plugin changes unrelated to the surge prediction recovery
batch. Staging or committing automatically would risk mixing unrelated changes with this delivery.

Recommended delivery path: stage only the recovery batch files and create a focused commit/PR.
