---
id: SPEC-AI-061
version: 0.1.0
status: draft
created: 2026-06-23
updated: 2026-06-23
author: manager-spec
priority: high
issue_number: null
---

# SPEC-AI-061: Surge Auto-Improvement Loop Structural Hardening

## HISTORY

- 2026-06-23 (v0.1.0): Initial draft. Consolidates four structural defects observed
  in the live surge auto-improvement loop on 2026-06-22: (P0) rollback pendulum
  A↔B oscillation, (P0) `_run_surge_verify_predictions` PendingRollbackError,
  (P1) negative-expected-value asymmetry, (P1) sector_contagion repeat failures,
  (P2) `surge_actual_outcome.stock_name` storing ticker codes instead of names.

---

## Background

The daily closed-loop self-improvement system (SPEC-AI-041 / AI-043) collects
actual surgers, evaluates T-1 signals, and auto-adjusts ensemble weights plus
`min_score_for_signal`. As of 2026-06-22 the loop is functionally stalled and, in
two areas, actively harmful.

### Observed evidence (2026-06-22, production DB)

1. **Rollback pendulum.** `surge_auto_improvement_log` shows the system flip-flopping
   between two parameter states (call them A and B) on consecutive evaluation days:
   - 2026-06-19 10:03 UTC: auto_rollback A → B
   - 2026-06-22 10:04 UTC: auto_rollback B → A
   - Trigger each time: `prev_recall=0.000 < rolling_avg*0.80=0.009`.
   Both states have recall ≈ 0, so neither is an improvement; the loop only rolls
   back, never converges. Root cause confirmed in `surge_auto_improver.py`
   `analyze_and_improve()` Step 5 (rollback) which swaps `old_value`/`new_value`
   with no cooldown, no parameter-set identity check, and no consecutive-rollback
   tracking.

2. **Negative expected value.** `improvement_logs` (failure_aggregation):
   total_verified=136, accuracy_rate=37.5% (surge_candidate 38.5%, preday_disclosure
   45.8%, disclosure_impact 37.5%, buy 0%). avg_return_correct=+1.44%,
   avg_return_incorrect=-11.39%. Expected value per signal
   = 0.375 × (+1.44) + 0.625 × (-11.39) ≈ **-6.58%**. The asymmetry (small wins,
   large losses) makes the strategy expected-value-negative even before fees.

3. **verify_predictions error.** `_run_surge_verify_predictions`
   (`scheduler.py:599`) raises `PendingRollbackError` on `db.commit()` repeatedly
   (daily 18:30 KST). The function performs multiple commits (post-FN-analysis at
   `scheduler.py:654`, post-TP-analysis at `:719`); when an intermediate query/commit
   fails (e.g. SSL drop → `OperationalError`), the session enters
   `InFailedSqlTransaction` and every subsequent statement fails. The outer
   `except` at `:727` re-raises, so the evaluation result is not durably recorded.

4. **sector_contagion repeat failures.** sector_contagion is the #1 failure
   cause (28 of the verified failures). Today it exists only as a post-hoc *label*
   produced by `signal_verifier._classify_disclosure_failure`
   (`signal_verifier.py:90-102`): any disclosure-based failure lacking supply
   keywords is bucketed as sector_contagion. There is no *preventive* filter at
   signal-generation time that suppresses signals likely to suffer sector-wide
   contagion.

5. **stock_name data quality.** `surge_actual_outcome.stock_name` contains ticker
   codes for some rows (e.g. `475430 | 475430`). Source:
   `surge_actual_outcome_service.py:134` writes `stock_name=code` as a fallback,
   then attempts to backfill from the `Stock` table (`:145-169`). Rows whose
   ticker is absent from the `Stock` table (new listings, preferred shares,
   delisted) keep the code, so downstream reports and Telegram messages show codes.

### Why one consolidated SPEC

All five defects share the same daily loop and the same files
(`surge_auto_improver.py`, `scheduler.py`, `surge_actual_outcome_service.py`,
`signal_verifier.py`, `surge_detection.yaml`). Fixing them piecemeal risks
re-introducing the pendulum. They are specified together but isolated into
independent requirement groups so each can be implemented and verified in priority
order.

---

## Scope

### In Scope

- Pendulum-prevention controls on the auto-rollback path (cooldown, parameter-set
  identity check, consecutive-rollback escalation).
- Transaction-safety hardening of `_run_surge_verify_predictions` so a partial
  failure cannot poison the session or lose the evaluation result.
- An expected-value guard: either raise the confidence bar for signal admission
  when the rolling expected value is negative, or apply a stop-loss-style cap on
  recorded outcomes used for evaluation, configurable via YAML.
- A preventive sector_contagion suppression gate at signal-generation time, layered
  on top of existing gates.
- A correctness fix and backfill for `surge_actual_outcome.stock_name`.

### Out of Scope (deferred / other SPECs)

- Re-enabling real buy execution (governed by SPEC-AI-043 prediction-record mode;
  threshold/regime owned by SPEC-AI-029). This SPEC must remain compatible with
  prediction-record mode and MUST NOT enable live trading.
- Detector weight calibration math itself (owned by SPEC-AI-041) — this SPEC only
  adds *guards around* the rollback decision, not a new calibration formula.
- Adding new detectors (coverage owned by SPEC-AI-044 / AI-050 / AI-051).
- LLM cause-analysis enrichment (owned by SPEC-AI-060).
- Probability/regime threshold logic (owned by SPEC-AI-029 / AI-038).

---

## Glossary

- **Pendulum**: repeated auto-rollback between two parameter states with no net
  improvement.
- **Parameter set**: the tuple of all parameters touched by a single day's
  auto-improvement run (ensemble weights + min_score_for_signal + any window
  changes), used for identity comparison.
- **Expected value (EV)**: probability-weighted average return per emitted signal,
  computed over the rolling evaluation window.
- **sector_contagion**: failure mode where a signal stock falls due to sector-wide
  bad news rather than the stock's own catalyst.

---

## Requirements (EARS)

### Group A — Pendulum Prevention (P0)

- **REQ-AI061-A01** (Unwanted): The auto-improvement loop **shall not** apply an
  auto-rollback whose resulting parameter set is identical (within 1e-6 per value)
  to a parameter set that was active within the preceding `rollback_cooldown_days`
  (configurable, default 5 trading days).

- **REQ-AI061-A02** (Event-Driven): **When** a candidate auto-rollback is evaluated,
  the system **shall** compute a stable hash of the resulting parameter set and
  compare it against the hashes of the last `rollback_cooldown_days` applied parameter
  sets recorded in `surge_auto_improvement_log`; **if** a match is found, **then** the
  system **shall** skip the rollback and record a log entry with rationale
  `rollback_suppressed_pendulum`.

- **REQ-AI061-A03** (State-Driven): **While** the loop has performed
  `consecutive_rollback_limit` (configurable, default 2) consecutive auto-rollbacks
  on consecutive evaluation days, the system **shall not** perform a further plain
  rollback; instead it **shall** freeze auto-adjustment of the affected parameters
  and record a log entry with rationale `rollback_frozen_escalation`, leaving
  parameters at their current values until human intervention.

- **REQ-AI061-A04** (Event-Driven): **When** the rollback path is suppressed or
  frozen by REQ-A01/A02/A03, the system **shall** include this fact in the daily
  Telegram report (`format_telegram_report` / `run_daily_report`).

- **REQ-AI061-A05** (Ubiquitous): All new pendulum-control thresholds
  (`rollback_cooldown_days`, `consecutive_rollback_limit`) **shall** be read from a
  configuration section (auto.yaml-compatible) and **shall** have safe defaults so
  that absence of the keys does not disable the guard.

### Group B — verify_predictions Transaction Safety (P0)

- **REQ-AI061-B01** (Unwanted): `_run_surge_verify_predictions` **shall not** allow a
  failure in the optional FN-analysis or TP-analysis blocks to leave the database
  session in an `InFailedSqlTransaction` state that blocks subsequent commits.

- **REQ-AI061-B02** (Event-Driven): **When** any query or commit inside
  `_run_surge_verify_predictions` raises an exception, the system **shall** issue an
  explicit `db.rollback()` before attempting any further database statement.

- **REQ-AI061-B03** (State-Driven): **While** the core evaluation
  (`evaluate_surge_predictions`) has succeeded, the system **shall** durably persist
  precision/recall/f1 **even if** the optional FN/TP enrichment blocks fail, by
  committing the core evaluation before the optional blocks run.

- **REQ-AI061-B04** (Unwanted): The optional enrichment blocks **shall not** re-raise
  in a way that loses the already-committed evaluation result; enrichment failures
  **shall** be logged and isolated.

### Group C — Expected-Value Guard (P1)

- **REQ-AI061-C01** (Event-Driven): **When** the rolling-window expected value (EV)
  over the last `ev_window_days` (configurable, default 5 trading days) is below
  `ev_floor` (configurable, default 0.0), the system **shall** raise
  `min_score_for_signal` by `ev_penalty_step` (configurable, default +0.02), bounded
  by the existing min_score clamp [0.35, 0.65].

- **REQ-AI061-C02** (State-Driven): **While** EV is at or above `ev_floor`, the
  EV guard **shall not** modify `min_score_for_signal` (it defers to the existing
  recall/precision adjustment in SPEC-AI-041).

- **REQ-AI061-C03** (Ubiquitous): The system **shall** compute EV as
  `accuracy × avg_return_correct + (1 − accuracy) × avg_return_incorrect` using the
  same verified-outcome data already aggregated for evaluation, and **shall** record
  the computed EV in the daily report and in the improvement log rationale.

- **REQ-AI061-C04** (Optional): Where outcome data for the EV computation is
  insufficient (fewer than `ev_min_samples`, configurable, default 20 verified
  signals), the system **shall** skip the EV guard for that day rather than acting on
  a noisy estimate.

### Group D — sector_contagion Preventive Gate (P1)

- **REQ-AI061-D01** (Event-Driven): **When** a candidate signal is being generated and
  the candidate's sector exhibits a contagion condition (sector breadth of decliners
  exceeding `sector_contagion_decline_ratio`, configurable, default 0.60, among the
  sector's tracked stocks for the current evaluation context), the system **shall**
  suppress or down-weight the candidate before it is recorded as a signal.

- **REQ-AI061-D02** (State-Driven): **While** the sector_contagion gate is enabled,
  a candidate suppressed by REQ-D01 **shall** be recorded in `surge_metadata` with a
  suppression reason so it can be audited, and **shall not** be emitted as a
  `surge_candidate` FundSignal.

- **REQ-AI061-D03** (Ubiquitous): The sector_contagion gate **shall** reuse the
  existing sector mapping (`Stock.sector_id → Sector.name`) and the existing actual /
  price data paths; it **shall not** introduce a new external data fetch beyond what
  the signal-generation path already performs.

- **REQ-AI061-D04** (Optional): Where the sector breadth cannot be computed (sector
  has too few tracked stocks, fewer than `sector_min_stocks`, configurable, default 5),
  the gate **shall** pass the candidate through unchanged (fail-open) to avoid
  starving sparse sectors.

### Group E — stock_name Data Quality (P2)

- **REQ-AI061-E01** (Event-Driven): **When** writing a `surge_actual_outcome` row,
  **if** the resolved `stock_name` equals the `stock_code` (i.e. the Stock-table
  backfill found no name), **then** the system **shall** attempt one additional name
  resolution via the available name source before persisting, and **shall** flag the
  row (e.g. via a nullable name-resolution status) when no human-readable name is
  available.

- **REQ-AI061-E02** (Unwanted): The system **shall not** silently overwrite an
  existing human-readable `stock_name` with a ticker code on upsert conflict.

- **REQ-AI061-E03** (Ubiquitous): A one-time backfill **shall** correct existing
  `surge_actual_outcome` rows whose `stock_name` equals `stock_code` by resolving the
  name from the `Stock` table where available.

### Cross-Cutting

- **REQ-AI061-X01** (Ubiquitous): All new behavior **shall** be controllable via
  configuration (auto.yaml-compatible, protected from `git reset --hard` per the
  existing `_write_auto_yaml` mechanism) and **shall** default to safe values that
  preserve current behavior where a guard is not yet warranted.

- **REQ-AI061-X02** (Ubiquitous): The system **shall** remain in prediction-record
  mode; no requirement in this SPEC **shall** enable live buy execution.

- **REQ-AI061-X03** (Ubiquitous): All new and modified public functions **shall**
  carry @MX annotations consistent with the existing surge_auto_improver tagging
  (`[AUTO] SPEC-AI-061`), and YAML-writing paths **shall** carry `@MX:WARN` with
  `@MX:REASON`.

---

## Constraints

- **Data**: Per [[project-surge-detector-constraints]], the signal-generation price
  helper `_fetch_price_change_sync` returns only `{current_price, change_rate}` (no
  `open_price`; change_rate is previous-close based). The sector_contagion gate
  (Group D) MUST be expressible using `change_rate` / actual-outcome breadth, NOT
  intraday minute data or open_price.
- **DB schema**: `FundSignal` has no `stock_code` column; matching to ticker-keyed
  actuals requires a `Stock.stock_code` join. `surge_probability_score` /
  `surge_basis` live inside the `surge_metadata` JSON, not as columns.
- **No numpy/scipy/sklearn** in the backend (pyproject.toml). Any numeric work must
  be pure-Python.
- **YAML weight invariant**: ensemble weights validated by
  `validate_ensemble_weights` must sum to 1.0 (5 detector weights + weekend_gap_up).
  The pendulum guards (Group A) MUST preserve this invariant when suppressing /
  freezing rollbacks.
- **Scheduler**: cron jobs use `timezone="Asia/Seoul"` with KST hours passed
  directly. Group B changes are confined to `_run_surge_verify_predictions`
  (18:30 KST) and MUST NOT change its schedule or signature in a way that breaks the
  registered job.
- **Migration**: Group E status flag (if added as a column) requires a new Alembic
  migration with `down_revision` = current head (verify head before implementation;
  AI-060 introduced migration 061).
- **Ownership boundaries**: weight calibration math = SPEC-AI-041; probability /
  regime threshold = SPEC-AI-029 / AI-038; coverage detectors = AI-044/050/051; LLM
  cause analysis = AI-060. This SPEC adds only guards/safety/data-quality.

---

## Assumptions

1. The rollback pendulum is driven entirely by the value-swap rollback in
   `analyze_and_improve()` Step 5; no other code path writes auto_rollback log rows.
   → Correct me if a second rollback writer exists.
2. The PendingRollbackError originates from an intermediate failure (SSL drop or a
   failed enrichment query) inside `_run_surge_verify_predictions`, not from
   `evaluate_surge_predictions` itself.
3. Sector membership is available via `Stock.sector_id → Sector.name`, and
   `surge_actual_outcome` (was_surge / change_rate per code per day) is a usable
   proxy for sector breadth on the evaluation date.
4. EV can be computed from the same aggregation that produced
   accuracy_rate / avg_return_correct / avg_return_incorrect in `improvement_logs`.
5. Raising `min_score_for_signal` is an acceptable lever for the EV guard given live
   trading is disabled (it reduces recorded signals, improving precision/EV without
   real-money risk).

---

## Exclusions (What NOT to Build)

- **No live trading enablement.** This SPEC must not flip prediction-record mode to
  real buy execution. (Owned by SPEC-AI-043.)
- **No new calibration formula.** The detector-weight proportional-adjustment math in
  SPEC-AI-041 is unchanged; this SPEC only wraps the rollback decision with guards.
- **No new detector.** Coverage expansion is out of scope (AI-044/050/051).
- **No probability-threshold or regime-cap changes.** Owned by AI-029 / AI-038.
- **No new external data fetch for the sector gate.** Group D must reuse existing
  data paths; a gate requiring intraday minute bars or open_price is explicitly
  excluded as unimplementable in the current path.
- **No LLM enrichment changes.** AI-060 owns per-stock cause analysis; this SPEC does
  not modify `analyze_misses_with_llm` / `analyze_true_positives_with_llm` behavior
  (Group B only hardens the transaction boundary around their call sites).
- **No schema redesign of surge_actual_outcome** beyond an optional name-resolution
  status flag for Group E.

---

## Acceptance Criteria Summary

See `acceptance.md` for full Given-When-Then scenarios. Quality gate: pendulum
provably broken (no identical-set rollback within cooldown), verify_predictions
durably records evaluation under simulated mid-job failure, EV guard raises
min_score only when EV<floor with sufficient samples, sector gate suppresses
contagion candidates while failing open on sparse sectors, and no
`surge_actual_outcome` row written by the fixed path has `stock_name == stock_code`
when a name is resolvable.

---

## Related SPECs

- **SPEC-AI-041** (prerequisite): owns the auto-improvement loop and weight
  calibration. This SPEC modifies the rollback guard within it.
- **SPEC-AI-043** (prerequisite): prediction-record mode paradigm; must stay
  compatible.
- **SPEC-AI-060** (sibling): per-stock cause analysis runs in the same
  `_run_surge_verify_predictions` job; Group B must preserve AI-060's isolated
  enrichment block.
- **SPEC-AI-029 / AI-038**: probability/regime threshold ownership (do not touch).
- **SPEC-AI-028**: existing post-hoc sector_contagion *labeling* in
  `signal_verifier.py`; Group D adds the *preventive* counterpart.
