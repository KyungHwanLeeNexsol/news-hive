---
id: SPEC-AI-111
title: "Scan Universe Bridge Pool A Limited Activation"
version: "0.1.0"
status: implemented
created: 2026-08-07
updated: 2026-08-10
author: Nexsol
priority: High
phase: "backend surge-detection v0.1.0"
module: "backend/app/services"
lifecycle: spec-anchored
tags: "surge-detection, scan-universe, bridge-candidates, pool-a, no-go"
tier: M
depends_on: [SPEC-AI-105, SPEC-AI-109, SPEC-AI-110]
related_specs: [SPEC-AI-102, SPEC-AI-113]
---

# SPEC-AI-111 - Scan Universe Bridge Pool A Limited Activation

Status: implemented-no-go
Created: 2026-08-07
Priority: next

## 1. Summary

Enable the already implemented scan universe bridge through a narrow Pool A canary, only after a read-only readiness gate confirms enough shadow data and acceptable Pool A precision.

The initial real bridge activation must be Pool A-only:

```yaml
scan_universe_bridge_candidates_enabled: true
scan_universe_bridge_pool_b_enabled: false
scan_universe_bridge_max_candidates: 5
scan_universe_bridge_pool_limits:
  pool_a: 5
  pool_b: 0
  pool_c: 0
scan_universe_bridge_shadow_enabled: true
```

If readiness data is insufficient or fails the precision guardrail, implementation must leave `scan_universe_bridge_candidates_enabled` unset/false and record a no-go result in `progress.md`.

## 2. Motivation

The current surge prediction issue is not only an evaluation problem. SPEC-AI-109 and SPEC-AI-110 make the measurements trustworthy enough to act on. The next smallest product lever is to activate part of the bridge code that already exists but is disabled.

Pool A is the safest first target because it uses already stored disclosure data and showed meaningful pure missed coverage in the 2026-07-03 to 2026-07-27 production gap report. Pool C and Pool B are intentionally held back: Pool C is weakly filtered, and Pool B adds price-history fetch cost.

## 3. Scope

### In Scope

- Add a read-only Pool A bridge activation readiness gate.
- Use `surge_bridge_shadow_candidates`, `SurgeActualOutcome`, and `SurgePredictionEvaluation` as inputs.
- Keep Pool A and Pool C precision decisions separate.
- Enable Pool A-only bridge canary only if the readiness gate passes.
- Ensure Pool C remains blocked by `scan_universe_bridge_pool_limits.pool_c: 0`.
- Ensure Pool B remains disabled and performs no price-history bridge fetch.
- Ensure Pool D remains measurement-only and cannot enter bridge output.
- Add focused regression tests around activation limits, exclusion rules, and metric compatibility.

### Out Of Scope

- New bridge scoring formulas.
- Pool B real activation.
- Pool C real activation.
- Pool D bridge scoring or trading path.
- Ensemble threshold retuning.
- Evaluation formula changes.

## 4. Requirements

### REQ-AI111-001 - Flag-Off No-Regression

While `scan_universe_bridge_candidates_enabled` is false or absent, the system shall produce the same final qualified candidate stock-code set as the current implementation.

### REQ-AI111-002 - Pool A Readiness Gate

When the Pool A bridge activation preflight runs, the system shall evaluate at least the latest 10 trading days that have both bridge shadow observations and actual surge outcomes.

The preflight shall return a no-go result when fewer than 10 eligible trading days exist.

An eligible trading day shall have:

- Pool A bridge shadow observations for that date;
- actual surge outcomes for that date;
- a `SurgePredictionEvaluation` row for that date with non-null `precision`.

If fewer than 10 eligible baseline rows exist, the preflight shall return no-go rather than treating missing baseline precision as zero.

### REQ-AI111-003 - Precision Guardrail

When the readiness gate has enough data, the system shall compare Pool A shadow precision against the same-period `SurgePredictionEvaluation.precision` baseline.

The default pass condition shall be:

- aggregate Pool A shadow precision is at least `max(0.05, baseline_precision)`;
- Pool A does not have five consecutive eligible trading days with `0.0` precision;
- aggregate Pool A shadow candidate count is greater than zero.

Pool C precision shall be calculated and reported separately, but it shall not be allowed to help Pool A pass.

### REQ-AI111-004 - Pool A-Only Canary Config

If REQ-AI111-002 and REQ-AI111-003 pass, the activation config shall set:

- `scan_universe_bridge_candidates_enabled: true`;
- `scan_universe_bridge_pool_b_enabled: false`;
- `scan_universe_bridge_max_candidates: 5`;
- `scan_universe_bridge_pool_limits.pool_a: 5`;
- `scan_universe_bridge_pool_limits.pool_b: 0`;
- `scan_universe_bridge_pool_limits.pool_c: 0`;
- `scan_universe_bridge_shadow_enabled: true`.

### REQ-AI111-005 - Pool C Block

While the first canary is active, Pool C bridge candidates shall not enter final qualified predictions even if Pool C shadow precision exists.

The blocker shall use the existing pool-limit mechanism rather than adding a new target-pool flag.

### REQ-AI111-006 - Pool B Block And No Fetch

While this SPEC is active, Pool B bridge candidates shall not enter final qualified predictions.

The implementation shall keep `scan_universe_bridge_pool_b_enabled` false and tests shall prove that the Pool B bridge path does not call `fetch_stock_price_history_batch_sync()`.

### REQ-AI111-007 - Pool D Measurement-Only

While this SPEC is active, Pool D shall remain excluded from bridge output and `FundSignal` emission. `pool_d_min_slots: 10` may remain for measurement, but Pool D membership shall not become a prediction source.

### REQ-AI111-008 - Observability

When the real bridge produces candidates, logs and downstream metadata shall preserve enough attribution to identify:

- bridge candidate count;
- Pool A bridge candidate count;
- `active_detectors` containing `scan_universe_bridge` and `pool_a`;
- `surge_basis` or equivalent metadata preserving `scan_universe_bridge`.

### REQ-AI111-009 - Rollback

The rollback path shall be a single config change: set `scan_universe_bridge_candidates_enabled` to false or remove it from YAML.

Operational rollback triggers:

- Pool A bridge precision falls below the readiness threshold after activation;
- Pool A bridge precision is `0.0` for five consecutive eligible trading days;
- total prediction count exceeds 3x the previous 14-day average;
- any Pool B bridge price-history fetch occurs while Pool B is disabled;
- scheduler runtime materially regresses.

### REQ-AI111-010 - Metric Compatibility

The evaluation API and stored evaluation rows shall continue exposing market-level and scannable-level metrics introduced by SPEC-AI-110. Adding Pool A bridge candidates shall not collapse these metrics back into a single recall number.

### REQ-AI111-011 - GO Evidence

If the readiness gate returns GO and production config is changed, `progress.md` shall record:

- GO status;
- exact YAML values applied;
- eligible baseline day count;
- Pool A aggregate shadow precision;
- same-period baseline precision;
- rollback config line.

If the readiness gate returns NO-GO, `progress.md` shall record the no-go reason and shall state that `scan_universe_bridge_candidates_enabled` remains false or absent.

## 5. Decisions

### D1 - Activate Pool A First

Pool A is selected because it uses already stored disclosure data, has pure missed coverage, and does not add Pool B-style external fetch cost.

### D2 - Keep Pool C Shadow-Only

Pool C must remain at limit `0` for the first canary. Its precision is measured separately because blended A/C precision can hide Pool C noise.

### D3 - Keep Pool B Disabled

Pool B is excluded because the bridge implementation can fetch price history for Pool B scoring. That is too much operational surface for the first activation.

### D4 - Keep Pool D Out Of Bridge

Pool D addresses absent-type misses better in theory, but the current bridge generator does not target Pool D. This SPEC must not add a Pool D bridge path.

### D5 - No-Go Is A Valid Delivery Outcome

If the actual database lacks enough shadow observations, the implementation should deliver the readiness gate and tests, leave production bridge disabled, and record the no-go reason.

## 6. Delivery State

Run phase completed with NO-GO for production activation. The readiness gate and
tests exist, but production-grade readiness could not be evaluated from the
workspace DB setting, so `scan_universe_bridge_candidates_enabled` remains
unset/false.

Follow-up: SPEC-AI-113 owns the production readiness rerun, Pool A-only canary
decision, and rollback monitor.
