# SPEC-AI-112 Acceptance Criteria

Status: implemented

### AC-112-001

Given an evaluation day with actual surge rows, predicted codes, and scan-universe members,
when the attribution service runs, then it returns only actual surge codes absent from both
the standard predicted set and T-1 scan universe.

### AC-112-002

Given an absent miss with same-day news after the T-1 prediction cut, when classification runs,
then the primary bucket is `same_day_catalyst` and the row is not counted as T-1 recoverable.

### AC-112-003

Given an absent miss with contract or M&A keyword evidence available before the T-1 cut,
when classification runs, then the primary bucket is `contract_mna_keyword` and the proposed
source-pool recovery estimate includes it.

### AC-112-004

Given multiple matching buckets for one stock, when classification runs, then exactly one
primary bucket is selected according to the documented precedence and secondary tags preserve
the additional evidence.

### AC-112-005

Given a date range with no eligible evaluation rows, when the report path runs, then it returns
a clear `no_eligible_days` result instead of zero-filled performance claims.

### AC-112-006

Given existing `FundSignal` rows, when the attribution report runs, then `FundSignal` row count
and `surge_candidate` qualified output remain unchanged.

### AC-112-007

Given a generated report, then it includes total actual surges, predicted hits, scan-universe
coverage, absent misses, bucket counts, unknown share, and ranked proposed source pools.
