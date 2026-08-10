# SPEC-AI-111 Acceptance Criteria

Status: implemented-no-go
Created: 2026-08-07

## AC-111-001 - Flag-Off Candidate Set Is Unchanged

Given `scan_universe_bridge_candidates_enabled=false`, when `gather_surge_candidates()` runs with fixtures that include Pool A and Pool C scan universe members, then the final qualified stock-code set shall match the current flag-off result exactly.

Verification: unit test.

## AC-111-002 - Readiness Gate Blocks Insufficient Shadow Data

Given fewer than 10 eligible trading days with bridge shadow observations and actual outcomes, when `evaluate_bridge_activation_readiness()` runs for `pool_a`, then it shall return `ready=false` and `reason="insufficient_shadow_days"`.

Verification: unit test.

## AC-111-003 - Readiness Gate Passes Pool A Only On Separate Precision

Given at least 10 eligible trading days where aggregate Pool A shadow precision is at least `max(0.05, baseline_precision)` and there is no five-day zero-precision streak, when the readiness helper runs, then it shall return `ready=true` for `pool_a`.

Pool C precision shall be present in the diagnostic rows if available, but Pool C shall not be blended into Pool A's pass condition.

Verification: unit test.

## AC-111-004 - Readiness Gate Fails Low Pool A Precision

Given at least 10 eligible trading days where Pool C precision is high but Pool A precision is below `max(0.05, baseline_precision)`, when the readiness helper runs, then it shall return `ready=false` for `pool_a`.

Verification: unit test.

## AC-111-005 - Pool A-Only Canary Emits Only Pool A

Given bridge activation config:

```python
{
    "scan_universe_bridge_candidates_enabled": True,
    "scan_universe_bridge_pool_b_enabled": False,
    "scan_universe_bridge_max_candidates": 5,
    "scan_universe_bridge_pool_limits": {"pool_a": 5, "pool_b": 0, "pool_c": 0},
}
```

when Pool A and Pool C candidates both score above `_BRIDGE_MIN_SCORE`, then final bridge output shall contain at most five Pool A candidates and zero Pool C candidates.

Verification: unit test.

## AC-111-005A - GO Config Values Are Exact

Given the readiness gate returns `ready=true`, when production config is changed, then `surge_detection.yaml` shall contain exactly the Pool A-only bridge values required by REQ-AI111-004:

- `scan_universe_bridge_candidates_enabled: true`;
- `scan_universe_bridge_pool_b_enabled: false`;
- `scan_universe_bridge_max_candidates: 5`;
- `scan_universe_bridge_pool_limits.pool_a: 5`;
- `scan_universe_bridge_pool_limits.pool_b: 0`;
- `scan_universe_bridge_pool_limits.pool_c: 0`;
- `scan_universe_bridge_shadow_enabled: true`.

Verification: document/config check plus `progress.md` GO evidence.

## AC-111-006 - Pool A Attribution Is Preserved

Given a Pool A bridge candidate enters final qualified predictions, then the candidate shall contain:

- `entry_pool == "pool_a"`;
- `bridge_score is not None`;
- `bypass_composite_score == bridge_score`;
- `active_detectors` containing `scan_universe_bridge` and `pool_a`;
- downstream signal metadata preserving `scan_universe_bridge` in `surge_basis` or equivalent metadata.

Verification: unit or service integration test.

## AC-111-007 - Pool B Is Disabled And Does Not Fetch

Given Pool B members exist in the scan universe and `scan_universe_bridge_pool_b_enabled=false`, when the Pool A canary config is active, then no Pool B bridge candidate shall be emitted and `fetch_stock_price_history_batch_sync()` shall not be called.

Verification: unit test with patched fetch function.

## AC-111-007A - Missing Baseline Precision Blocks GO

Given 10 or more days have bridge shadow observations and actual outcomes, but fewer than 10 matching `SurgePredictionEvaluation` rows have non-null `precision`, when `evaluate_bridge_activation_readiness()` runs for `pool_a`, then it shall return `ready=false` and `reason="insufficient_baseline_days"`.

Verification: unit test.

## AC-111-008 - Pool D Remains Measurement-Only

Given Pool D members exist in scan universe membership and `pool_d_min_slots=10`, when the Pool A canary config is active, then Pool D shall not enter bridge output and shall not appear in emitted `FundSignal` rows as `scan_universe_bridge`.

Verification: unit or service integration test.

## AC-111-009 - Pool C Zero Limit Blocks Otherwise Valid Pool C

Given a Pool C member has a prior-day move high enough to pass bridge scoring, when `scan_universe_bridge_pool_limits.pool_c=0`, then it shall not enter bridge output.

Verification: unit test.

## AC-111-010 - Evaluation Metrics Stay Split

Given Pool A bridge predictions exist, when the surge evaluation endpoints return summary/detail data, then market recall and scannable recall fields introduced by SPEC-AI-110 shall remain present and distinct.

Verification: focused endpoint tests.

## AC-111-010A - Bridge Candidate Counts Are Observable

Given at least one Pool A bridge candidate is produced, when `generate_scan_universe_bridge_candidates()` returns, then logs or structured diagnostics shall expose total bridge candidate count and Pool A bridge candidate count.

Verification: unit test with log capture or structured result assertion.

## AC-111-011 - No-Go Is Recorded Without Config Flip

Given the readiness gate returns no-go, when the implementation completes, then `progress.md` shall record the no-go reason and `surge_detection.yaml` shall not enable `scan_universe_bridge_candidates_enabled`.

Verification: document check plus `rg` config check.

## AC-111-011A - GO Is Recorded With Exact Evidence

Given the readiness gate returns GO and config is flipped, when implementation completes, then `progress.md` shall record GO status, exact YAML values, eligible baseline day count, Pool A aggregate precision, baseline precision, zero-precision streak, and rollback line.

Verification: document check.

## AC-111-012 - Rollback Is Config-Only

Given the canary was enabled, when rollback is required, then setting `scan_universe_bridge_candidates_enabled=false` or removing the key shall stop real bridge candidate emission without schema changes or shadow row deletion.

Verification: flag-off unit test and documented rollback evidence.
