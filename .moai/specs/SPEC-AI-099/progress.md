# SPEC-AI-099 Progress

## §E.1 Plan-phase Audit-Ready Signal

```yaml
plan_status: audit-ready
plan_complete_at: 2026-08-03
plan_auditor_verdict: PASS
plan_auditor_score: 0.92
plan_auditor_iteration: 2/3
plan_auditor_report: .moai/reports/plan-audit/SPEC-AI-099-review-2.md
```

Iteration 1 flagged D1 (REQ-AI099-004 double-modal GEARS contradiction) and D5
(Open Question 2 timing inconsistency between acceptance.md DoD and plan.md).
Both resolved and independently re-verified PASS in iteration 2 (score 0.92).
Remaining defects (D2/D3/D4/D6/D7) are all minor/non-blocking per the review
report and do not affect Must-Pass criteria.

## §E.2 Run-phase Evidence

### AC PASS/FAIL Matrix (M1)

| AC | REQ | Status | Verification | Actual Output |
|----|-----|--------|---------------|----------------|
| AC-099-001 | REQ-AI099-001 | PASS | `pytest tests/test_spec_ai_099.py::TestPersistFeatureSnapshots -q` | 3 passed |
| AC-099-002 | REQ-AI099-001 | PASS | `test_ac099_002_rescanned_stock_creates_new_row_and_preserves_old` | 1 passed — 2 distinct rows, 1st row unchanged |
| AC-099-003 | REQ-AI099-002 | PASS | `test_ac099_003_batch_write_is_single_commit_call` | 1 passed — commit_calls == 1 for 5 candidates |
| AC-099-004 | REQ-AI099-002 | PASS | `test_ac099_004_batch_write_failure_does_not_raise` | 1 passed — no exception propagated |
| AC-099-005 | REQ-AI099-003 | PASS | `test_ac099_005_backfill_fills_labels_when_outcome_exists` | 1 passed |
| AC-099-006 | REQ-AI099-003 | PASS | `test_ac099_006_backfill_leaves_null_when_outcome_absent` + weekend edge case | 2 passed |
| AC-099-007 | REQ-AI099-004 | PASS | `test_ac099_007_no_cleanup_job_registered_for_feature_snapshots` + `grep -rn "surge_feature_snapshot" app/services/scheduler.py` | 1 passed; grep shows only backfill job registration (5 matches, 0 delete/cleanup) |
| AC-099-008 | REQ-AI099-005 | PASS | `TestFeatureSnapshotReadinessCounter` (2 tests) | 2 passed — independent of check_ml_readiness() |
| AC-099-009 | REQ-AI099-006 | PASS | `git diff -- app/services/surge_detector.py \| grep -E "^-[^-]"` (0 matches, additive-only) + `git diff --name-only \| grep fund_manager.py` (0 matches) + full regression suite | Confirmed |

### PRESERVE-list grep verification (before/after diff = 0)

| Target | Verification | Result |
|--------|--------------|--------|
| `compute_ensemble_score()` weighted-sum/consensus logic | `git diff -- app/services/surge_detector.py` shows 0 deleted lines (purely additive) | PASS |
| Main loop + 3 bypass loops threshold/bypass judgment | same diff — no lines removed inside judgment blocks | PASS |
| `fund_manager.py` FundSignal creation/update | `git diff --name-only -- app/services/fund_manager.py` → 0 matches | PASS |
| `ml_feature_engineering.py` (capture_daily_features, check_ml_readiness) | `git diff --name-only -- app/services/ml_feature_engineering.py` → 0 matches | PASS |
| `surge_calibrator.py` | `git diff --name-only -- app/services/surge_calibrator.py` → 0 matches | PASS |
| `SurgeActualOutcome`/`SurgePredictionEvaluation` schemas | `surge_actual_outcome.py` → 0 matches. `surge_prediction_evaluation.py` shows a diff, but attributable to parallel sibling-SPEC work (SPEC-AI-097/098/100, completed concurrently in this session) — not touched by SPEC-AI-099 | PASS (SPEC-AI-099 scope) |

### Test suite results

- Targeted: `pytest tests/test_spec_ai_099.py -q` → **13 passed**
- Full regression: `pytest tests/ --tb=short -q -m "not slow"` → **2332 passed, 4 skipped, 3 xpassed**
  (1 pre-existing test, `test_spec_ai_096.py::TestPoolDCountPersistence::test_alembic_revision_chain_070_to_071`,
  required updating because it hardcoded `071_...` as the alembic chain head — an
  expected consequence of adding migration `072_surge_feature_snapshot.py`. Fixed
  to assert a single-head chain with 071 as an ancestor instead of the literal head.)
- Lint: `ruff check` on all new/modified files → **All checks passed**
- Type check: `mypy` unavailable in this venv (pre-existing environment gap, consistent
  with prior SPECs in this batch — residual risk, not a new regression)

### Migration

- File: `alembic/versions/072_surge_feature_snapshot.py`
- `down_revision = "071_surge_universe_pool_history_pool_d"` (confirmed via
  `ls backend/alembic/versions/` — 071 was the actual latest at implementation time)
- Verified single chain head: `script.get_heads() == ['072_surge_feature_snapshot']`

### Trading-day utility Open Question

No existing `next_trading_day`/reusable trading-day utility was found via
`grep -rn "next_trading_day\|is_trading_day" backend/app` (only `_is_trading_day()`
in `scheduler.py`, which answers "is today a trading day" for the current moment,
not "what is the next trading day after date X"). Implemented the minimum-viable
form specified in plan.md: weekend-only skip, no KRX holiday calendar. A holiday
mid-week leaves `outcome_trading_date` pointing at a non-trading day, so the
backfill join permanently misses and the label stays `NULL` — this is the
documented fail-safe behavior per AC-099-006 (never fill an incorrect value),
not a defect. Full KRX holiday-calendar integration is out of scope for this SPEC
per plan.md §E Risks (residual risk, carried forward as-is).

### price_at_signal implementation note (documented decision)

plan.md §A.1 named `fetch_current_price_with_change_sync` (the same function
`fund_manager.py` already calls) as the reuse target for `price_at_signal`.
Calling it for every `merged` candidate (not just qualified ones) would add one
synchronous Naver API round-trip per non-promoted candidate per scan cycle —
directly working against D2's stated constraint ("스캔 사이클의 체감 지연을
늘리지 않는 것을 제약으로 한다"), since a scan cycle can evaluate dozens to
hundreds of candidates. Implemented instead: `price_at_signal` is populated via
this same function, but **only for `qualified_codes`** — the same scale
`fund_manager.py` already operates at today, so this SPEC does not add new
aggregate call volume beyond what the codebase already performs for promoted
candidates. For non-qualified rows, `price_at_signal` stays `NULL` (nullable
column, not required by any AC). No AC in `acceptance.md` asserts a specific
`price_at_signal` value, so this is a documented implementation-detail decision
within plan.md's stated flexibility ("정확한 함수 시그니처는 구현 시... 재확인"),
not a scope deviation.

## §E.3 Run-phase Audit-Ready Signal

```yaml
run_status: audit-ready
run_complete_at: 2026-08-04
run_commit_sha: pending-backfill-M1
ac_pass_count: 9
ac_fail_count: 0
preserve_list_post_run_count: 6/6 verified (5 direct PASS, 1 PASS with scope note)
new_warnings_or_lints_introduced: 0
total_run_phase_files: 8
  new:
    - backend/app/models/surge_feature_snapshot.py
    - backend/alembic/versions/072_surge_feature_snapshot.py
    - backend/app/services/surge_feature_snapshot_service.py
    - backend/tests/test_spec_ai_099.py
  modified:
    - backend/app/services/surge_detector.py
    - backend/app/services/scheduler.py
    - backend/tests/conftest.py
    - backend/tests/test_spec_ai_096.py
m1_to_mN_commit_strategy: single M1 commit (Tier M, all 6 TASKs delivered in one milestone)
```

## §E.4 Sync-phase Audit-Ready Signal

```yaml
sync_status: audit-ready
sync_complete_at: 2026-08-04
sync_commit_sha: pending-backfill-sync
b12_self_test_a: PASS  # grep -c 'SPEC-AI-099' CHANGELOG.md == 0 before emission
b12_self_test_b: PASS  # AC row count (9, §B ### headers) matches CHANGELOG claim (9)
b12_self_test_c: PASS  # all file paths in CHANGELOG entry verified via commit f100c07 --stat
changelog_entry_position: top of [Unreleased] (newest of the 4-SPEC batch 097/098/099/100 to sync-close)
frontmatter_status_transitions:
  spec_md: "in-progress -> completed"
canary_compliance_check: n/a — this SPEC defines no forward-looking policy requiring its own sync-phase self-test
```

### Sync-phase verification evidence

- `grep -c "SPEC-AI-099" CHANGELOG.md` → 0 (before this sync commit; confirms no
  duplicate entry from a parallel BATCH-SYNC session)
- AC row count cross-check: `acceptance.md` §B has 9 `### AC-099-` headings
  (AC-099-001~009); CHANGELOG entry states "9개 전량 PASS" — matches
- File-path verification: all 6 files named in the CHANGELOG entry
  (`surge_feature_snapshot.py` model, `072_surge_feature_snapshot.py`
  migration, `surge_feature_snapshot_service.py`, `surge_detector.py`,
  `scheduler.py`, `test_spec_ai_099.py`) confirmed present via
  `git show f100c07 --stat`
- PRESERVE-list re-confirmation (sync-phase, no new drift since §E.2):
  `compute_ensemble_score()` / main+bypass-loop threshold logic / `fund_manager.py`
  / `ml_feature_engineering.py` / `surge_calibrator.py` — all 0 unexpected
  diff, per §E.2 already-verified table (no re-run needed; no code changed
  between run-phase close and this sync commit)
- Migration chain integrity: `alembic/versions/072_surge_feature_snapshot.py`
  `down_revision = "071_surge_universe_pool_history_pool_d"`, single head
  confirmed at run-phase (§E.2); unchanged at sync time (no new migration
  landed in the interim)

### Gaps

- `mypy` was not re-run at sync-phase (already noted as a pre-existing venv
  gap at run-phase, §E.2) — sync-phase does not introduce a new gap here,
  it inherits the same residual-risk statement.
- Open Questions 1 (row-count management threshold) and 3 (post-calibration
  value storage) remain unresolved by design — spec.md §Open Questions and
  acceptance.md §E Definition of Done both state these do not block this
  SPEC's DoD.

### Residual risk

- Trading-day utility minimal implementation (weekend-only skip, no KRX
  holiday calendar) — documented fail-safe per §E.2; carried forward
  unchanged into sync-phase, no mitigation added in this commit.
- Storage growth from unlimited retention (D4) is an intentional decision
  with no automated safeguard; first observation point is a future SPEC
  triggered by Open Question 1, not this sync commit.
