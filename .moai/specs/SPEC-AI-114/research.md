# SPEC-AI-114 Research

Status: implemented
Created: 2026-08-10

## Evidence

- `evaluate_surge_predictions()` excludes `horizon == "same_day"` signals from the standard T-1 predicted set.
- Recent live snapshots showed current official prediction count can be zero while same-day market movement exists.
- SPEC-AI-101 added horizon and forward outcome observability but did not turn same-day response into a separate public KPI.

## Risk

If same-day metrics are named too similarly to T-1 recall, operators may interpret intraday reaction as forecast skill. The API shape must make lane and denominator explicit.
