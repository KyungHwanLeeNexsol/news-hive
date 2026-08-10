# SPEC-AI-111 Plan

Status: implemented-no-go
Created: 2026-08-07

## 1. Implementation Strategy

Treat this as an activation and guardrail SPEC, not a new detector SPEC. The bridge generator already exists; the work is to make Pool A activation auditable, limited, and reversible.

## 2. Tasks

### TASK-001 - Characterize Current Bridge Behavior

Add or extend tests around `generate_scan_universe_bridge_candidates()` and `gather_surge_candidates()`:

- master switch false returns no bridge candidates;
- existing `scan_universe_bridge_pool_limits` can disable a pool with value `0`;
- returned Pool A bridge candidates carry `active_detectors=["scan_universe_bridge", "pool_a"]`;
- bridge candidates append to `qualified` without mutating `merged`.

Expected files:

- `backend/tests/test_spec_ai_092.py` or new `backend/tests/test_spec_ai_111.py`

### TASK-002 - Add Readiness Gate

Add a small read-only helper in `backend/app/services/surge_universe_gap_service.py`.

Suggested function:

```python
def evaluate_bridge_activation_readiness(
    db: Session,
    *,
    target_pool: str = "pool_a",
    min_trading_days: int = 10,
    min_precision_floor: float = 0.05,
    max_zero_precision_streak: int = 4,
) -> dict[str, object]:
    ...
```

The helper should:

- inspect recent trading dates with `surge_bridge_shadow_candidates` and `SurgeActualOutcome`;
- call or reuse `analyze_bridge_shadow_precision_by_date()` for Pool A and Pool C separation;
- read same-period `SurgePredictionEvaluation.precision`;
- require non-null `SurgePredictionEvaluation.precision` on every eligible baseline date;
- aggregate Pool A totals and surge counts;
- return `ready`, `reason`, `eligible_days`, `pool_precision`, `baseline_precision`, `zero_precision_streak`, and per-day rows.

No DB writes, migrations, or network calls.

### TASK-003 - Gate Canary Config Flip

Before changing `backend/app/surge_config/surge_detection.yaml`, run the readiness helper against the available database.

If ready:

```yaml
scan_universe_bridge_candidates_enabled: true
scan_universe_bridge_pool_b_enabled: false
scan_universe_bridge_max_candidates: 5
scan_universe_bridge_pool_limits:
  pool_a: 5
  pool_b: 0
  pool_c: 0
scan_universe_bridge_shadow_enabled: true
```

Then add exact GO evidence to `progress.md`: status, YAML values, eligible day count, Pool A aggregate precision, baseline precision, zero-precision streak, and rollback line.

If not ready:

- leave `scan_universe_bridge_candidates_enabled` false or absent;
- keep `scan_universe_bridge_shadow_enabled: true`;
- record the no-go reason in `progress.md`.

### TASK-004 - Prove Pool B And Pool D Exclusion

Add regression tests:

- Pool B entries do not enter bridge output while `scan_universe_bridge_pool_b_enabled` is false.
- `fetch_stock_price_history_batch_sync()` is not called while Pool B is disabled.
- Pool D entries do not enter bridge output even when `pool_d_min_slots` remains nonzero.

### TASK-005 - Prove Pool C Is Blocked In First Canary

Add a test fixture where Pool C would otherwise score above `_BRIDGE_MIN_SCORE`.

With `scan_universe_bridge_pool_limits={"pool_a": 5, "pool_c": 0, "pool_b": 0}`, assert that Pool C does not enter final bridge output.

### TASK-006 - Verify Observability

Add or extend tests so a real Pool A bridge candidate path verifies candidate-count observability:

- log message or structured result includes total bridge candidate count;
- log message or structured result includes Pool A bridge candidate count;
- attribution metadata remains available for downstream signal metadata.

### TASK-007 - Verify Evaluation Metric Compatibility

Run focused endpoint/service tests added by SPEC-AI-110 to ensure market recall and scannable recall remain separate after Pool A bridge candidates are present.

Expected tests:

- `backend/tests/test_surge_eval_endpoints.py`
- any focused SPEC-AI-110 regression test file if later split

### TASK-008 - Update Progress And Changelog

Update `progress.md` with:

- readiness gate result;
- GO or NO-GO evidence, including exact YAML values if GO;
- GO or NO-GO state;
- exact config values if GO;
- rollback command/config line;
- test evidence.

Update `CHANGELOG.md` only during implementation, not during this plan-only SPEC creation.

## 3. Verification Commands

Run focused tests first:

```powershell
& .\.venv\Scripts\python.exe -m pytest backend\tests\test_spec_ai_092.py backend\tests\test_spec_ai_105.py backend\tests\test_surge_eval_endpoints.py -q
```

If a new `test_spec_ai_111.py` is created, include it:

```powershell
& .\.venv\Scripts\python.exe -m pytest backend\tests\test_spec_ai_111.py backend\tests\test_spec_ai_092.py backend\tests\test_spec_ai_105.py backend\tests\test_surge_eval_endpoints.py -q
```

Run lint on changed backend files:

```powershell
& .\.venv\Scripts\python.exe -m ruff check backend\app\services\surge_universe_gap_service.py backend\app\services\surge_detector.py backend\tests\test_spec_ai_111.py
```

Run whitespace check:

```powershell
git diff --check
```

## 4. Rollback

Rollback is intentionally config-only:

```yaml
scan_universe_bridge_candidates_enabled: false
```

or remove the explicit key from `surge_detection.yaml` so the Pydantic default `False` applies.

Do not delete shadow rows during rollback. They are measurement evidence.
