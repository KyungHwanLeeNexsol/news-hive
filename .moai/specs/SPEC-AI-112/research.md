# SPEC-AI-112 Research

Status: implemented
Created: 2026-08-10

## Evidence

- Recent five official evaluations checked on 2026-08-10: predicted 68, actual 289, true positive 3.
- Market recall over that slice is about 1.0%; precision is about 4.4%.
- SPEC-AI-111 research cites the 2026-07-03 to 2026-07-27 production gap report: 84.9% of actual surges had no T-1 signal, and 83.1% of no-signal actual surges were absent from all T-1 scan-universe pools.
- Existing Pool A/B/C bridge wiring could theoretically recover only a minority of no-signal misses; therefore absent-source discovery must precede broad activation.

## Existing Assets

- `SurgeActualOutcome` supplies actual surge labels.
- `SurgePredictionEvaluation` supplies official predicted-code snapshots when present.
- `SurgeUniverseMember` supplies T-1 pool membership.
- News/disclosure models can provide evidence payloads for catalyst classification.
- SPEC-AI-109/110 define the latest evaluation repair and metric-basis semantics.

## Risk

Attribution is hindsight-heavy by nature. The implementation must separate evidence that existed before the T-1 cut from same-day evidence; otherwise it will overstate recoverable recall.
