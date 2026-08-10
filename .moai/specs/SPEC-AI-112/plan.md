# SPEC-AI-112 Plan

Status: implemented
Created: 2026-08-10

## Milestones

1. [x] Inspect current evaluation restore helpers, `SurgeUniverseMember`, news/disclosure models, and any existing miss-attribution scripts.
2. [x] Implement an absent miss attribution service with the same predicted-set semantics as `evaluate_surge_predictions()`.
3. [x] Add reason-bucket classification with deterministic precedence and compact evidence payloads.
4. [x] Add a range report path through either `scripts/` or an admin-only API.
5. [x] Add tests proving no `FundSignal` emission or qualified candidate mutation.

## Preserve List

- `evaluate_surge_predictions()` TP/FP/FN semantics.
- `scan_universe_bridge_candidates_enabled` default and YAML value.
- Existing detector scoring, bypass, and gate logic.
- Trading execution path.

## Open Questions

1. Resolved: first delivery is script-only to avoid adding admin auth/API surface before the attribution contract stabilizes.
2. Resolved: first delivery is deterministic generation from existing tables to avoid migration risk. Persistence can be reconsidered after SPEC-AI-113/114 source-pool metrics prove repeated operator demand.

## Completion Signal

Run phase is complete when the report shows a reason-bucket breakdown for at least one evaluated
trading day and no behavior-change tests pass. Local verification used in-memory evaluation rows
because the default local PostgreSQL endpoint was not running during implementation.
