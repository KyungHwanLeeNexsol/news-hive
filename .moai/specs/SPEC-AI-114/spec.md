---
id: SPEC-AI-114
title: "급등예측 same-day catalyst lane 분리 및 horizon별 평가"
version: "0.1.1"
status: implemented
created: 2026-08-10
updated: 2026-08-10
author: Nexsol
priority: High
phase: "backend surge-evaluation v0.1.0"
module: "backend/app/services"
lifecycle: spec-anchored
tags: "surge-evaluation, same-day, horizon, catalyst, metrics, api"
tier: M
depends_on: [SPEC-AI-083, SPEC-AI-101, SPEC-AI-109, SPEC-AI-110]
related_specs: [SPEC-AI-112, SPEC-AI-113, SPEC-AI-115, SPEC-AI-116]
---

# SPEC-AI-114: same-day catalyst lane 분리 및 horizon별 평가

## Context

표준 급등예측 평가는 T-1 신호가 T일 실제 급등을 맞췄는지 측정한다. 코드상
`surge_metadata.horizon == "same_day"` 신호는 표준 predicted set에서 제외된다. 이 설계는
타당하지만, 현재 운영 분석에서는 "T-1 예측 실패"와 "당일 catalyst 대응 부재"가 한 문장으로
섞여 보인다. 당일 뉴스, 공시, 거래량 급증형 급등이 많으면 T-1 recall은 낮을 수밖에 없다.

이 SPEC은 same-day 신호를 표준 T-1 지표로 다시 섞지 않고, 별도 lane과 별도 KPI로 평가한다.

## Goals

1. T-1 next-day lane과 same-day catalyst lane을 API/리포트에서 명확히 분리한다.
2. same-day 신호의 precision/coverage를 별도 계산해 당일 대응 제품성을 판단한다.
3. same-day 성과가 표준 T-1 recall/precision을 오염시키지 않도록 metric basis를 고정한다.

## Non-Goals

### Out of Scope - same-day detector expansion

- 신규 same-day detector 자체는 이 SPEC에서 추가하지 않는다.
- SPEC-AI-116이 missing trigger detector pack을 별도로 소유한다.

### Out of Scope - T-1 metric redefinition

- 표준 T-1 predicted set exclusion rule을 완화하지 않는다.
- near-limit carry exclusion도 변경하지 않는다.

### Out of Scope - trading execution changes

- intraday 매수 sizing, 주문 시간, 리스크 관리는 변경하지 않는다.

## Requirements

### REQ-AI114-001 (P0, Ubiquitous) - lane contract

The evaluation layer shall expose two explicit surge prediction lanes:

- `next_day`: standard T-1 to T prediction, excluding same-day and near-limit carry signals.
- `same_day`: signals whose metadata declares `horizon == "same_day"`.

필수 조건:

- one signal belongs to exactly one lane.
- existing T-1 precision/recall values remain backward compatible.

### REQ-AI114-002 (P0, Event-Driven) - same-day metric computation

**When** same-day signals exist for a trading date, the evaluation service shall compute same-day
predicted count, true positive count, false positive count, precision, and actual coverage.

필수 조건:

- same-day true positive is counted only when the stock becomes an actual surge on the same trading date.
- same-day recall shall not be named `recall` unless its denominator is explicitly shown.
- if same-day actual denominator is unavailable, the metric shall return null rather than zero.

### REQ-AI114-003 (P0, Ubiquitous) - metric basis visibility

The API shall expose lane-specific metric names so consumers cannot confuse same-day response
with T-1 forecast skill.

필수 조건:

- list, detail, and prediction-history responses include lane fields or nested lane objects.
- `recall_basis` from SPEC-AI-110 remains present.
- no response removes existing fields without a compatibility plan.

### REQ-AI114-004 (P1, Event-Driven) - same-day evidence linkage

**When** a same-day signal is evaluated, the service shall preserve catalyst evidence metadata
needed to debug why it fired.

필수 조건:

- include detector name, created_at, stock code, price_at_signal when available, and compact catalyst reference.
- do not store full copyrighted article text.

### REQ-AI114-005 (P0, State-Driven) - no T-1 contamination

**While** same-day lane metrics are enabled, same-day signals shall remain excluded from the
standard T-1 predicted set.

필수 조건:

- regression tests cover mixed next-day and same-day signals for the same trading date.
- mixed-lane duplicates are resolved deterministically in API output.

## Implementation Notes

- Added `backend/app/services/surge_lane_metrics_service.py`.
- Same-day lane metrics are computed from existing `FundSignal` and `SurgeActualOutcome` rows;
  no new table or migration was added.
- API list/detail/history responses now include nested `lanes.next_day` and `lanes.same_day`
  objects while preserving existing SPEC-AI-110 fields.
- Same-day catalyst evidence is compacted to references and does not include article/disclosure
  body text.
- Standard T-1 evaluation and `_is_same_day_event_horizon_signal()` exclusion behavior remain
  unchanged.
