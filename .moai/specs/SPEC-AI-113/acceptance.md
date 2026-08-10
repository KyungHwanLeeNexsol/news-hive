# SPEC-AI-113 Acceptance Criteria

Status: implemented

### AC-113-001

Given the production-equivalent data source is unavailable, when readiness runs, then it returns
`database_unavailable` or equivalent no-go without changing bridge config.

### AC-113-002

Given at least 10 eligible days and Pool A shadow precision meeting the guardrail, when readiness
runs, then it returns GO with eligible count, Pool A precision, baseline precision, and candidate count.

### AC-113-003

Given readiness is NO-GO, when the implementation completes, then `scan_universe_bridge_candidates_enabled`
is absent or false.

### AC-113-004

Given readiness is GO and the canary is approved, when config is applied, then only Pool A bridge
can emit candidates and Pool B/Pool C/Pool D cannot enter bridge output.

### AC-113-005

Given Pool A canary is active, when five consecutive eligible days have 0.0 Pool A bridge precision,
then the rollback monitor emits a rollback recommendation.

### AC-113-006

Given evaluation/history rows include bridge candidates, then bridge counts are visible without
removing `market_recall`, `scannable_recall`, `coverage`, or `recall_basis`.

### AC-113-007

Given SPEC-AI-113 finishes, then SPEC-AI-111 progress is linked to the new GO/NO-GO outcome.
