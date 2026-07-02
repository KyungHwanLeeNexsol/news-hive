## SPEC-AI-069 Progress

- Started: 2026-07-02
- Phase 0.9: Python (backend/pyproject.toml) detected → moai-lang-python
- Phase 0.95: 8 files, single domain (backend) → Standard Mode (manager-strategy + expert-backend + manager-quality)
- Harness level: standard (file_count > 3, single domain, priority=High not critical)
- Development mode: ddd (quality.yaml)
- Dependency: SPEC-AI-068 completed (commits d9c03e7, 2e26696) — Scannable Recall available for REQ-003 retargeting

### Phase 1 (manager-strategy) — Plan proposed, AWAITING USER APPROVAL (no response after 60s, paused)

manager-strategy verified all plan.md assumptions against live code and found 3 important corrections:
- base `surge_detection.yaml` already has `legacy_detectors` weight = 0.00 (not something to "restore" to a nonzero value)
- SPEC-AI-068 already made `recall` column transition to `scannable_recall` when universe exists — REQ-003's real change is auto_improver reading `today_eval.scannable_recall` explicitly (not the generic `.recall`)
- Migration number is **066** (065 was consumed by SPEC-AI-068), not 065 as plan.md assumed

Task breakdown proposed (T-001~T-010, M1→M2→M3→M4→M5, DDD methodology):
- M1 (P0, safest/immediate): T-001 auto_improve_enabled flag (default false) gating `analyze_and_improve`; T-002 auto.yaml reset mechanism (empty override file, base yaml authoritative, no hardcoded values); T-003 z-score flag `relative_scoring.zscore_enabled` default false gating the setattr at `surge_detector.py:2011-2016`
- M2 (P0): T-004 `run_backtest_gate` verdict logic (pass/fail/insufficient) in `surge_backtest.py`; T-005 migration 066 `surge_backtest_result` table; T-006 scheduler cron job at **18:45 KST** (between 18:30 eval jobs and 19:00 auto-improve job)
- M3 (P0, unblocked — SPEC-AI-068 done): T-007 retarget `analyze_and_improve` to read `today_eval.scannable_recall` (skip adjustment if None); T-008 backtest-verdict gate before all `_write_auto_yaml` call sites
- M4 (P1): T-009 calibrator invalid-state surfacing, direction (b) explicit disconnect + documentation (recommended, not yet confirmed)
- M5 (P0): T-010 full regression + lint/type + buy-logic diff-0 verification

Three open decisions asked via AskUserQuestion, no response yet:
1. Overall plan approval (Proceed / Modify / Postpone)
2. Backtest cron slot: 18:45 KST (recommended) vs custom
3. Calibrator direction: (b) explicit disconnect (recommended) vs (a) add training job
4. auto.yaml reset mechanism: empty the override file entirely (recommended) vs selectively revert only known keys

**Resume instruction**: Re-ask these 4 questions via AskUserQuestion at the start of the next `/moai run SPEC-AI-069` invocation before proceeding to Phase 1.5/manager-ddd. Full task detail is in the manager-strategy agent transcript (agentId a68eb166bef94fa9a) if still resumable, otherwise re-derive from this summary — the technical decisions above are already verified against code and don't need re-verification.

---

## Phase 2 (manager-ddd) — DDD ANALYZE-PRESERVE-IMPROVE execution — COMPLETE (2026-07-02)

User approval of the 4 decisions was already provided upstream (decisions embedded directly in the manager-ddd invocation prompt); manager-ddd proceeded directly to ANALYZE without re-asking.

### ANALYZE

- Confirmed manager-strategy's 3 corrections against live code: `legacy_detectors` weight = 0.00 in base yaml (not restore target), SPEC-AI-068 already exposes `scannable_recall` column, migration number = 066 (down_revision = 065_surge_universe_members).
- Read all target files: `surge_auto_improver.py`, `surge_backtest.py`, `surge_detector.py` (z-score block at lines 2007-2053), `surge_baseline_service.py`, `surge_calibrator.py`, `surge_settings.py`, `scheduler.py`, `fund_manager.py`, `main.py` lifespan, existing test suites.
- Confirmed `retrain_calibrator()` has zero scheduler call sites — calibrator is genuinely dead/no-op in production (supports decision (b) explicit disconnect).
- Confirmed `_restore_auto_yaml()` in `main.py` lifespan only fires when auto.yaml is absent — establishes the ordering requirement for T-002 (reset must run first to make the file "exist" and short-circuit DB-based restoration).

### PRESERVE

- Baseline run (surge-related test files only): 74 passed, 1 pre-existing failure (`test_surge_detector.py::TestVolumeNewsCombo::test_characterize_low_zscore_no_candidate` — unrelated z-score sign issue in `volume_news_combo`'s own detector-local z-score, not the SPEC-AI-065 baseline-service z-score touched by this SPEC). This failure persisted unchanged through the entire DDD cycle and is explicitly out of scope.
- All existing characterization tests in `test_surge_auto_improver.py`, `test_surge_backtest.py`, `test_spec_ai_065.py` served as the safety net; extended with a per-file `autouse` fixture (`_enable_auto_improve_for_legacy_tests`) that sets `auto_improve_enabled=true` and seeds a passing `SurgeBacktestResult` so pre-existing tests continue exercising the original internal logic unaffected by the two new upstream gates (Step 0, backtest gate).

### IMPROVE — M1 (auto_improve_enabled flag, auto.yaml reset, z-score flag)

- T-001: Added `auto_improve_enabled: bool = False` to `SurgeDetectionConfig` + base yaml. `analyze_and_improve` Step 0 gate returns `[]` immediately when disabled (ANCHOR signature unchanged).
- T-002: Implemented `reset_auto_yaml_to_base()` in `surge_auto_improver.py` — empties auto.yaml entirely (no per-key hardcoding), skips when base yaml's `auto_improve_enabled=true`, calls `reload_surge_config()` internally (bug caught by characterization test: initial implementation omitted this call, leaving the config singleton stale after reset — fixed). Wired into `main.py` lifespan **before** `_restore_auto_yaml()` so the emptied file short-circuits DB-based restoration.
- T-003: Added `relative_scoring.zscore_enabled: bool = False` config flag. Extracted the SPEC-AI-065 z-score setattr logic (lines ~2011-2016) into a new pure function `_apply_relative_scoring()` in `surge_detector.py` (minimal extraction per SPEC's explicit allowance, not a rewrite) — gates whether `zscore_to_score()`'s normalized value is applied vs. raw score kept. `update_baselines()` call is unaffected (baseline warming continues regardless of flag, per REQ-004).

### IMPROVE — M2 (backtest gate)

- T-004: Added `run_backtest_gate()` + `BacktestGateVerdict` dataclass to `surge_backtest.py`. Calls `compute_surge_backtest()` internally without modifying it (ANCHOR API contract preserved). Verdict logic: `insufficient` (signals < floor), `pass` (accuracy >= floor), `fail` (otherwise). Added `BacktestGateConfig` (`min_signals=20`, `min_directional_accuracy=0.50`, `lookback_days=30`) nested under `BacktestConfig.gate`.
- T-005: Created `SurgeBacktestResult` SQLAlchemy model (`backend/app/models/surge_backtest_result.py`) and filled migration `066_surge_backtest_result.py` (stub → real `op.create_table`/`op.create_index`). Registered in `models/__init__.py` and `tests/conftest.py`'s model-import list.
- T-006: Added `_run_surge_backtest_gate()` wrapper in `scheduler.py` (SessionLocal + try/except/finally + `_is_kr_market_open` guard, matching existing pattern) and registered cron job at **18:45 KST mon-fri** (id=`surge_backtest_gate`, distinct from `surge_verify_predictions` 18:30 and `surge_auto_improve` 19:00, `max_instances=1, coalesce=True, replace_existing=True`).

### IMPROVE — M3 (backtest gate governance + Scannable Recall retargeting)

- T-007: Retargeted `analyze_and_improve`'s Step 4 min_score adjustment to read `today_eval.scannable_recall` instead of `today_eval.recall`. `scannable_recall is None` → skip adjustment (conservative). Updated the downstream log rationale to reflect the actual driving metric. Left Step 4.3 (volume_breakout bypass threshold, SPEC-AI-063-owned) and Step 5 (R12 rollback pendulum detection, AI-061-owned) untouched — out of REQ-003's literal scope (only the min_score block was named).
- T-008: Added `_check_backtest_gate(db)` helper querying the latest `SurgeBacktestResult` (`ORDER BY run_date DESC, created_at DESC`); returns `(False, "no_record")` when no record exists (EC-2, conservative). Computed once after the R11 gate (Step 1.5) and threaded through all 4 `_write_auto_yaml` call sites: EV guard (Step 4.5), R12 rollback (Step 5), window expansion (Step 5.5), and the main weight/min_score/vb-bypass write (Step 6). When blocked, Step 6 additionally resets `final_weight`/`new_min_score`/`new_vb_bypass` to current values so Step 7 doesn't log phantom changes. R12's blocked path records `backtest_gate_blocked:<verdict>` rationale logs instead of `auto_rollback`. AI-061's pendulum/EV guards remain fully intact and evaluated first — the backtest gate is strictly additive.

### IMPROVE — M4 (calibrator surfacing)

- T-009: Added `get_calibrator_status()` to `surge_calibrator.py` (returns `is_identity`/`trained_at`/`sample_count`). `format_telegram_report()` gained an optional `calibrator_status` parameter (backward compatible, default `None`) that appends a warning line when `is_identity=True`. `run_daily_report()` computes the status (exception-isolated) and passes it through. Direction (b) confirmed: no training-job wiring added; `fund_manager.py:1385`'s calibration call site got an explanatory comment documenting the explicit-disconnect decision (comment-only change, zero logic diff).

### M5 — Validation

- Full backend suite: `uv run pytest tests/ --tb=short -q -m "not slow"` → **1776 passed, 1 pre-existing failure (unrelated), 4 skipped, 3 xpassed**. The 1 failure is the same pre-existing `test_characterize_low_zscore_no_candidate` identified during ANALYZE/baseline — unchanged, confirmed out of scope.
- `ruff check .` (full backend): all checks passed, zero warnings.
- `mypy` not installed in this environment (no mypy config in `pyproject.toml`) — skipped gracefully per project convention.
- Buy/portfolio logic diff: **0 files** — confirmed via `git status --short` (no `surge_trading_service.py`, no portfolio model files in the diff). `fund_manager.py`'s only change is a 4-line explanatory comment (zero logic diff, verified via `git diff`).
- One regression caught and fixed during M5: `test_spec_ai_050.py::TestAC3WindowExpansion::test_ac_3_1_recall_zero_3days_window_expansion` broke because T-008's gate defaults to blocked (no `SurgeBacktestResult` record) — fixed by seeding a passing verdict in that test (consistent with the new precondition all `analyze_and_improve` write-path tests must satisfy going forward).

### Divergence from planned files (tasks.md)

Additional files touched beyond the original plan, all required to keep the DDD safety net green:
- `backend/tests/conftest.py` — registered `SurgeBacktestResult` in the model-import list for `test_engine` fixture (required for `Base.metadata.create_all` to include the new table in test DBs).
- `backend/tests/test_services/test_scheduler.py` — added `TestRunSurgeBacktestGate` (T-006 wrapper tests).
- `backend/tests/test_spec_ai_050.py` — one-line fix (seeded passing `SurgeBacktestResult`) to keep a pre-existing AI-050 characterization test green under the new T-008 gate.
- `backend/tests/test_spec_ai_069.py` (new) — primary SPEC-AI-069 test suite, 31 tests covering T-003/T-004/T-007/T-008/T-009 in isolation from `test_surge_auto_improver.py`'s autouse fixture (so gate-blocking scenarios can be tested precisely).

No planned files were skipped. All M1-M5 milestones complete.

---

## Post-review gap closure (2026-07-02) — manager-quality / evaluator-active independent verification

Overall verdict: PASS. Two gaps identified and closed before commit; no code logic changes required (test reinforcement + comment correction only, per coordinator instruction).

### Gap 1 (MEDIUM, evaluator-active) — EV guard "allowed" branch untested

`surge_auto_improver.py:733-762` (EV guard, Step 4.5): the gate-**blocked** branch was already covered by `test_ev_guard_blocked_by_backtest_gate`, but the gate-**allowed** branch (EV guard fires AND `_write_auto_yaml` is actually called with the expected `min_score_for_signal` bump) had no test — unlike the other 3 write sites (R12 rollback, window expansion, main write), which already had both directions covered.

Fix: added `test_ev_guard_allowed_writes_when_gate_passes` to `TestBacktestGateBlocksEvGuardAndRollback` in `backend/tests/test_spec_ai_069.py`. Seeds a passing `SurgeBacktestResult`, 5 evaluations with `scannable_recall=0.5` (neutral — ensures Step 4's own adjustment stays at delta=0 so the observed min_score change is attributable solely to the EV guard), and 5 `ImprovementLog(action_type="failure_aggregation")` rows producing `mean_ev=-3.2 < floor=0.0` with `n_samples=25 >= min_samples=20`. Asserts `_write_auto_yaml` is called with `ensemble.min_score_for_signal == min(0.65, current + 0.02)`.

### Gap 2 (LOW, evaluator-active) — comment overstated the calibrator decision

`fund_manager.py:1382-1387` and `surge_calibrator.py:246-250` both said direction "(b) 명시적 해제" (explicit disconnect), but the actual implementation only surfaces the identity-fallback state — `calibrate_confidence()` is still called unconditionally, the connection was never severed. spec.md REQ-005's minimum bar (surface the invalid state, don't let it hide silently) was met, but the comment claimed more than was built.

Fix: reworded both comments to state "표면화만 구현(surfacing-only) — calibrate_confidence 연결 자체는 유지된다" (surfacing-only; the call site remains connected), removing the "명시적 해제" framing. Zero logic diff — comment-only change in both files.

### Re-verification

- `cd backend && uv run pytest tests/test_spec_ai_069.py tests/test_surge_auto_improver.py -v --tb=short` → **62 passed** (61 previous + 1 new).
- `uv run pytest tests/ --tb=short -q -m "not slow"` (full suite) → **1777 passed**, 1 pre-existing failure (`test_surge_detector.py::TestVolumeNewsCombo::test_characterize_low_zscore_no_candidate`, unrelated — evaluator-active independently reconfirmed via `git stash` reproduction that this fails identically without any SPEC-AI-069 changes applied), 4 skipped, 3 xpassed.
- `uv run ruff check .` (full backend) → all checks passed, zero warnings.
- Files touched in this closure round: `backend/tests/test_spec_ai_069.py` (+1 test), `backend/app/services/fund_manager.py` (comment only), `backend/app/services/surge_calibrator.py` (comment only). No production logic changed.

