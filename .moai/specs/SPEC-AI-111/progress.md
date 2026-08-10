# SPEC-AI-111 Progress

Status: implemented-no-go
Created: 2026-08-07

## Current State

Run phase completed with NO-GO for production activation. The readiness gate and regression tests are implemented, but the current app DB setting (`localhost:5432/news_hive`) is unavailable in this workspace, so no production-grade Pool A readiness decision could be made. `surge_detection.yaml` was intentionally left without `scan_universe_bridge_candidates_enabled`.

## Planning Evidence

- `generate_scan_universe_bridge_candidates()` already exists and is gated by `scan_universe_bridge_candidates_enabled`.
- `gather_surge_candidates()` already calls the bridge generator and appends bridge candidates after feature snapshot persistence.
- Pool B remains behind `scan_universe_bridge_pool_b_enabled`.
- Pool D is not a bridge target pool.
- `scan_universe_bridge_shadow_enabled: true` is already present in YAML.
- `scan_universe_bridge_candidates_enabled` is absent from YAML, so the real bridge remains disabled by default.
- The 2026-07-03 to 2026-07-27 universe gap report supports Pool A as the safest first activation target.

## Checklist

- [x] Read MoAI plan workflow.
- [x] Review bridge generator, call site, and shadow precision code.
- [x] Review SPEC-AI-092, SPEC-AI-096, SPEC-AI-104, and SPEC-AI-105 context.
- [x] Select next-priority implementation target.
- [x] Create SPEC-AI-111 research/spec/plan/acceptance/progress artifacts.
- [x] Run initial Plan Audit Gate.
- [x] Patch SPEC acceptance gaps found by audit before implementation.
- [x] Re-run Plan Audit Gate after SPEC patch.
- [x] Implement readiness gate.
- [x] Run readiness gate against available database setting.
- [x] Do not apply Pool A-only canary config because gate could not run against an available DB.
- [x] Add focused tests.
- [x] Run verification commands.
- [x] Record NO-GO result.

## Initial Decision

Proceed with Pool A-only bridge activation readiness. Pool C remains shadow-only, Pool B remains disabled, and Pool D remains measurement-only.

## Plan Audit

- Review 1: FAIL — GO config evidence, candidate-count observability, and baseline sufficiency were underspecified.
- Review 2: PASS — blockers resolved before implementation.

Reports:

- `.moai/reports/plan-audit/SPEC-AI-111-review-1.md`
- `.moai/reports/plan-audit/SPEC-AI-111-review-2.md`

## Implementation Summary

- Added `evaluate_bridge_activation_readiness()` to `backend/app/services/surge_universe_gap_service.py`.
- Added `backend/tests/test_spec_ai_111.py` with readiness, Pool A-only bridge, Pool B/D exclusion, observability, and metric compatibility coverage.
- Did not change `backend/app/surge_config/surge_detection.yaml`.

## Readiness Result

Status: NO-GO

Reason: `database_unavailable`

Evidence:

```text
& .\.venv\Scripts\python.exe -c "from app.database import SessionLocal; from app.services.surge_universe_gap_service import evaluate_bridge_activation_readiness; db=SessionLocal(); print(evaluate_bridge_activation_readiness(db)); db.close()"

psycopg2.OperationalError: connection to server at "localhost" (::1), port 5432 failed: Connection refused
```

Config state:

- `scan_universe_bridge_shadow_enabled: true` remains enabled.
- `scan_universe_bridge_candidates_enabled` remains absent/false.
- No Pool A-only GO YAML was applied.

Follow-up:

- SPEC-AI-113 owns the production DB/API readiness rerun, Pool A-only canary
  decision, and post-activation rollback monitor.

## SPEC-AI-113 Follow-up Result

2026-08-10: SPEC-AI-113 implemented a repeatable operator readiness runner,
GO-only Pool A config helper, bridge count observability, and rollback monitor.
The activation result remains NO-GO because the configured DB endpoint
`localhost:5432/news_hive` is unavailable in this workspace. Therefore this
SPEC's original production-readiness blocker is not resolved yet, and
`scan_universe_bridge_candidates_enabled` remains absent/false.

Rollback line if a future GO config is applied:

```yaml
scan_universe_bridge_candidates_enabled: false
```

## Acceptance Evidence

| AC | Status | Evidence |
|----|--------|----------|
| AC-111-001 | PASS | `tests/test_spec_ai_111.py::TestPoolAOnlyBridgeCanary::test_flag_off_keeps_pool_a_bridge_out_of_qualified` |
| AC-111-002 | PASS | `tests/test_spec_ai_111.py::TestBridgeActivationReadiness::test_blocks_when_shadow_outcome_days_are_insufficient` |
| AC-111-003 | PASS | `tests/test_spec_ai_111.py::TestBridgeActivationReadiness::test_passes_pool_a_without_blending_pool_c` |
| AC-111-004 | PASS | `tests/test_spec_ai_111.py::TestBridgeActivationReadiness::test_fails_low_pool_a_even_when_pool_c_is_high` |
| AC-111-005 | PASS | `tests/test_spec_ai_111.py::TestPoolAOnlyBridgeCanary::test_pool_a_only_config_emits_pool_a_and_blocks_pool_c` |
| AC-111-005A | N/A-NO-GO | GO config was not applied because readiness could not run against an available DB. |
| AC-111-006 | PASS | `tests/test_spec_ai_111.py::TestPoolAOnlyBridgeCanary::test_pool_a_only_config_emits_pool_a_and_blocks_pool_c` |
| AC-111-007 | PASS | `tests/test_spec_ai_111.py::TestPoolAOnlyBridgeCanary::test_pool_b_disabled_does_not_fetch_and_pool_d_is_excluded` |
| AC-111-007A | PASS | `tests/test_spec_ai_111.py::TestBridgeActivationReadiness::test_missing_baseline_precision_blocks_go` |
| AC-111-008 | PASS | `tests/test_spec_ai_111.py::TestPoolAOnlyBridgeCanary::test_pool_b_disabled_does_not_fetch_and_pool_d_is_excluded` |
| AC-111-009 | PASS | `tests/test_spec_ai_111.py::TestPoolAOnlyBridgeCanary::test_pool_a_only_config_emits_pool_a_and_blocks_pool_c` |
| AC-111-010 | PASS | `tests/test_spec_ai_111.py::TestSpecAi111MetricCompatibility::test_evaluation_endpoint_keeps_market_and_scannable_recall_with_bridge_signal` |
| AC-111-010A | PASS | `tests/test_spec_ai_111.py::TestPoolAOnlyBridgeCanary::test_pool_a_bridge_logs_total_and_pool_counts` |
| AC-111-011 | PASS | This progress section records NO-GO and confirms no config flip. |
| AC-111-011A | N/A-NO-GO | GO evidence is not applicable because GO config was not applied. |
| AC-111-012 | PASS | Flag-off test plus rollback line above. |

## Verification

```text
& .\.venv\Scripts\python.exe -m pytest tests\test_spec_ai_111.py -q
9 passed

& .\.venv\Scripts\python.exe -m pytest tests\test_spec_ai_111.py tests\test_spec_ai_092.py tests\test_spec_ai_105.py tests\test_surge_eval_endpoints.py -q
62 passed

& .\.venv\Scripts\python.exe -m ruff check app\services\surge_universe_gap_service.py tests\test_spec_ai_111.py
All checks passed!
```
