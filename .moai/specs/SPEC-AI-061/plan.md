# SPEC-AI-061 Implementation Plan

## Overview

Five independent, priority-ordered requirement groups hardening the surge
auto-improvement loop. Each group is implementable in isolation; recommended order
follows priority (A and B are P0, C and D are P1, E is P2).

## Technical Approach

### Group A — Pendulum Prevention (P0)

**Target**: `backend/app/services/surge_auto_improver.py` `analyze_and_improve()`
Step 5 (rollback block, current lines ~395-444).

Approach:
- Before applying a rollback, build the resulting parameter set and compute a stable
  hash (sorted dot-path → rounded value tuple, hashed with `hashlib`).
- Query the last `rollback_cooldown_days` of `surge_auto_improvement_log`, reconstruct
  each day's applied parameter set, hash, and compare. On match → record
  `rollback_suppressed_pendulum` log and return without writing the swap.
- Track consecutive rollbacks: count consecutive prior days whose rationale is
  `auto_rollback`. If `>= consecutive_rollback_limit` → record
  `rollback_frozen_escalation`, skip auto-adjustment of the affected parameters for
  the day.
- Read `rollback_cooldown_days` / `consecutive_rollback_limit` from config with safe
  defaults (reuse `get_surge_config()` extension or a dedicated config block;
  prefer adding to the existing surge config model so auto.yaml override works).
- Surface suppression/freeze state to `format_telegram_report`.

Risk: parameter-set reconstruction from log rows must match exactly how Step 6 writes
them. Mitigation: hash only the `parameter_path → new_value` pairs that the loop
itself writes, derived from the same log rows.

### Group B — verify_predictions Transaction Safety (P0)

**Target**: `backend/app/services/scheduler.py` `_run_surge_verify_predictions`
(lines 599-732).

Approach:
- Commit the core evaluation (precision/recall/f1) immediately after
  `evaluate_surge_predictions` succeeds, before the FN block (REQ-B03).
- Wrap the FN-analysis block and the TP-analysis block each in their own try/except
  that calls `db.rollback()` on failure (REQ-B02) and logs without re-raising
  (REQ-B04). The existing AI-060 TP block already has isolation at `:724` — extend the
  FN block (`:623-655`) with the same pattern and add `db.rollback()` to both.
- Ensure the outer `except` at `:727` no longer loses an already-committed evaluation;
  the core result is durable before the optional blocks run.

Risk: changing commit ordering must not double-commit or partially write the
evaluation row. Mitigation: commit core eval once; enrichment updates are separate
column writes on the same row, each guarded.

### Group C — Expected-Value Guard (P1)

**Target**: `backend/app/services/surge_auto_improver.py` Step 4 (min_score
adjustment, lines ~365-392).

Approach:
- Compute EV from the rolling verified outcomes (same data feeding
  accuracy/avg_return aggregation). Pure-Python.
- If samples `< ev_min_samples` → skip (REQ-C04). If EV `< ev_floor` → add
  `ev_penalty_step` to the min_score delta (REQ-C01), still clamped to [0.35, 0.65].
  If EV `>= ev_floor` → no EV-driven change (REQ-C02).
- Record EV in the log rationale and the Telegram report (REQ-C03).
- Read `ev_window_days`, `ev_floor`, `ev_penalty_step`, `ev_min_samples` from config.

Risk: interaction with the existing recall/precision delta. Mitigation: EV guard
augments the same `new_min_score` computation; combined delta is clamped once.

### Group D — sector_contagion Preventive Gate (P1)

**Target**: signal-generation path in `backend/app/services/surge_detector.py`
(candidate emission sites) + new config block.

Approach:
- At candidate emission, resolve the candidate's sector
  (`Stock.sector_id → Sector.name`).
- Compute sector breadth of decliners from available data (e.g. fraction of the
  sector's tracked stocks with negative change_rate on the evaluation context),
  reusing existing fetched data — no new external fetch (REQ-D03).
- If breadth `> sector_contagion_decline_ratio` and sector has
  `>= sector_min_stocks` → suppress/down-weight and stamp `surge_metadata` with the
  suppression reason (REQ-D02). Otherwise fail-open (REQ-D04).
- Config: new `sector_contagion_gate` block with `enabled`,
  `sector_contagion_decline_ratio`, `sector_min_stocks`.

Risk: sector breadth proxy quality given data-only-daily constraint. Mitigation:
default ratio conservative (0.60), gate disabled-by-default until validated, fail-open
on sparse sectors.

### Group E — stock_name Data Quality (P2)

**Target**: `backend/app/services/surge_actual_outcome_service.py` (lines 120-189) +
one-time backfill script + optional migration.

Approach:
- After the Stock-table backfill (`:166-169`), for any row where
  `stock_name == stock_code`, attempt one more resolution from an available name
  source; if still unresolved, set a nullable name-resolution status flag (REQ-E01).
- Change the upsert `on_conflict_do_update` so it does NOT overwrite an existing
  human-readable name with a code (REQ-E02) — e.g. use a SQL CASE/COALESCE that keeps
  the existing name when the incoming value equals the code.
- Backfill script: update existing rows where `stock_name = stock_code` using the
  `Stock` table (REQ-E03).
- Migration only if the status flag is added as a column (verify head first).

Risk: upsert conflict logic must remain idempotent. Mitigation: characterization test
on the upsert before/after.

## Milestones (priority order, no time estimates)

1. **M1 (P0) — Pendulum + Transaction safety**: Group A + Group B. Stops active harm
   (oscillation and lost evaluations).
2. **M2 (P1) — Expected value + sector gate**: Group C + Group D. Improves EV and
   reduces #1 failure cause.
3. **M3 (P2) — Data quality**: Group E + backfill. Cleans reporting.

## Files Touched (anticipated)

- `backend/app/services/surge_auto_improver.py` (A, C)
- `backend/app/services/scheduler.py` (B)
- `backend/app/services/surge_detector.py` (D)
- `backend/app/services/surge_actual_outcome_service.py` (E)
- `backend/app/surge_config/surge_settings.py` + `surge_detection.yaml` (config for A/C/D)
- `backend/alembic/versions/` (E, only if status flag column added — verify head)
- `backend/scripts/` (E backfill)
- `backend/tests/` (all groups)

## Risks

- **Cross-SPEC collision**: surge_auto_improver.py and surge_detector.py are shared by
  many SPECs. Keep changes additive and config-gated; do not alter the AI-041
  calibration math or AI-029/038 threshold logic.
- **YAML weight invariant**: Group A must not break the sum-to-1.0 invariant when
  suppressing rollbacks.
- **Default-off safety**: P1 gates (C, D) should default conservative or disabled
  until validated against live data, to avoid replacing the pendulum with a new
  failure mode.
- **Migration head drift**: verify Alembic head before adding any Group E column.

## Verification Commands

- Backend tests: `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"`
- Lint: `cd backend && uv run ruff check . && uv run mypy app/`
- Import sanity: `cd backend && uv run python -c "from app.main import app; print('OK')"`
