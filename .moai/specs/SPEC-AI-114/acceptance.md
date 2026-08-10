# SPEC-AI-114 Acceptance Criteria

Status: implemented

### AC-114-001

Given a trading date with next-day and same-day signals, when evaluation runs, then each signal
is assigned to exactly one lane.

### AC-114-002

Given same-day signals that overlap actual surge outcomes, when same-day metrics are computed,
then same-day predicted count, TP, FP, precision, and denominator basis are returned.

### AC-114-003

Given same-day signals exist, when standard T-1 evaluation is computed, then same-day codes do
not enter the standard predicted set.

### AC-114-004

Given evaluation list/detail/history API responses, then lane-specific fields are present and
SPEC-AI-110 metric fields remain present.

### AC-114-005

Given same-day catalyst evidence has article/disclosure references, then API output contains
compact references and no full article body.
