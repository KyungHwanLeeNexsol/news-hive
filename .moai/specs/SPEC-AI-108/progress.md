# SPEC-AI-108 Progress

## §E.1 Plan-phase Audit-Ready Signal

plan_status: audit-ready
plan_complete_at: 2026-08-06
plan_audit_verdict: PASS, score 0.86 (iteration 3/3, final — `.moai/reports/plan-audit/SPEC-AI-108-review-3.md`). 2 minor non-blocking debts left open (recommended, not required): D-NEW-1 polarity typo in REQ-AI108-001 first sub-bullet ("수정해야 한다" should read "수정해서는 안 된다" — plan.md §A.1 PRESERVE table is the unambiguous authoritative source, use it over this prose); D-NEW-2 REQ-AI108-002 has no directly-mapped AC in the matrix (its behavior is de facto covered by AC-108-002/003's normalization-equivalence tests).

## §E.2 Run-phase Evidence

cycle_type: ddd (ANALYZE-PRESERVE-IMPROVE, single cycle — pure read-only diagnostic
addition, no domain restructuring warranted a multi-cycle DDD sweep). PRESERVE list
(plan.md §A.1) verified intact: `compute_horizon_signature()`,
`select_effective_threshold()`, `run_horizon_shadow_comparison()`,
`check_horizon_transition_readiness()`, `evaluate_high_based_outcomes()`,
`_persist_signal_forward_outcomes()` all unmodified (diff --stat empty on their
owning files, `git diff -- surge_detector.py surge_horizon_readiness_service.py`
empty); `ensemble.horizon_aware_thresholds.enabled`/`.shadow_mode_enabled` values
unchanged (`git diff -- surge_detection.yaml` empty); no new DB tables/columns/
migrations.

| AC ID | Status | Verification Command | Actual Output |
|-------|--------|----------------------|----------------|
| AC-108-001 | PASS | `pytest tests/test_spec_ai_108.py::TestReconstructHorizonSignatureFromBasis::test_none_returns_multi_day_dominant tests/test_spec_ai_108.py::TestReconstructHorizonSignatureFromBasis::test_empty_list_returns_multi_day_dominant -v` | PASS — both `None` and `[]` inputs return `"multi_day_dominant"` |
| AC-108-002 | PASS | `pytest tests/test_spec_ai_108.py::TestReconstructHorizonSignatureFromBasis -v -k "matches_live_function or mixed or immediate_disclosure or legacy"` | 6 passed — single same_day/next_day/multi_day keys, 2-key mixed, and the `immediate_disclosure`→`disclosure_pattern` / `legacy`→`legacy_detectors` normalization equivalence cases all match `compute_horizon_signature()`'s live output on the corresponding component-score input |
| AC-108-003 | PASS | `pytest tests/test_spec_ai_108.py::TestReconstructHorizonSignatureFromBasis::test_non_ensemble_keys_ignored -v` | PASS — `["near_limit_up_carry", "volume_breakout"]` produces the identical result (`"same_day_dominant"`) as `["volume_breakout"]` alone |
| AC-108-004 | PASS | `pytest tests/test_spec_ai_108.py::TestAnalyzePrecisionByHorizonSignature::test_all_four_buckets_present_with_correct_precision -v` | PASS — all 4 buckets (`same_day_dominant`/`next_day_dominant`/`multi_day_dominant`/`mixed`) present with hand-computed `{signal_count, forward_positive_count, precision}` matching (e.g. same_day_dominant 2/1/0.5) |
| AC-108-005 | PASS | `pytest tests/test_spec_ai_108.py::TestAnalyzePrecisionByHorizonSignature::test_does_not_requery_fund_signal_or_stock_tables -v` | PASS — `db.query` spy confirms no `FundSignal`/`Stock` model appears among queried models (only `SurgeSignalForwardOutcome` queried) |
| AC-108-006 | PASS | `pytest tests/test_spec_ai_108.py::TestAnalyzePrecisionByHorizonSignature::test_zero_signal_count_bucket_precision_is_none -v` | PASS — `mixed` bucket `signal_count=0`, `precision is None`, no `ZeroDivisionError` |
| AC-108-007 | PASS | `pytest tests/test_spec_ai_108.py::TestEvaluateSurgePredictionsHorizonDiagnosticIntegration::test_normal_cycle_logs_structured_line_with_all_buckets -v` | PASS — exactly 1 INFO-level `[지평시그니처정밀도]` log record, containing all 4 bucket-name tokens |
| AC-108-008 | PASS | `pytest tests/test_spec_ai_108.py::TestEvaluateSurgePredictionsHorizonDiagnosticIntegration::test_diagnostic_exception_does_not_block_core_result_or_eod_upsert -v` | PASS — `_analyze_precision_by_horizon_signature` mocked to raise `RuntimeError`; `SurgePredictionEvaluation` row and `SurgeSignalForwardOutcome` row both committed normally, exactly 1 WARNING log, 0 INFO `[지평시그니처정밀도]` logs |
| AC-108-009 | PASS | `git diff -- backend/app/surge_config/surge_detection.yaml` (empty) + `git diff --name-only --diff-filter=A -- backend/alembic/versions/` (empty) + `git diff --stat -- backend/app/services/surge_detector.py backend/app/services/surge_horizon_readiness_service.py` (empty) | All 3 checks empty — no config drift, no new migration, no PRESERVE-listed function body touched |
| AC-108-010 | PASS | `grep -A 30 "^## C\. 증거 활용 절차" .moai/specs/SPEC-AI-108/plan.md \| grep -c "Open Question 2\|D1\|재검토"` | 6 (all 3 required keywords present, multiple mentions) |

Scenarios (acceptance.md): Scenario 1 (normal cycle, 4-bucket precision + core result
unchanged) ⊂ AC-108-004/007/008 tests (same integration test observes both the log and
the preserved core commit); Scenario 2 (diagnostic exception isolation) ⊂ AC-108-008
test; Scenario 3 (bypass-only signal safely multi_day_dominant) ⊂
`test_bypass_only_signal_returns_multi_day_dominant`. All 3 reproduced.

## §E.3 Run-phase Audit-Ready Signal

```yaml
run_complete_at: 2026-08-06
run_commit_sha: 7ff98ce46e83954a93d3b4c9c469513b6e32ac06
run_status: PASS
ac_pass_count: 10
ac_fail_count: 0
preserve_list_post_run_count: 8
l44_pre_commit_fetch: PASS (git fetch origin main; git rev-list --count --left-right origin/main...HEAD = "0 0" before commit)
l44_post_push_fetch: PASS (git push origin main succeeded 3a12f97..7ff98ce; post-push fetch confirms "0 0" — local main == origin/main)
new_warnings_or_lints_introduced: 0 (ruff check app/services/surge_evaluation_service.py tests/test_spec_ai_108.py: All checks passed)
cross_platform_build:
  note: "Python project — no GOOS/GOARCH cross-compile applicable; app boot verified via `python -c \"from app.main import app\"` -> OK"
total_run_phase_files: 3 (surge_evaluation_service.py edited; test_spec_ai_108.py new; CHANGELOG.md [Unreleased] entry added)
m1_to_mN_commit_strategy: single M1 commit (Tier M, DDD single-cycle scope — ANALYZE(read compute_horizon_signature/_persist_signal_forward_outcomes/evaluate_surge_predictions) -> PRESERVE(regression baseline test_spec_ai_100/101/106 + test_surge_evaluation_service*.py all green, 136 passed) -> IMPROVE(add 2 pure functions + 1 isolated log block), no intermediate milestones warranted a separate commit)
```

## §E.4 Sync-phase Audit-Ready Signal

```yaml
sync_complete_at: 2026-08-06
sync_commit_sha: 9bc3c63
sync_status: PASS
changelog_entry_position: CHANGELOG.md [Unreleased] top entry (line 7)
frontmatter_status_transitions:
  spec_md: in-progress -> completed
readme_update: not-required (internal diagnostic logging only, no user-facing surface)
```

## §F Phase 4 Mode Selection

**Input parameters**: tier=M, scope=2 files (surge_evaluation_service.py extended with 2 new functions + 1 wiring block, new test_spec_ai_108.py), domain count=1, concurrency benefit=LOW (pure read-only diagnostic, but coding-heavy sequential DDD).

**Decision: sub-agent** (Mode 5).

**Plan Audit Gate**: NOT skipped — full 3-iteration audit already completed this session (FAIL→FAIL→PASS), final verdict is fresh (same session, artifact hash unchanged since iteration-3 verdict). Proceeding directly to run-phase with the audited artifacts.
