# Implementation Plan: SPEC-AI-036

## Technical Approach

The work splits into four cohesive units, each mapping to a requirement cluster.
All new logic is exception-isolated so it cannot break the existing signal pipeline
(REQ-036-008).

### Unit 1 — surge composite_score / factor_scores 활성화 (REQ-036-001, 005, 007)

The surge path never assigns composite_score. Introduce a single helper that
converts a `SurgeCandidate`'s per-detector scores into a normalized
`(composite_score: float[0..1], factor_scores_json: str)` pair, then call it at
every surge_candidate creation site.

- Add `build_surge_factor_scores(candidate, config) -> tuple[str, float]` in
  `factor_scoring.py` (co-located with existing `build_factor_scores_json` for
  discoverability). It reuses `compute_ensemble_score(candidate, config)` as the
  composite_score source and emits the individual detector scores as `factor_scores`.
- The composite is clamped to 0.0~1.0. (LLM path keeps its 0~100 value; the two
  paths write the same column on different scales by design — REQ-036-007.)
- At each `FundSignal(... signal_type="surge_candidate" ...)` site in
  `surge_detector.py` (lines ~1638, 1752, 1881, 2028, 2238 and derived paths),
  set `signal.composite_score` and `signal.factor_scores` from the helper.
- Forward-only: no migration that rewrites historical rows (REQ-036-005). The
  columns already exist, so no schema change is required.

### Unit 2 — isotonic 캘리브레이터 (REQ-036-002, 006)

Create a new module `surge_calibrator.py` implementing isotonic regression via the
pure-Python Pool Adjacent Violators (PAV) algorithm (no numpy/sklearn dependency,
per research.md A3).

- `train_isotonic(pairs: list[tuple[float, int]]) -> IsotonicModel`: sorts by raw
  confidence, runs PAV on the 0/1 outcomes, produces a monotone step function.
- `IsotonicModel.predict(raw: float) -> float`: interpolates within fitted breakpoints.
- Persistence: pickle to a known path (e.g. `backend/data/surge_calibrator.pkl`)
  OR a small `surge_calibrator_state` DB table. Pickle is simpler for a single-VM
  bare-metal deploy; record `trained_at` and `sample_count` in metadata (REQ-036-006).
- Training data source: `signal_verifier`-verified surge_candidate signals from the
  last 90 days where `is_correct` is not NULL. Skip when samples <
  `min_calibration_samples` (default 50) or when positive ratio is 0%/100%.
- Weekly retraining: hook into the existing scheduler (the same place
  `verify_signals` / accuracy jobs run). Load the model at app startup; fall back
  to identity (raw) on load failure (REQ-036-002 IF clause).
- Apply in Unit 1's helper path: calibrate the surge raw confidence before storing.

### Unit 3 — 품질 floor 게이트 (REQ-036-003)

Add a floor check at surge_candidate emission that is layered on top of SPEC-AI-029.

- New config keys under the surge settings YAML / `SurgeDetectionConfig`:
  `min_calibrated_confidence` (default 0.35), `min_composite_score` (default 0.60),
  `min_calibration_samples` (default 50).
- Gate logic: emit the signal only if
  `calibrated_confidence >= min_calibrated_confidence OR composite_score >= min_composite_score`.
- This gate AND SPEC-AI-029's adaptive threshold both apply; the stricter wins.
  Do NOT modify `surge_threshold_service` — call it, then apply the floor.

### Unit 4 — signal-quality 엔드포인트 (REQ-036-004)

Add `GET /api/fund/signal-quality` to `routers/fund_manager.py`, backed by a new
service function (extend `signal_verifier.py` or a small `signal_quality.py`).

- Returns: confidence distribution (bucketed counts), composite_score fill rate,
  Brier score, ECE (Expected Calibration Error).
- Reports composite_score scale per `signal_type` (surge=0~1, llm=0~100) — never
  mixes the two (REQ-036-004, 007).
- Returns `insufficient_data` status (not an error) when verified samples are scarce.

## File Modification List

| File | Change | Why |
|------|--------|-----|
| `backend/app/services/factor_scoring.py` | ADD `build_surge_factor_scores()` | surge-specific composite/factor_scores (REQ-036-001) |
| `backend/app/services/surge_detector.py` | EDIT all surge_candidate creation sites to set composite_score + factor_scores + apply floor | REQ-036-001, 003, 005 |
| `backend/app/services/surge_calibrator.py` | NEW — PAV isotonic train/predict/persist | REQ-036-002, 006 |
| `backend/app/services/signal_verifier.py` | EDIT — expose calibrator training data; add Brier/ECE helpers | REQ-036-002, 004 |
| `backend/app/services/signal_quality.py` (or extend verifier) | NEW/EDIT — quality metrics aggregation | REQ-036-004 |
| `backend/app/routers/fund_manager.py` | ADD `GET /api/fund/signal-quality` | REQ-036-004 |
| surge settings YAML + `SurgeDetectionConfig` | ADD floor + calibration config keys | REQ-036-003 |
| scheduler/startup wiring | ADD weekly retrain + startup load | REQ-036-002 |
| `backend/tests/test_surge_detector.py` | EDIT — composite_score/floor assertions | test strategy |
| `backend/tests/test_surge_calibrator.py` | NEW — PAV/monotonicity/persistence tests | test strategy |

## Milestones (priority-ordered, no time estimates)

1. **M1 (High) — composite_score 활성화**: Unit 1. Lowest risk, immediate value
   (fixes the 0/428 NULL problem). Ship independently.
2. **M2 (High) — isotonic 캘리브레이터**: Unit 2. Depends on verified-signal data
   already produced by `verify_signals`.
3. **M3 (High) — 품질 floor 게이트**: Unit 3. Depends on M1 (composite_score) and
   M2 (calibrated confidence) being available.
4. **M4 (Medium) — signal-quality API**: Unit 4. Depends on M1+M2 for meaningful
   metrics; can ship last as a monitoring layer.

## Risks

- **R1 — composite_score 스케일 혼재**: surge(0~1) vs LLM(0~100) in one column.
  Mitigation: signal-quality endpoint reports per `signal_type`; never aggregate
  across scales (REQ-036-007). Aggregation queries elsewhere must filter by
  signal_type.
- **R2 — 신호 과소 생성**: A too-strict floor could drop daily signals below the
  5~10 target, starving the paper-trading executor. Mitigation: floor keys are
  YAML-tunable; validate against the 30-day distribution before enabling in prod.
- **R3 — 캘리브레이터 cold-start**: < 50 verified samples → no calibration.
  Mitigation: identity fallback (REQ-036-002), so behavior is never worse than today.
- **R4 — 의존성 footprint**: scikit-learn would pull numpy/scipy onto a Micro
  instance. Mitigation: pure-Python PAV (research.md A3).
- **R5 — 회귀 위험**: editing 5+ surge_candidate creation sites risks an
  inconsistent state. Mitigation: single shared helper (Unit 1) + exception
  isolation (REQ-036-008) + characterization tests on existing surge output.
- **R6 — 백워드 호환**: no schema change (columns exist), forward-only. Old rows
  keep NULL composite_score; queries must tolerate NULL.

## Backward Compatibility / Data Migration

- No Alembic schema migration needed — `composite_score` and `factor_scores`
  columns already exist on `fund_signals`.
- Forward-only population (REQ-036-005). Existing NULL rows remain NULL; the
  signal-quality endpoint reports fill-rate so the transition is observable.
- Calibrator artifact (`.pkl` or DB table) is additive; absence triggers identity
  fallback.
