# SPEC-AI-116 Plan

Status: implemented
Created: 2026-08-10

## Milestones

1. [x] Consume SPEC-AI-112 attribution output and identify top trigger bucket over recent eligible days.
2. [x] Implement shadow detector skeletons with independent config flags.
3. [x] Add detector-specific evidence metadata and horizon tags.
4. [x] Add shadow precision report per detector family.
5. [x] Add production enablement guard that returns GO/NO-GO per detector.
6. [x] Add shadow lane reporting so same-day detector candidates do not contaminate standard T-1 metrics.

## Preserve List

- Existing detector scores and thresholds.
- SPEC-AI-114 lane separation.
- SPEC-AI-115 drop attribution.
- Trading execution path.

## Open Questions

1. Resolved: first contract/M&A dictionary reuses SPEC-AI-112 `CONTRACT_MNA_KEYWORDS`.
2. Resolved: first shadow defaults are volume ratio `3.0`, baseline window `20`, low-liquidity market cap `1000` eok, and low-liquidity price move `5.0%`.
3. Resolved: low-liquidity candidates remain shadow-only high-risk annotations in this SPEC.

## Completion Signal

Run phase is complete when each detector family can run in shadow, reports per-family precision
and count inflation, and no family emits production signals without GO evidence.

Completed in v0.1.1 with DB-backed shadow storage, per-family readiness guardrails, same-day/next-day
shadow lane reporting, operator script smoke coverage, and focused regression tests.
