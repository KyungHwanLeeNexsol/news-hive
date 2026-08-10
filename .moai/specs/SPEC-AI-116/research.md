# SPEC-AI-116 Research

Status: implemented
Created: 2026-08-10

## Evidence

- Recent miss analysis repeatedly named volume spike, low-liquidity price move, and contract/M&A/news catalysts as plausible explanations.
- SPEC-AI-112 will provide the non-hindsight attribution needed to avoid building detectors from isolated anecdotes.
- SPEC-AI-114 is required so same-day catalysts do not contaminate T-1 forecast metrics.
- SPEC-AI-115 is required so new detector candidates can be compared against existing drop and threshold behavior.

## Risk

Detector expansion is the easiest way to increase false positives. The detector pack must stay shadow-first and detector-family-specific until enough eligible evaluation days exist.
