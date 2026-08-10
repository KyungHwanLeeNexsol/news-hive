# SPEC-AI-114 Plan

Status: implemented
Created: 2026-08-10

## Milestones

1. [x] Inspect current same-day exclusion helpers and prediction-history serializers.
2. [x] Define lane DTO shape for evaluation list/detail/history.
3. [x] Implement same-day metric computation from existing `FundSignal` and `SurgeActualOutcome` data.
4. [x] Add mixed-lane regression tests proving T-1 metrics are unchanged.
5. [x] Update API documentation/changelog in sync phase.

## Preserve List

- `_is_same_day_event_horizon_signal()` exclusion behavior.
- `_is_near_limit_up_carry_signal()` exclusion behavior.
- SPEC-AI-110 market/scannable metric fields.
- Existing `SurgePredictionEvaluation` stored T-1 counts.

## Open Questions

1. Resolved: lane metrics are computed for API/report responses only to avoid migration risk.
2. Resolved: same-day actual coverage denominator is all actual surge codes on the same trading date. The denominator is exposed as `same_trading_date_actual_surge_count`.

## Completion Signal

Run phase is complete when API/report output separates `next_day` and `same_day` metrics and regression tests prove standard T-1 TP/FP/FN values do not change.
