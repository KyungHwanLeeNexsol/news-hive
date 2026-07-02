## SPEC-AI-068 Progress

- Started: 2026-07-02
- Phase 0.9: Python (backend/pyproject.toml) detected → moai-lang-python
- Phase 0.95: 6 files, single domain (backend) → Standard Mode (manager-strategy + expert-backend + manager-quality)
- Harness level: standard (file_count > 3, single domain, priority=High not critical)
- Development mode: ddd (quality.yaml)

### DDD Cycle Execution Log (manager-ddd, 2026-07-02)

**ANALYZE**
- Confirmed migration head: `065_surge_universe_members` is the sole alembic head (`alembic heads` → 1 head), `down_revision=064_surge_universe_pool_history` correct.
- Confirmed hook location: `surge_detector.py:1918` `persist_pool_counts` try-block inside `gather_surge_candidates`, `_universe_codes`/`_entry_pool_map` already in scope. `build_scan_universe` (line 3960) signature confirmed, untouched.
- Confirmed `evaluate_surge_predictions` (surge_evaluation_service.py:482-620) exact baseline logic — became PRESERVE characterization target.
- Confirmed `conftest.py` requires explicit model import for `Base.metadata.create_all` (SQLite tests) — added `SurgeUniverseMember` import (necessary test infra, not scope creep).
- Confirmed downstream `.recall` consumers (`surge_auto_improver.py`) already defensively handle `None`/`or 0.0` — safe for the new nullable-recall semantics; did not touch that file (SPEC-AI-069 territory).

**PRESERVE (T-004, before rewrite)**
- Added `TestEvaluateSurgePredictionsCharacterization` (10 tests) to `test_surge_evaluation_service.py`, locking in: predicted_count, actual_surge_count (market-wide), TP/FP, precision zero-denom, pool_counts passthrough (insert + preserved-on-update-when-None), upsert idempotency (same evaluation_date PK), `db.commit()` invocation.
- All 18 tests (8 pre-existing + 10 new characterization) GREEN on baseline code before any rewrite — safety net confirmed before touching `evaluate_surge_predictions`.

**IMPROVE**
- T-001: Implemented `SurgeUniverseMember` model (composite PK `trading_date, stock_code`), migration `065_surge_universe_members.py` (table + index + 4 columns on `SurgePredictionEvaluation` + 1 column on `SurgeActualOutcome`), registered in `models/__init__.py`, registered in `conftest.py` for SQLite `create_all`.
- T-002: Implemented `persist_universe_members` (daily replace: DELETE-then-insert, dedupes codes, defaults unmapped codes to `existing`) and `get_universe_members_for_date` in `surge_universe_pool_service.py`. 8 new tests in `test_surge_universe_members.py`, all green (includes EC-5 stale-code-removal on same-date rerun).
- T-003: Added `persist_universe_members` call inside the existing `persist_pool_counts` try-block at `surge_detector.py:1918` (same transaction, same fail-open except). Diff confirmed scoped to exactly this block via `git diff` — `build_scan_universe` untouched (0 lines changed).
- T-004: See PRESERVE above.
- T-005: Rewrote `evaluate_surge_predictions` — kept TP/FP/FN/precision/legacy-recall computation on market-wide `actual_set` unchanged (byte-for-byte formula preserved as `legacy_recall`); removed the false-premise comment at old `:531-535`; added T-1 universe lookup via `get_universe_members_for_date`, computed `scannable_actual = actual_set ∩ universe_set`, `scannable_recall` (null if `scannable_actual_count==0`), `coverage` (null if `total_actual_count==0`); `recall` column now transitions to `scannable_recall` when universe exists, else retains `legacy_recall` (per user-confirmed decision). New metrics computation wrapped in try/except with `db.rollback()` fail-open (does not crash the eval job). All 18 PRESERVE tests remained GREEN after rewrite (zero changes needed) — behavior preservation confirmed. Added `TestScannableRecallAndCoverage` (5 tests) covering acceptance.md Scenario 1 hand-calculation, EC-1, EC-2, EC-3, and false_negative market-wide invariance.
- T-006: Added `SurgeActualOutcome.surge_type` labeling (`scannable`/`non_scannable` by `stock_code in universe_set`) as a separate step AFTER the core evaluation commit, isolated in its own try/except+rollback (AI-061 B01/B02 pattern — labeling failure never touches already-committed precision/recall/scannable_recall/coverage). Added `TestSurgeTypeLabeling` (4 tests) covering acceptance.md Scenario 3 and fail-open behavior.
- T-007: See Verification below.

**Verification (T-007)**
- Full suite: `uv run pytest tests/ --tb=short -q -m "not slow"` → **1737 passed, 4 skipped, 3 xpassed, 1 failed**. The 1 failure (`test_surge_detector.py::TestVolumeNewsCombo::test_characterize_low_zscore_no_candidate`) reproduces identically on baseline `main` (verified via `git stash` + isolated re-run) — pre-existing, unrelated to this SPEC.
- `ruff check` on all modified/new files: all checks passed.
- `mypy`: not installed in this project's dependency set (only `ruff` is listed in `pyproject.toml`; `python -m mypy` → `ModuleNotFoundError`). Pre-existing tooling gap, not introduced by this SPEC — not fixed here (out of scope, would require adding a new dependency).
- Coverage (new/changed files only): `surge_universe_member.py` 100%, `surge_prediction_evaluation.py` 100%, `surge_actual_outcome.py` 100%, `surge_universe_pool_service.py` 100%, `surge_evaluation_service.py` 82% (aggregate 86% across the 5 files; remaining misses in `surge_evaluation_service.py` are pre-existing LLM-analysis helper code untouched by this SPEC, plus 2 defensive nested `except: pass` lines). `surge_detector.py` hook lines (1912-1946, including the new `persist_universe_members` call) confirmed covered via `test_surge_universe_pool_bugfix.py`/`test_surge_detector.py`.
- Buy/portfolio diff 0: `git status --short` shows zero matches for buy/portfolio/trading/order/position-related files — confirmed prediction-record-only mode (SPEC-AI-043) is unaffected.
- Scenario 1 hand-calculation cross-check (acceptance.md): T-1 universe={A,B,C,D}, actual={A,B,X,Y,Z}, predicted={A} → `scannable_actual_count=2, total_actual_count=5, scannable_recall=0.5, coverage=0.4, true_positive=1, false_positive=0, false_negative=4, precision=1.0, recall(transitioned)=0.5` — all asserted exactly in `test_scenario1_scannable_recall_and_coverage_hand_calculated`, GREEN.
- Alembic: `uv run alembic heads` → `065_surge_universe_members (head)`, single head confirmed, no branch conflicts.
