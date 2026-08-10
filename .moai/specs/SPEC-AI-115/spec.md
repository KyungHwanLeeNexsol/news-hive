---
id: SPEC-AI-115
title: "급등예측 gate/drop attribution 및 보수 필터 완화 shadow"
version: "0.1.1"
status: implemented
created: 2026-08-10
updated: 2026-08-10
author: Nexsol
priority: High
phase: "backend surge-detection v0.1.0"
module: "backend/app/services"
lifecycle: spec-anchored
tags: "surge-detection, threshold, guardrail, drop-attribution, shadow, observability"
tier: M
depends_on: [SPEC-AI-096, SPEC-AI-100, SPEC-AI-102, SPEC-AI-110, SPEC-AI-112]
related_specs: [SPEC-AI-113, SPEC-AI-114, SPEC-AI-116]
---

# SPEC-AI-115: gate/drop attribution 및 보수 필터 완화 shadow

## Context

후보 생성 파이프라인은 recall보다 precision 보호 쪽으로 설계되어 있다. main threshold,
strong/immediate bypass threshold, `combo_chase_guard`, `_MAX_PRICE_FETCH_CANDIDATES` 절단,
`sector_contagion` gate, 평가 exclusion이 여러 단계에 걸쳐 후보를 제거한다. 현재는 최종
공식 예측이 적을 때 어느 gate가 얼마나 많은 잠재 TP를 버렸는지 일자별로 재구성하기 어렵다.

이 SPEC은 gate를 바로 완화하지 않는다. 후보가 어느 단계에서 drop됐는지 관측하고, 제한된
shadow 완화 설정으로 recall gain과 false-positive cost를 측정한다.

## Goals

1. 후보별 drop stage와 drop reason을 날짜별로 관측한다.
2. conservative gate 완화안을 shadow로 실행해 공식 예측과 비교한다.
3. 완화안이 실제 config 전환 대상인지 판단할 guardrail을 만든다.

## Non-Goals

### Out of Scope - immediate threshold flip

- 이 SPEC의 기본 산출물은 shadow measurement이다.
- main threshold, bypass threshold, combo guard, sector gate를 바로 production 값으로 바꾸지 않는다.

### Out of Scope - bridge activation

- Pool A bridge activation은 SPEC-AI-113 소관이다.
- source-pool absent miss는 SPEC-AI-112/116 소관이다.

### Out of Scope - trading risk model

- 매수/매도 risk limit과 주문 실행 로직은 변경하지 않는다.

## Requirements

### REQ-AI115-001 (P0, Event-Driven) - drop observation

**When** `gather_surge_candidates()` processes candidates, the detection layer shall record a
drop observation for candidates removed by major gates.

필수 drop stage:

- `below_regime_threshold`
- `strong_bypass_failed`
- `immediate_bypass_failed`
- `combo_chase_guard`
- `price_fetch_truncation`
- `sector_contagion_gate`
- `evaluation_excluded_same_day`
- `evaluation_excluded_near_limit_carry`

필수 조건:

- observation records include stock code, trading date, detector set, score before drop,
  gate name, and compact reason metadata.
- observation failure shall not stop signal generation.

### REQ-AI115-002 (P0, Ubiquitous) - official output preservation

The initial implementation shall preserve the official `surge_candidate` output set.

필수 조건:

- drop observations are side effects only.
- tests compare qualified candidate codes before and after observation wiring.

### REQ-AI115-003 (P1, Event-Driven) - shadow relaxed gate run

**When** shadow gate mode is enabled, the detector shall compute an alternate candidate set using
one bounded relaxed-gate profile and persist/report the diff against official candidates.

필수 조건:

- shadow candidates do not emit `FundSignal`.
- relaxed profile changes one gate family at a time unless explicitly named as a combined profile.
- diff includes added candidates, removed candidates, expected TP/FP after actual outcomes exist,
  and prediction-count inflation.

### REQ-AI115-004 (P1, Ubiquitous) - guardrail decision report

The report shall rank gate relaxations by estimated recall gain per added false positive.

필수 조건:

- require at least 10 eligible evaluation days before recommending a config change.
- reject any relaxation that increases candidate count above 2x baseline unless precision gain is explicit.
- mark insufficient data as NO-GO rather than recommending a change.

### REQ-AI115-005 (P0, State-Driven) - evaluation basis compatibility

**While** drop attribution is enabled, SPEC-AI-110 market/scannable/high-based metrics shall remain
unchanged.

필수 조건:

- evaluation exclusion observations may be reported but shall not alter TP/FP/FN calculations.

## Implementation Notes

- Added `surge_gate_drop_observations` as an append-only observation table with compact JSON
  detector/reason fields.
- Wired observation hooks into `gather_surge_candidates()` for:
  `below_regime_threshold`, `strong_bypass_failed`, `immediate_bypass_failed`,
  `combo_chase_guard`, `price_fetch_truncation`, and `sector_contagion_gate`.
- Wired evaluation-only observations into `evaluate_surge_predictions()` for:
  `evaluation_excluded_same_day` and `evaluation_excluded_near_limit_carry`.
- Added `regime_threshold_minus_0_05` as the first bounded relaxed-gate shadow profile.
  It marks near-threshold non-official candidates as `shadow_candidate=True` without emitting
  `FundSignal` rows.
- Added `scripts/spec_ai_115_gate_attribution_report.py` to rank relaxed profiles by expected
  TP/FP cost after evaluation outcomes exist.

## Decisions

1. Drop observations are persisted in DB rather than emitted only as logs so later evaluation
   days can be joined against actual outcomes.
2. The first shadow profile is a single-family regime threshold relaxation of `-0.05`.
3. Official `surge_candidate` output remains unchanged; shadow candidates are observation rows
   only.

## Verification

- `backend> .\.venv\Scripts\python.exe -m pytest tests\test_spec_ai_115.py -q`
  - 7 passed.
- `backend> .\.venv\Scripts\python.exe -m ruff check app\services\surge_gate_attribution_service.py app\services\surge_detector.py app\services\surge_evaluation_service.py app\models\surge_gate_drop_observation.py scripts\spec_ai_115_gate_attribution_report.py tests\test_spec_ai_115.py`
  - passed.
- `backend> .\.venv\Scripts\python.exe -m pytest tests\test_spec_ai_092.py tests\test_spec_ai_102.py tests\test_spec_ai_105.py tests\test_spec_ai_111.py tests\test_spec_ai_112.py tests\test_spec_ai_113.py tests\test_spec_ai_114.py tests\test_spec_ai_115.py tests\test_surge_eval_endpoints.py -q`
  - 105 passed, 3 warnings (2 existing datetime deprecations, 1 fail-open rollback warning).
- `backend> .\.venv\Scripts\python.exe scripts\spec_ai_115_gate_attribution_report.py --help`
  - passed.
- `backend> .\.venv\Scripts\python.exe scripts\spec_ai_115_gate_attribution_report.py --compact`
  - returned `db_unavailable` because local PostgreSQL on `localhost:5432` is not running.
