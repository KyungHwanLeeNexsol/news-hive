# Surge Prediction Recovery SPEC Cleanup - 2026-08-10

## Scope

This cleanup records the SPEC queue created after the 2026-08-10 analysis of low surge prediction power.
It is a planning/report artifact, not an implementation result.

## Operating Evidence

- Latest official evaluation available through the operating API was 2026-08-03.
- Recent five official evaluation rows summed to predicted=68, actual=289, true_positive=3.
- Market-level recall over that slice was about 1.0%; precision was about 4.4%.
- 2026-08-10 prediction-history showed current official `surge_candidate` count 0.
- SPEC-AI-111 remained `implemented-no-go` because Pool A readiness could not be evaluated against an available production-grade DB.

## Cause-Ordered Recovery Queue

| Order | Cause | SPEC | Status | Reason |
|---:|---|---|---|---|
| 1 | Actual surges absent from candidate surface | SPEC-AI-112 | draft | Quantifies absent miss buckets and source-pool recovery candidates before adding detectors. |
| 2 | Scan-universe members not promoted | SPEC-AI-113 | draft | Resolves SPEC-AI-111 no-go and reruns Pool A bridge readiness against production-equivalent data. |
| 3 | T-1 forecast and same-day catalyst are mixed in analysis | SPEC-AI-114 | draft | Separates same-day lane metrics from standard T-1 metrics. |
| 4 | Conservative gates drop candidates without attribution | SPEC-AI-115 | draft | Adds drop-stage observability and shadow gate-relaxation reports before any threshold change. |
| 5 | Missing trigger classes in recent FNs | SPEC-AI-116 | draft | Adds shadow-first detector pack for contract/M&A, volume spike, and low-liquidity triggers. |

## Direct Residual SPEC Cleanup

| SPEC | Previous State | Cleanup Action |
|---|---|---|
| SPEC-AI-102 | `spec.md` said `in-progress`; progress recorded run implemented and sync pending. | Frontmatter corrected to `implemented`; sync remains pending. |
| SPEC-AI-111 | `spec.md`/plan/acceptance/research said planned/draft while progress recorded `implemented-no-go`. | Artifacts updated to `implemented-no-go`; follow-up linked to SPEC-AI-113. |
| SPEC-AI-109 | Documented completed, but operating API still stale after 2026-08-03. | Treat as deployment/operation verification prerequisite before trusting new metrics. |
| SPEC-AI-110 | Documented completed, but operating API response did not show new metric fields during 2026-08-10 check. | Treat as deployment/operation verification prerequisite before comparing recall bases. |

## Deferred Cleanup

`moai spec drift` reported 23 status-drift rows. Most are modern-era git-implied drift or protected legacy/era-exempt records outside the immediate surge-prediction recovery path. They were not mass-edited in this cleanup to avoid changing unrelated historical SPEC state.

Recommended separate cleanup later:

1. Run `moai spec drift`.
2. Close only SPECs with explicit run/sync evidence in `progress.md`.
3. Archive or mark superseded legacy drafts only after reading their body and related implementation evidence.

## Next Execution Recommendation

Run order should be:

1. `moai run SPEC-AI-112`
2. `moai run SPEC-AI-113`
3. `moai run SPEC-AI-114`
4. `moai run SPEC-AI-115`
5. `moai run SPEC-AI-116`

Before any metric comparison, verify production deployment freshness for SPEC-AI-109 and SPEC-AI-110.
