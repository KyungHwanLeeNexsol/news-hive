# SPEC-AI-113 Research

Status: implemented-no-go
Created: 2026-08-10

## Evidence

- SPEC-AI-111 progress records `implemented-no-go` because the workspace DB setting was unavailable.
- `surge_detection.yaml` has `scan_universe_bridge_shadow_enabled: true` but no real bridge master switch.
- The bridge generator already supports Pool A-only activation through existing pool limits.
- SPEC-AI-105 provides shadow persistence and pool-separated precision measurement.

## Risk

Pool A bridge can improve only misses already present in Pool A shadow output. SPEC-AI-111 research estimated that existing pool bridge wiring cannot recover the majority of absent-source misses, so this canary must be treated as an incremental recovery lever, not the whole recall solution.
