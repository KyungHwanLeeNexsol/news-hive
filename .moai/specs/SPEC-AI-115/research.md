# SPEC-AI-115 Research

Status: implemented
Created: 2026-08-10

## Evidence

- Main regime thresholds are currently around 0.38 to 0.45 depending on market regime.
- Strong/immediate disclosure bypass thresholds are 0.85.
- `combo_chase_guard` removes combo-only candidates when companion detector evidence is absent.
- `_MAX_PRICE_FETCH_CANDIDATES` still bounds the expensive price-history scoring path.
- Final gates such as sector contagion can remove candidates after provisional qualification.

## Risk

Lowering gates without attribution can produce a candidate-count explosion and make precision worse. Shadow-first measurement is required because recent precision is already low.
