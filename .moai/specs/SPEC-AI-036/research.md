# Research: SPEC-AI-036

Research conducted 2026-06-04 to ground requirements in the current codebase.
All file paths and line references reflect the repository state on that date.

## Core finding: two independent signal-generation paths

NewsHive has **two distinct FundSignal creation paths**, and only one of them
populates `composite_score` / `factor_scores`:

### Path A — LLM-based `generate_signal()` (in `fund_manager.py`)

- File: `backend/app/services/fund_manager.py`, around lines 2746-2767.
- DOES populate `composite_score` and `factor_scores` via
  `build_factor_scores_json(...)` (imported from `app.services.factor_scoring`).
- DOES apply `calibrate_confidence(signal.confidence, accuracy)` (Bayesian),
  but only when `accuracy["total"] >= 10`.
- This path produces `signal_type` values for the LLM-driven flow (buy/sell/hold),
  not the surge pipeline.

### Path B — surge detector (`surge_detector.py`) — THE PROBLEM

- File: `backend/app/services/surge_detector.py`.
- Every `FundSignal(... signal_type="surge_candidate" ...)` is constructed with
  ONLY `confidence`, `reasoning`, and `surge_metadata`. Confirmed at multiple
  creation sites: lines 1638, 1752, 1881, 2028, 2238 (plus `theme_propagation` at
  line 1372 and `volume_anomaly` in `_detect_volume_anomaly_internal`).
- NONE of these sites set `composite_score` or `factor_scores`.
- This is the direct cause of Issue 1 (composite_score is always NULL for
  surge_candidate rows): the surge path simply never assigns it.

Conclusion: composite_score activation for surge signals is NOT a matter of
"re-enabling dead code." The surge path has no composite_score assignment at all.
It must be ADDED, sourcing inputs from the per-detector scores already present on
the `SurgeCandidate` object.

## Existing building blocks to reuse (do NOT reinvent)

### `compute_ensemble_score(candidate, config)` — already a normalized surge score

- File: `surge_detector.py` line 947, called at 1168, 1223, 1237.
- Produces a normalized surge probability (0.0~1.0 range) from the per-detector
  scores. Already stored into `surge_metadata.surge_probability_score` via
  `surge_candidate_to_signal_metadata()` (line 1232) but NOT into `composite_score`.
- The detector grouping is news(theme_cluster + volume_news_combo) / disclosure /
  technical; `validate_ensemble_weights` requires the 4 detector weights to sum to 1.0.

### Per-candidate factor scores available on `SurgeCandidate`

`surge_candidate_to_signal_metadata()` (lines 1232-1247) already exposes:
`theme_cluster_score`, `combo_score`, `pattern_score`,
`immediate_disclosure_score`, `legacy_score`, plus `disclosure_sentiment`
(SPEC-AI-028). These are the natural inputs for a surge-specific
`factor_scores` JSON and a surge `composite_score`.

### `compute_composite_score(factor_scores, weights)` — exists, but 0-100 scale

- File: `backend/app/services/factor_scoring.py` line 316.
- Returns a **0.0~100.0** weighted sum (NOT 0-1). The LLM path uses it.
- IMPORTANT SCALE MISMATCH: the problem statement's REQ-036-003 references
  `composite_score >= 0.60`. The existing `composite_score` column stores a
  0-100 value in the LLM path. The SPEC MUST resolve this: either normalize the
  surge composite to 0.0~1.0 (recommended for a probability-like score), or use
  a 0-100 threshold (>= 60). See REQ-036-001 decision note.

### `calibrate_confidence(raw_confidence, accuracy_stats)` — Bayesian, not isotonic

- File: `signal_verifier.py` line 485.
- Current calibration is a **Bayesian blend** keyed on coarse confidence buckets
  (high >= 0.7, medium >= 0.55, low otherwise), clamped to [0.1, 0.95].
- Gated by `_MIN_CALIBRATION_SAMPLES` and `accuracy_stats.total`.
- This is NOT isotonic regression. REQ-036-002 introduces a NEW isotonic
  calibrator. The Bayesian function may remain for the LLM path or be superseded;
  the SPEC scopes isotonic calibration to the surge_candidate path to avoid
  destabilizing the LLM path.

### Verification path (`signal_verifier.py`)

- `verify_signals(db)` (line 152) records `is_correct`, `return_pct`,
  `alpha_pct`, `verified_at` after 5 trading days.
- `is_correct` is judged on `alpha_pct` sign (benchmark-adjusted), falling back to
  raw `price_change` when alpha is unavailable (lines 261-268).
- The accuracy summary already buckets by confidence (lines 440-458) producing
  `by_confidence` with per-bucket accuracy — directly reusable for calibrator
  training data and for the signal-quality endpoint.

## Data-availability constraints (carried from prior surge SPECs)

- The sync price helper `_fetch_price_change_sync(stock_code)` returns only
  `{"current_price": int, "change_rate": float}` — NO `open_price` (시가).
  `change_rate` is previous-close %, not from-open intraday.
- `_get_volume_history` returns daily (일봉) bars only — no intraday volume.
- These do NOT block SPEC-AI-036 (it operates on already-computed detector scores,
  not on fresh price fetches), but they are noted so requirements do not
  accidentally assume intraday data.

## Dependency constraint: no numpy / scikit-learn in the backend

- `backend/pyproject.toml` does NOT list `numpy`, `scipy`, `pandas`, or
  `scikit-learn`. Grep across the backend found no such dependency.
- Consequence for REQ-036-002: isotonic regression CANNOT assume
  `sklearn.isotonic.IsotonicRegression`. The implementation must either:
  (a) add `scikit-learn` (heavy; pulls numpy/scipy) as a new dependency, or
  (b) implement the Pool Adjacent Violators (PAV) algorithm in pure Python
      (lightweight, ~40 LOC, no new dependency).
- Recommendation captured in plan.md: prefer pure-Python PAV to keep the
  deploy footprint small (bare-metal OCI Micro instance, see project memory).

## API surface

- Router prefix is `/api/fund` (`backend/app/routers/fund_manager.py` line 41).
- So REQ-036-004's `GET /api/fund/signal-quality` is consistent with existing
  endpoints (`/signals`, `/accuracy`, `/verify`, `/backtest-stats`, `/model-health`).
- SPEC-AI-029 added `GET /api/surge-trading/threshold-status` (a different router).

## Related SPEC boundaries (avoid duplication)

- SPEC-AI-029 owns the **adaptive** threshold (`SurgeThresholdHistory`,
  `surge_threshold_service.get_effective_threshold` built on
  `ensemble.min_score_for_signal`, and `combo_zero_theme_floor`). REQ-036-003 must
  layer a **floor** ON TOP of AI-029's adaptive value, never replace it.
- SPEC-AI-030 owns the volume_news_combo chase-buy gates (`ComboChaseGuardConfig`).
- SPEC-AI-006 owns dynamic factor weights for the LLM path's
  `build_factor_scores_json`.
- SPEC-AI-036 introduces NEW concerns: (1) surge-path composite_score/factor_scores
  population, (2) isotonic confidence calibration for surge signals,
  (3) a quality-floor gate, (4) a signal-quality monitoring endpoint.

## Open decisions resolved in the SPEC

1. composite_score scale → store surge composite on **0.0~1.0** scale to match a
   probability interpretation and the REQ-036-003 `>= 0.60` threshold. Document the
   divergence from the LLM path's 0-100 value in REQ-036-001 (the two paths write
   the same column on different scales; the signal-quality endpoint must report
   scale per `signal_type` to avoid mixing).
2. Calibrator scope → isotonic calibrator applies to **surge_candidate** signals
   only; the LLM path keeps Bayesian `calibrate_confidence`.
3. Backfill → forward-only. No historical rewrite of `composite_score`.
