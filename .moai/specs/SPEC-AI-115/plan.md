# SPEC-AI-115 Plan

Status: implemented
Created: 2026-08-10

## Milestones

1. [x] Map every major candidate removal stage in `surge_detector.py` and `surge_evaluation_service.py`.
2. [x] Add a lightweight drop observation model or deterministic log/report path.
3. [x] Add official-output preservation tests.
4. [x] Implement one bounded shadow relaxed-gate profile.
5. [x] Add range report ranking recall gain versus added false positives.

## Preserve List

- Official `FundSignal` emission.
- Official evaluation TP/FP/FN formulas.
- SPEC-AI-113 bridge activation flags.
- Trading execution path.

## Open Questions

1. Resolved: persist observations in DB append table `surge_gate_drop_observations`.
2. Resolved: first shadow profile is lower regime threshold by 0.05
   (`regime_threshold_minus_0_05`).

## Completion Signal

Run phase is complete when drop reasons are visible for major gates, official candidate output is proven unchanged, and a shadow report can rank at least one relaxed profile over eligible evaluated days.

Completed in v0.1.1 with unit coverage for all required gates, fail-open behavior,
official-output preservation, and report guardrails.
