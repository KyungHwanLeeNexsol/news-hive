# SPEC-AI-111 Research - Scan Universe Bridge Pool A Canary Activation

Status: implemented-no-go
Created: 2026-08-07
Workflow: moai plan

## 1. Problem

Recent surge prediction work fixed evaluation visibility first:

- SPEC-AI-109 repaired missing/partial evaluation rows so recall and precision are not silently underreported.
- SPEC-AI-110 separated market recall from scannable recall so low recall is no longer flattened into one ambiguous number.

After those fixes, the remaining product problem is not just "metrics are wrong". The system still misses too many actual surge stocks because a large portion of actual surges never becomes a candidate signal, and part of the scan universe bridge that could convert known pool members into candidates is implemented but not active.

## 2. Evidence

### 2.1 Universe gap report

`.moai/reports/surge-universe-gap/2026-07-27.md` measured 15 production trading days from 2026-07-03 to 2026-07-27.

- Actual surges: 885.
- Actual surges with no signal: 751, or 84.9%.
- Among no-signal actual surges, 624, or 83.1%, were absent from all T-1 scan universe pools.
- The maximum theoretically recoverable share from existing pool A/B/C bridge wiring is 16.9% of no-signal misses.
- Pool A contributed 43 no-signal misses, or 5.7% of no-signal misses.
- Pool A raw members overlapped existing disclosure signals only 36.7% of the time; 63.3% were pure missed candidates.
- Pool B contributed only 3.6% of no-signal misses and needs a price-history fetch path when bridged.
- Pool C contributed 7.6% of no-signal misses, but its score is weakly filtered because a 5% prior-day move already clears the bridge minimum score.

This makes Pool A the most conservative first activation target. It is not a full recall solution, but it is the existing lever with meaningful incremental signal and no Pool B-style network cost.

### 2.2 Existing bridge implementation

`backend/app/services/surge_detector.py` already calls `generate_scan_universe_bridge_candidates()` from `gather_surge_candidates()` after scan universe construction and before final qualified sorting.

Key implementation facts:

- `generate_scan_universe_bridge_candidates()` returns an empty list unless `scan_universe_bridge_candidates_enabled` is true.
- By default, bridge targets Pool A and Pool C only.
- Pool B enters only when both the master switch and `scan_universe_bridge_pool_b_enabled` are true.
- Pool D is not part of the bridge target pool set.
- Pool limits are already supported through `scan_universe_bridge_pool_limits`.
- A pool limit of `0` prevents that pool from entering final bridge output.
- Returned bridge candidates are tagged with `active_detectors=["scan_universe_bridge", pool]`.
- Bridge candidates get `bridge_score` and `bypass_composite_score`, then append to `qualified` without mutating `merged`.

### 2.3 Current configuration state

`backend/app/surge_config/surge_detection.yaml` currently has:

- `max_scan_universe: 250`
- `pool_b_min_slots: 20`
- `pool_c_min_slots: 30`
- `pool_d_min_slots: 10`
- `universe_gap_measurement_enabled: true`
- `scan_universe_bridge_shadow_enabled: true`

The same YAML does not set `scan_universe_bridge_candidates_enabled`, so `backend/app/surge_config/surge_settings.py` default `False` still keeps the real bridge inactive.

### 2.4 Existing shadow gate

SPEC-AI-105 added shadow persistence and analysis:

- `backend/app/services/surge_bridge_shadow_service.py` persists shadow candidates to `surge_bridge_shadow_candidates` with date-level replace semantics.
- `backend/app/services/surge_universe_gap_service.py` exposes `analyze_bridge_shadow_precision_by_date()`.
- Shadow precision is returned separately for Pool A and Pool C.
- Pool B is hard excluded from shadow measurement.
- Shadow never changes `qualified` candidates because it only calls the bridge generator with a copied config.

This is enough to define an activation gate without inventing a new scoring path.

## 3. Root Causes Of Low Surge Prediction Power

1. Most actual surges are outside the active candidate surface. The 15-day production sample shows 83.1% of no-signal actual surges were absent from T-1 pool A/B/C membership.
2. Existing scan universe members are not always promoted into predictions. Pool A has meaningful pure missed coverage, but the real bridge master switch is still off.
3. Pool C may inflate candidate count with weak filtering. Its bridge score is based on prior-day move normalization, so it must not be blended with Pool A precision.
4. Pool B needs external price-history fetches on the bridge path. It is higher operational risk for a first activation.
5. Pool D is measurement-only. It may become a better source for absent misses, but there is no Pool D bridge scoring path yet.

## 4. Selected Next Priority

Create an activation SPEC for a Pool A-only bridge canary.

The canary should:

- keep Pool B disabled;
- keep Pool D measurement-only;
- keep Pool C at limit `0` during the first activation;
- keep shadow measurement on;
- require a read-only readiness gate before any production config flip;
- record a no-go result if shadow observations are insufficient.

## 5. Non-Goals

- No new model, ensemble weight, or detector score formula.
- No Pool B activation.
- No Pool D bridge output.
- No change to evaluation metric formulas created by SPEC-AI-109 and SPEC-AI-110.
- No broad scan universe expansion beyond the already configured `max_scan_universe: 250`.
