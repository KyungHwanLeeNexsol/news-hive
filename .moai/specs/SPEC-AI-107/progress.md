# SPEC-AI-107 Progress

## §E.1 Plan-phase Audit-Ready Signal

plan_status: audit-ready
plan_complete_at: 2026-08-06
plan_audit_verdict: PASS-WITH-DEBT, score 0.92 (iteration 2, `.moai/reports/plan-audit/SPEC-AI-107-review-2.md`); D1/D2 (GEARS trigger-word + min_calibration_samples pass-through) fixed post-audit, AC-107-011 added

## §E.2 Run-phase Evidence

cycle_type: ddd (ANALYZE-PRESERVE-IMPROVE). PRESERVE list (plan.md §A.1) verified
intact: `_run_pav()`/`IsotonicModel.predict()` unmodified; active
`data/surge_calibrator.pkl` never written by any new code path (AC-107-002 test
confirms); `fund_manager.py` quality-floor gate lines untouched;
`signal_verifier.py`'s Bayesian `calibrate_confidence()` untouched;
`get_surge_calibration_pairs()` unmodified (sibling function added instead).

| AC ID | Status | Verification Command | Actual Output |
|-------|--------|----------------------|----------------|
| AC-107-001 | PASS | `pytest tests/test_spec_ai_107.py::TestRunShadowTraining::test_sufficient_data_creates_candidate_and_logs -v` | PASS — candidate_{YYYYMMDD}.pkl created, run.candidate_path exists |
| AC-107-002 | PASS | `pytest tests/test_spec_ai_107.py::TestRunShadowTraining::test_active_pkl_and_singleton_unchanged -v` | PASS — active pkl absent before/after, `id(get_calibrator())` unchanged |
| AC-107-003 | PASS | `pytest tests/test_spec_ai_107.py::TestRunShadowTraining::test_two_consecutive_runs_append_not_overwrite -v` | PASS — 2 consecutive runs → +2 lines in runs.jsonl, 5 required fields present |
| AC-107-004 | PASS | `pytest tests/test_spec_ai_107.py::TestRunShadowTraining::test_insufficient_sample_count_skips_training tests/test_spec_ai_107.py::TestRunShadowTraining::test_insufficient_positive_count_skips_training -v` | PASS — both (a) 49<50 samples and (b) 60 samples/3<15 positive → sufficient_data=False, candidate_path=None, no .pkl created |
| AC-107-005 | PASS | `git diff --name-only \| grep -c alembic; git diff --name-only -- backend/app/models/` | 0 alembic/versions files; only pre-existing unrelated `surge_prediction_evaluation.py` dirty state (not touched this session) |
| AC-107-006 | PASS | `pytest tests/test_spec_ai_107.py::TestSchedulerHandler::test_exception_is_isolated_no_reraise -v` | PASS — mocked exception caught, warning logged, no re-raise, db.close() called |
| AC-107-007 | PASS | `pytest tests/test_surge_calibrator.py -v` (6 existing AC-1~6) + `pytest tests/test_spec_ai_107.py::TestTrainIsotonicMinPositiveSamples -v` | 24 passed (existing suite incl. AC-1~6) + 3 passed (new min_positive_samples tests, incl. omitted-arg byte-identical check) |
| AC-107-008 | PASS | `pytest tests/test_spec_ai_107.py::TestSchedulerHandler::test_job_registered_exactly_once_with_expected_cron -v` | PASS — exactly 1 add_job call with id=surge_calibrator_shadow_training, day_of_week=sun, hour=3, minute=0, timezone=Asia/Seoul |
| AC-107-009 | PASS | `pytest tests/test_spec_ai_107.py::TestFloorResolution::test_none_uses_surge_config_min_calibration_samples -v` | PASS — monkeypatched config value (30) used as floor when min_calibration_samples arg omitted |
| AC-107-010 | PASS | `grep -A 40 "^## C\. 프로모션 및 롤백 절차" .moai/specs/SPEC-AI-107/plan.md \| grep -c "게이트 통과 확인\|프로모션 실행\|롤백 경로"` | 3 (all 3 required keywords present in plan.md §C) |
| AC-107-011 | PASS | `pytest tests/test_spec_ai_107.py::TestFloorResolution::test_resolved_floor_passed_to_train_isotonic_not_internal_default -v` | PASS — spy confirms train_isotonic() receives min_calibration_samples=37 (monkeypatched, distinct from internal default 50), not the internal default |

Scenarios (acceptance.md): Scenario 1 (sufficient data) ⊂ AC-107-001/003 tests;
Scenario 2 (positive-scarce) ⊂ AC-107-004 test; Scenario 3 (DB exception
isolation) ⊂ AC-107-006 test. All 3 reproduced.

## §E.3 Run-phase Audit-Ready Signal

```yaml
run_complete_at: 2026-08-06
run_commit_sha: 26a37bccf950480ff479c3cc599cc7c8a16d310b
run_status: PASS
ac_pass_count: 11
ac_fail_count: 0
preserve_list_post_run_count: 6
l44_pre_commit_fetch: PASS (git fetch origin main; git rev-list --count --left-right origin/main...HEAD = "0 0" before commit)
l44_post_push_fetch: PASS (git push origin main succeeded 279a166e0..26a37bccf; post-push fetch confirms "0 0" — local main == origin/main)
new_warnings_or_lints_introduced: 0 (ruff check: All checks passed; 1 self-caught unused-import warning fixed before final run)
cross_platform_build:
  note: "Python project — no GOOS/GOARCH cross-compile applicable; app boot verified via `python -c \"from app.main import app\"`"
total_run_phase_files: 4 (surge_calibrator.py, signal_verifier.py, scheduler.py edited; test_spec_ai_107.py new)
m1_to_mN_commit_strategy: single M1 commit (Tier M, DDD single-cycle scope — ANALYZE(read existing) -> PRESERVE(regression baseline 40/40 passed) -> IMPROVE(extend train_isotonic + add shadow training pipeline + scheduler wiring), no intermediate milestones warranted a separate commit)
```

## §E.4 Sync-phase Audit-Ready Signal

```yaml
sync_complete_at: 2026-08-06
sync_commit_sha: 40ac9f4
sync_status: PASS
changelog_verified: true (cross-checked against get_surge_calibration_pairs_with_time(),
  split_walk_forward()/compute_brier_score()/run_shadow_training()/promote_candidate() in
  surge_calibrator.py, _run_surge_calibrator_shadow_training() cron Sunday 03:00 KST in
  scheduler.py — all function names, file paths, and cron schedule confirmed accurate;
  no CHANGELOG edit required)
readme_disposition: no update (internal shadow-training infrastructure, no user-facing
  surface — consistent with SPEC-AI-104/105/106 judgment)
b12_self_test_a: PASS (grep -c 'SPEC-AI-107' CHANGELOG.md == 1 before this commit — no
  duplicate entry)
b12_self_test_b: PASS (acceptance.md SSOT AC row count == 11 matches CHANGELOG's stated
  REQ-AI107-001~009 + AC-107-001~011 coverage)
b12_self_test_c: PASS (backend/app/services/surge_calibrator.py, signal_verifier.py,
  scheduler.py all verified present via grep of actual function definitions)
test_evidence: "pytest tests/test_spec_ai_107.py tests/test_surge_calibrator.py -q -m
  \"not slow\" -> 47 passed"
```

## §F Phase 4 Mode Selection

**Input parameters**: tier=M, scope=5 files (signal_verifier.py sibling function, surge_calibrator.py training pipeline, scheduler.py wiring, new test_spec_ai_107.py, plan.md §C docs), domain count=1, concurrency benefit=LOW.

**Decision: sub-agent** (Mode 5) — coding-heavy Tier M, sequential.

**Plan Audit Gate**: re-executed (not skipped) because artifact hash changed post-iteration-1 verdict. Iteration-2 verdict PASS-WITH-DEBT 0.92; the 2 flagged defects (GEARS trigger-word, min_calibration_samples pass-through ambiguity) fixed before this run-phase delegation. Proceeding with the corrected artifacts.
