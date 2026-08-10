---
id: SPEC-AI-113
title: "급등예측 Pool A bridge NO-GO 해소 및 운영 canary 전환"
version: "0.1.1"
status: implemented
created: 2026-08-10
updated: 2026-08-10
author: Nexsol
priority: Critical
phase: "backend surge-detection v0.1.0"
module: "backend/app/services"
lifecycle: spec-anchored
tags: "surge-detection, scan-universe, bridge-candidates, pool-a, canary, rollback"
tier: M
depends_on: [SPEC-AI-105, SPEC-AI-109, SPEC-AI-110, SPEC-AI-111]
related_specs: [SPEC-AI-102, SPEC-AI-112, SPEC-AI-114, SPEC-AI-115]
---

# SPEC-AI-113: Pool A bridge NO-GO 해소 및 운영 canary 전환

## Context

SPEC-AI-111은 Pool A-only bridge 활성화 readiness gate와 테스트를 구현했지만, workspace의
DB 설정이 `localhost:5432/news_hive`에 연결되지 않아 production-grade readiness 판단을 하지
못했다. 그 결과 `scan_universe_bridge_candidates_enabled`는 계속 absent/false이고, 2026-08-10
운영 prediction-history도 공식 `surge_candidate` 0개 상태를 보였다.

이 SPEC은 기존 111을 다시 구현하지 않는다. 목적은 no-go 원인이었던 운영 DB/API 접근 갭을
닫고, 충분한 shadow/outcome/evaluation evidence가 있으면 Pool A-only canary를 제한적으로
적용하며, 실패하면 명확한 no-go evidence를 남기는 것이다.

## Goals

1. Pool A bridge readiness gate를 운영 DB 또는 운영 API 기준으로 재실행 가능하게 한다.
2. readiness 결과가 GO일 때만 Pool A-only canary config를 적용한다.
3. canary 적용 후 precision/count/runtime guardrail을 매일 모니터링하고 단일 config rollback
   경로를 보장한다.
4. SPEC-AI-111 상태를 후속 완료 체계에 연결한다.

## Non-Goals

### Out of Scope - bridge scoring redesign

- `_BRIDGE_MIN_SCORE`, Pool A 점수 산식, Pool C/Pool B scoring을 변경하지 않는다.
- Pool B와 Pool C 실활성화는 이 SPEC에서 다루지 않는다.

### Out of Scope - broad recall recovery

- scan universe 밖 absent miss는 SPEC-AI-112와 후속 source-pool SPEC의 영역이다.
- 이 SPEC의 기대 효과는 Pool A shadow가 회수 가능한 부분에 한정된다.

### Out of Scope - automatic trading escalation

- bridge candidate 활성화는 예측 후보 생성에만 영향을 준다.
- 매수 주문 sizing, portfolio allocation, risk limit은 변경하지 않는다.

## Requirements

### REQ-AI113-001 (P0, Event-Driven) - production readiness execution path

**When** an operator requests Pool A bridge readiness, the backend or script shall run
`evaluate_bridge_activation_readiness()` against the configured production-equivalent data source
instead of assuming a local development database.

필수 조건:

- result includes data source identity without exposing secrets.
- result includes eligible day count, Pool A aggregate shadow precision, baseline precision,
  consecutive zero-precision streak, candidate count, and GO/NO-GO reason.
- database connection failure returns `database_unavailable` with actionable context.

### REQ-AI113-002 (P0, State-Driven) - GO-only config application

**While** readiness status is not GO, the implementation shall not enable
`scan_universe_bridge_candidates_enabled`.

**When** readiness status is GO and the user approves implementation kickoff, the deployment config
shall apply Pool A-only values:

```yaml
scan_universe_bridge_candidates_enabled: true
scan_universe_bridge_pool_b_enabled: false
scan_universe_bridge_max_candidates: 5
scan_universe_bridge_pool_limits:
  pool_a: 5
  pool_b: 0
  pool_c: 0
scan_universe_bridge_shadow_enabled: true
```

### REQ-AI113-003 (P0, Ubiquitous) - Pool C/B/D remain blocked

The bridge canary shall emit only Pool A bridge candidates.

필수 조건:

- Pool B fetch path remains disabled and tests prove no Pool B price-history bridge fetch occurs.
- Pool C limit is 0.
- Pool D remains measurement-only and cannot enter bridge output.

### REQ-AI113-004 (P0, Event-Driven) - post-activation rollback monitor

**When** Pool A bridge canary is active, the scheduler shall compute daily guardrail status and
emit a rollback recommendation when any rollback trigger is detected.

Rollback triggers:

- Pool A bridge precision below readiness threshold after activation.
- Pool A bridge precision is 0.0 for five consecutive eligible trading days.
- total prediction count exceeds 3x the previous 14-day average.
- any Pool B bridge price-history fetch occurs while Pool B is disabled.
- scheduler runtime materially regresses relative to the previous 14-day baseline.

### REQ-AI113-005 (P1, Ubiquitous) - bridge observability fields

The evaluation/history response or operator report shall expose bridge candidate counts by pool.

필수 조건:

- include total bridge candidate count and Pool A bridge candidate count.
- preserve SPEC-AI-110 market/scannable metric fields.
- include `recall_basis` so bridge impact is not confused with a metric-definition change.

### REQ-AI113-006 (P0, Event-Driven) - SPEC-AI-111 closure link

**When** this SPEC records a GO or NO-GO outcome, the progress artifact shall link back to
SPEC-AI-111 and state whether its previous no-go blocker has been resolved.

## Implementation Notes

- Added `backend/app/services/surge_bridge_readiness_service.py` with a production-safe readiness
  runner, non-secret data-source identity, GO-only Pool A config copy helper, and rollback
  guardrail evaluator.
- Added operator script `backend/scripts/spec_ai_113_bridge_readiness_report.py`.
- Added scheduler callback `_run_surge_bridge_guardrail_monitor()` and registered it as a
  read-only weekday 19:20 KST job. When bridge canary is inactive, it exits with inactive status.
- Added bridge count fields to evaluation/history responses:
  `bridge_candidate_count`, `bridge_pool_a_candidate_count`,
  `bridge_candidate_count_by_pool`.
- Did not modify `backend/app/surge_config/surge_detection.yaml` to enable
  `scan_universe_bridge_candidates_enabled`.

## Delivery State

Run phase completed with implementation present and production activation NO-GO.

Reason: `database_unavailable` from the configured local PostgreSQL endpoint
`localhost:5432/news_hive`.

`scan_universe_bridge_candidates_enabled` remains absent/false. SPEC-AI-111's previous no-go
blocker is not resolved in this workspace because no production-equivalent DB/API source was
available, but it now has a repeatable operator readiness path and rollback monitor.
