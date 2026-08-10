---
id: SPEC-AI-112
title: "급등예측 후보 표면 회복 - absent actual attribution and source-pool discovery"
version: "0.1.1"
status: implemented
created: 2026-08-10
updated: 2026-08-10
author: Nexsol
priority: Critical
phase: "backend surge-detection v0.1.0"
module: "backend/app/services"
lifecycle: spec-anchored
tags: "surge-detection, recall, scan-universe, attribution, source-discovery, observability"
tier: L
depends_on: [SPEC-AI-092, SPEC-AI-096, SPEC-AI-104, SPEC-AI-105, SPEC-AI-109, SPEC-AI-110]
related_specs: [SPEC-AI-111, SPEC-AI-113, SPEC-AI-114, SPEC-AI-115, SPEC-AI-116]
---

# SPEC-AI-112: 급등예측 후보 표면 회복

## Context

2026-08-10 급등예측력 점검에서 가장 큰 원인은 "점수 모델이 틀림"이 아니라 실제 급등주의
대부분이 공식 후보 표면에 들어오지 않는 구조로 확인됐다. 최근 5개 공식 평가일 합산 기준
예측 68개 중 적중은 3개였고, 실제 급등 289개 중 포착은 3개였다. SPEC-AI-111 research가
인용한 2026-07-03~2026-07-27 production gap report에서도 실제 급등 885개 중 84.9%가
T-1 신호가 없었고, no-signal actual 중 83.1%는 T-1 scan universe pool에도 없었다.

따라서 첫 번째 회복 SPEC은 threshold 완화나 bridge activation이 아니라, 후보 표면 밖
miss를 날짜별/사유별로 설명 가능한 데이터로 만드는 것이다. 이 SPEC은 예측 신호를 즉시
늘리지 않고, 어떤 신규 소스 풀이 가장 먼저 필요한지 결정할 수 있는 attribution ledger와
리포트를 만든다.

## Goals

1. 실제 급등주 중 T-1 predicted set과 scan universe 어느 곳에도 없던 absent miss를 날짜별로
   영속 또는 재현 가능한 ledger로 만든다.
2. absent miss를 same-day catalyst, late disclosure, volume spike, low-liquidity price move,
   contract/M&A keyword, theme-peer-only, unknown 등 실행 가능한 원인 bucket으로 분류한다.
3. 각 bucket별로 "새 소스 풀을 만들면 이론적으로 회수 가능한 miss"와 증거 payload를 리포트한다.
4. 후속 detector/bridge SPEC이 사용할 source-pool backlog를 우선순위와 guardrail까지 포함해
   생성한다.

## Non-Goals

### Out of Scope - production prediction emission

- 이 SPEC은 `FundSignal(signal_type="surge_candidate")`를 새로 발행하지 않는다.
- `scan_universe_bridge_candidates_enabled` 값을 변경하지 않는다.
- 거래 실행, 포트폴리오, 텔레그램 알림 경로를 변경하지 않는다.

### Out of Scope - detector scoring changes

- 1차 탐지기 점수 산식, ensemble threshold, bypass threshold, combo chase guard를 변경하지
  않는다.
- 신규 detector 구현은 SPEC-AI-116에서 다룬다.

### Out of Scope - historical actual reconstruction

- 실제 과거 가격 시계열을 재구성하는 대형 백필러를 만들지 않는다.
- 이미 존재하는 `SurgeActualOutcome`, `FundSignal`, `SurgeUniverseMember`, 뉴스/공시 DB,
  현재 사용 가능한 가격/거래량 조회만 사용한다.

## Requirements

### REQ-AI112-001 (P0, Event-Driven) - absent miss ledger

**When** 특정 거래일의 `SurgeActualOutcome`과 `SurgePredictionEvaluation` row가 존재하면,
the attribution service shall identify actual surge stock codes that were absent from both
the standard T-1 `predicted_set` and the T-1 `SurgeUniverseMember` scan universe.

필수 조건:

- standard T-1 `predicted_set`은 SPEC-AI-109/110 평가 로직과 같은 exclusion rule을 사용한다.
- `same_day`와 `near_limit_up_carry` exclusion은 별도 bucket으로 표시하고 T-1 recall 회수
  가능분으로 섞지 않는다.
- ledger row 또는 deterministic report row에는 trading date, stock code, stock name,
  actual change rate, scan-universe membership, predicted membership, and reason bucket을 포함한다.

### REQ-AI112-002 (P0, Ubiquitous) - reason taxonomy

The attribution service shall classify each absent miss into exactly one primary reason bucket
and zero or more secondary evidence tags.

기본 primary bucket:

- `same_day_catalyst`
- `late_disclosure`
- `volume_spike_without_t1`
- `low_liquidity_price_move`
- `contract_mna_keyword`
- `theme_peer_only`
- `source_absent_unknown`

필수 조건:

- primary bucket이 둘 이상 가능한 경우 결정 순서를 코드 상수로 고정한다.
- 어떤 bucket에도 들어가지 않으면 `source_absent_unknown`으로 분류한다.
- unknown 비율은 날짜별/기간별 리포트에 별도 표시한다.

### REQ-AI112-003 (P0, Event-Driven) - source-pool recovery estimate

**When** attribution rows are grouped over a date range, the report generator shall estimate
the recoverable miss count for each proposed source pool without emitting predictions.

필수 조건:

- recovery estimate는 "실제 급등을 hindsight로 맞춘 수"와 "T-1에 관측 가능했던 증거로
  후보화 가능했던 수"를 분리한다.
- same-day evidence는 T-1 source-pool recovery로 계산하지 않는다.
- 각 proposed pool은 estimated recall gain, expected candidate count, data dependency,
  and activation risk를 표시한다.

### REQ-AI112-004 (P1, Event-Driven) - evidence payload

**When** an absent miss has matching news, disclosure, volume, liquidity, or theme evidence,
the report row shall include a compact evidence payload sufficient for human review.

필수 조건:

- payload는 기사/공시 전문을 저장하지 않고 title, timestamp, source id, matched keyword,
  numeric features만 포함한다.
- payload 생성 실패는 해당 row의 attribution 실패로 격리하고 전체 리포트를 실패시키지 않는다.

### REQ-AI112-005 (P1, Ubiquitous) - operator report/API

The backend shall expose the attribution summary through one operator-facing path: either an
admin API endpoint or a repo script under `scripts/`.

필수 조건:

- default range는 최근 20 eligible trading days이다.
- output에는 total actual surges, predicted hits, scan-universe coverage, absent misses,
  bucket counts, unknown share, and top proposed source pools가 포함된다.
- API를 선택하면 관리자 인증을 요구한다.

### REQ-AI112-006 (P0, State-Driven) - no behavior change

**While** this SPEC is deployed, the implementation shall not change the production
`surge_candidate` emission set.

필수 조건:

- tests shall prove attribution/report execution leaves `FundSignal` count unchanged.
- `gather_surge_candidates()` qualified candidate set shall be unchanged unless a later SPEC
  explicitly activates a source pool.

## Implementation Notes

- Added `backend/app/services/surge_absent_attribution_service.py`.
- Added operator script `backend/scripts/spec_ai_112_absent_attribution_report.py`.
- The implementation is read-only and uses existing `SurgeActualOutcome`,
  `SurgePredictionEvaluation`, `SurgeUniverseMember`, `FundSignal`, news, stock, and disclosure
  tables.
- `predicted_codes_json` is preferred when available; rows without the snapshot fall back to the
  same standard T-1 `surge_candidate` query and near-limit/same-day exclusion helpers used by
  `evaluate_surge_predictions()`.
- No detector scoring, bridge activation, `FundSignal` emission, or trading path is changed.
