# SPEC-AI-116 Acceptance Criteria

Status: implemented

### AC-116-001

Given SPEC-AI-112 attribution has insufficient eligible days, when detector selection runs, then
all detector families remain NO-GO for production emission.

Status: implemented. Covered by `TestAttributionSelection`.

### AC-116-002

Given contract/M&A evidence exists, when the contract/M&A detector runs in shadow, then it records
matched keyword, source reference, horizon, and candidate score without emitting `FundSignal`.

Status: implemented. Covered by `TestContractMnaShadowDetector`.

### AC-116-003

Given multiple stocks require volume-history inspection, when abnormal volume spike shadow runs,
then it uses batch history lookup and records volume ratio metadata.

Status: implemented. Covered by batch lookup test in `TestVolumeSpikeShadowDetector`.

### AC-116-004

Given missing price history for one stock, when volume spike scoring runs, then that stock is skipped
and the scan continues.

Status: implemented. Covered by missing-history branch in `TestVolumeSpikeShadowDetector`.

### AC-116-005

Given low-liquidity price movement evidence, when the low-liquidity detector runs, then output is
shadow-only and marked high-risk.

Status: implemented. Covered by `TestLowLiquidityShadowDetector`.

### AC-116-006

Given 10 eligible shadow evaluation days for a detector family, when readiness runs, then GO/NO-GO
is computed for that family without blending precision with other detector families.

Status: implemented. Covered by per-family readiness test in `TestReadinessReport`.

### AC-116-007

Given a same-day detector candidate, when evaluation output is generated, then it appears in the
same-day lane and not in standard T-1 predicted-set metrics.

Status: implemented. Readiness output now includes separate `same_day` / `next_day` shadow lanes
with `standard_t1_predicted_set_impact == 0`; covered by `TestReadinessReport`.
