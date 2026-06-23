# SPEC-AI-061 Acceptance Criteria

Given-When-Then scenarios per requirement group. Minimum 2 scenarios per P0/P1 group.

## Group A — Pendulum Prevention (P0)

### AC-A-01 — Identical-set rollback within cooldown is suppressed
- **Given** the auto-improvement log contains a parameter set X applied within the
  last `rollback_cooldown_days`
- **When** `analyze_and_improve()` evaluates a candidate auto-rollback whose resulting
  parameter set hashes identical to X
- **Then** no value-swap rollback rows are written, a log entry with rationale
  `rollback_suppressed_pendulum` is recorded, and the YAML weight invariant (sum 1.0)
  is preserved.

### AC-A-02 — Consecutive-rollback escalation freezes adjustment
- **Given** the loop has recorded `auto_rollback` on `consecutive_rollback_limit`
  consecutive prior evaluation days
- **When** `analyze_and_improve()` would perform another plain rollback
- **Then** it records `rollback_frozen_escalation`, does not write a further swap, and
  leaves the affected parameters unchanged.

### AC-A-03 — Normal rollback still works outside cooldown
- **Given** the candidate rollback's resulting parameter set does NOT match any set
  from the last `rollback_cooldown_days` and consecutive count is below the limit
- **When** the rollback trigger fires
- **Then** the rollback is applied as before and recorded with rationale
  `auto_rollback`.

### AC-A-04 — Suppression appears in daily report
- **Given** a rollback was suppressed or frozen by AC-A-01/AC-A-02
- **When** the daily Telegram report is generated
- **Then** the report states the rollback was suppressed/frozen.

### AC-A-05 — Missing config keys do not disable the guard
- **Given** `rollback_cooldown_days` / `consecutive_rollback_limit` are absent from
  config
- **When** the loop runs
- **Then** safe defaults (5 / 2) are applied and the guard remains active.

## Group B — verify_predictions Transaction Safety (P0)

### AC-B-01 — Core evaluation persists despite enrichment failure
- **Given** `evaluate_surge_predictions` succeeds but the FN-analysis block raises
  (e.g. simulated SSL drop)
- **When** `_run_surge_verify_predictions` runs
- **Then** precision/recall/f1 are durably committed and no `PendingRollbackError` is
  raised to the scheduler.

### AC-B-02 — Rollback issued before next statement after a failure
- **Given** an intermediate query raises inside the FN or TP block
- **When** the next database statement is attempted
- **Then** an explicit `db.rollback()` has been issued first, so the session is not in
  `InFailedSqlTransaction` state.

### AC-B-03 — TP enrichment failure isolated (AI-060 preserved)
- **Given** the TP-analysis block (SPEC-AI-060) raises
- **When** the job completes
- **Then** the evaluation result remains committed and the failure is logged without
  re-raising (AI-060's existing isolation is retained).

### AC-B-04 — Schedule and signature unchanged
- **Given** the fixed function
- **When** the scheduler registers the 18:30 KST job
- **Then** the job id, schedule, and `_run_surge_verify_predictions()` signature are
  unchanged.

## Group C — Expected-Value Guard (P1)

### AC-C-01 — Negative EV raises min_score
- **Given** the rolling EV over `ev_window_days` is below `ev_floor` with at least
  `ev_min_samples` verified signals
- **When** `analyze_and_improve()` computes the min_score adjustment
- **Then** `min_score_for_signal` is increased by `ev_penalty_step`, clamped to
  [0.35, 0.65], and the EV value is recorded in the log rationale.

### AC-C-02 — Non-negative EV leaves min_score to existing logic
- **Given** EV is at or above `ev_floor`
- **When** the loop runs
- **Then** the EV guard makes no change to `min_score_for_signal` (existing
  recall/precision adjustment governs).

### AC-C-03 — Insufficient samples skip the guard
- **Given** fewer than `ev_min_samples` verified signals in the window
- **When** the loop runs
- **Then** the EV guard is skipped and a log/Telegram note records the skip.

### AC-C-04 — EV formula matches aggregated data
- **Given** accuracy=0.375, avg_return_correct=+1.44, avg_return_incorrect=-11.39
- **When** EV is computed
- **Then** EV ≈ -6.58 (within rounding), confirming the formula
  `accuracy×correct + (1−accuracy)×incorrect`.

## Group D — sector_contagion Preventive Gate (P1)

### AC-D-01 — Contagion candidate suppressed
- **Given** a candidate whose sector has decliner breadth above
  `sector_contagion_decline_ratio` and at least `sector_min_stocks` tracked stocks,
  with the gate enabled
- **When** the signal-generation path emits candidates
- **Then** the candidate is suppressed/down-weighted, not emitted as a
  `surge_candidate` FundSignal, and the suppression reason is stamped in
  `surge_metadata`.

### AC-D-02 — Sparse sector fails open
- **Given** a candidate whose sector has fewer than `sector_min_stocks` tracked stocks
- **When** the gate runs
- **Then** the candidate passes through unchanged (fail-open).

### AC-D-03 — Gate uses no new external fetch
- **Given** the gate computes sector breadth
- **When** it runs
- **Then** it uses only data already available in the signal-generation path
  (Stock→Sector mapping + existing actual/price data), with no additional API call.

### AC-D-04 — Gate disabled by default preserves current behavior
- **Given** `sector_contagion_gate.enabled` is false (default)
- **When** signals are generated
- **Then** behavior is identical to pre-SPEC behavior.

## Group E — stock_name Data Quality (P2)

### AC-E-01 — Resolvable name is written, not the code
- **Given** an actual-outcome row for a ticker present in the `Stock` table
- **When** the row is upserted
- **Then** `stock_name` is the human-readable name, never the ticker code.

### AC-E-02 — Existing name not overwritten by code on conflict
- **Given** an existing row with a human-readable `stock_name`
- **When** an upsert arrives whose incoming `stock_name` equals the code
- **Then** the existing human-readable name is preserved.

### AC-E-03 — Unresolvable name flagged, not silently coded
- **Given** a ticker absent from the `Stock` table and unresolvable
- **When** the row is written
- **Then** the row is flagged (name-resolution status) rather than silently storing a
  code as if it were a name.

### AC-E-04 — Backfill corrects existing coded rows
- **Given** existing rows where `stock_name == stock_code` and the ticker is in the
  `Stock` table
- **When** the backfill runs
- **Then** those rows are updated to the resolved name.

## Edge Cases

- Empty evaluation window (no prior days): pendulum guard and EV guard skip safely.
- All detector hit-rates zero (current production state): rollback path must not loop;
  guards must converge to suppression/freeze rather than oscillation.
- Sector with all decliners but below min-stocks: fail-open.
- Ticker that is a valid name-equals-code coincidence (should not occur for KRX
  6-digit codes vs names, but treat numeric-only stock_name as unresolved).

## Definition of Done

- [ ] All P0 (Group A, B) acceptance criteria pass with tests.
- [ ] All P1 (Group C, D) acceptance criteria pass with tests; P1 gates default to
      safe/conservative or disabled.
- [ ] Group E backfill executed and verified (no `stock_name == stock_code` for
      resolvable tickers in the fixed path).
- [ ] `uv run pytest tests/ --tb=short -q -m "not slow"` green.
- [ ] `uv run ruff check .` and `uv run mypy app/` clean.
- [ ] `uv run python -c "from app.main import app; print('OK')"` succeeds.
- [ ] No live trading enabled (prediction-record mode preserved).
- [ ] YAML weight sum-to-1.0 invariant holds after every guard path.
- [ ] @MX annotations added for new/changed public functions and YAML-writing paths.
- [ ] Alembic head verified before any Group E column/migration.
