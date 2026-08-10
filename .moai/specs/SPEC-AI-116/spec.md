---
id: SPEC-AI-116
title: "급등예측 missing trigger detector pack - contract/M&A, volume spike, low-liquidity"
version: "0.1.0"
status: implemented
created: 2026-08-10
updated: 2026-08-10
author: Nexsol
priority: High
phase: "backend surge-detection v0.1.0"
module: "backend/app/services"
lifecycle: spec-anchored
tags: "surge-detection, detector, mna, contract, volume-spike, low-liquidity, shadow"
tier: L
depends_on: [SPEC-AI-112, SPEC-AI-114, SPEC-AI-115]
related_specs: [SPEC-AI-092, SPEC-AI-101, SPEC-AI-113]
---

# SPEC-AI-116: missing trigger detector pack

## Context

최근 실패 사례는 저유동성 가격 급등, 계약/수주 뉴스, M&A/경영권 이슈, 거래량 급증형이
반복적으로 나타났다. 그러나 detector를 바로 늘리면 이미 낮은 precision을 더 악화시킬 수
있다. 이 SPEC은 SPEC-AI-112의 absent miss attribution과 SPEC-AI-115의 drop attribution을
입력으로 삼아, missing trigger detector들을 shadow-first로 추가한다.

## Goals

1. contract/M&A keyword, abnormal volume spike, low-liquidity price move trigger를 독립
   feature flag로 추가한다.
2. 각 detector는 shadow mode에서 먼저 후보와 evidence를 저장한다.
3. 충분한 평가일과 precision guardrail을 통과한 detector만 production emission 후보가 된다.

## Non-Goals

### Out of Scope - one-shot broad activation

- 세 detector를 한 번에 production emission으로 켜지 않는다.
- shadow evidence 없이 config를 활성화하지 않는다.

### Out of Scope - full ML model

- 지도학습 모델 학습, feature store, online serving은 포함하지 않는다.
- 기존 rule/score 기반 detector framework 안에서만 확장한다.

### Out of Scope - same-day metric contamination

- same-day trigger는 SPEC-AI-114 same-day lane으로 평가한다.
- T-1 next-day metric에 same-day trigger를 섞지 않는다.

## Requirements

### REQ-AI116-001 (P0, Event-Driven) - attribution-driven detector selection

**When** SPEC-AI-112 attribution over the configured lookback window identifies a trigger bucket
above the activation threshold, the detector pack shall enable shadow measurement for the matching
detector family.

필수 조건:

- no detector family can be production-enabled before it has shadow evidence.
- if attribution data is insufficient, the detector pack returns NO-GO.

### REQ-AI116-002 (P0, Capability Gate) - contract/M&A detector

**Where** the contract/M&A detector flag is enabled, the detector shall identify compact news or
disclosure evidence for supply contract, acquisition, merger, management-right, investment, or
business-transfer catalysts.

필수 조건:

- keyword matching must preserve matched keyword and source reference.
- full article/disclosure body is not copied into signal metadata.
- T-1 and same-day horizon are tagged separately.

### REQ-AI116-003 (P0, Capability Gate) - abnormal volume spike detector

**Where** the abnormal volume spike detector flag is enabled, the detector shall score stocks whose
current or previous-session volume materially exceeds their baseline volume.

필수 조건:

- use existing batch price-history infrastructure where multiple stocks are inspected.
- score metadata includes baseline window, volume ratio, and liquidity guard.
- missing price history skips the stock without failing the scan.

### REQ-AI116-004 (P1, Capability Gate) - low-liquidity price move detector

**Where** the low-liquidity detector flag is enabled, the detector shall classify thinly traded
price moves as high-risk candidates and keep them shadow-only until precision is proven.

필수 조건:

- metadata includes liquidity bucket, turnover estimate, and reason.
- low-liquidity candidates cannot bypass risk gates by default.

### REQ-AI116-005 (P0, State-Driven) - shadow-first emission guard

**While** a detector family lacks at least 10 eligible evaluated trading days of shadow evidence,
the detector family shall not emit production `surge_candidate` signals.

필수 조건:

- detector precision must be compared against same-period baseline precision.
- candidate-count inflation must be reported.
- GO/NO-GO is per detector family, not blended across all families.

### REQ-AI116-006 (P0, Ubiquitous) - horizon compatibility

The detector pack shall tag every candidate with explicit horizon metadata.

필수 조건:

- same-day candidates flow into SPEC-AI-114 same-day lane.
- next-day candidates remain eligible for standard T-1 evaluation only when their evidence existed before the cut.

## Implementation Notes

- Added append-only shadow candidate storage in `surge_missing_trigger_shadow_candidates`.
- Added independent shadow detector families for `contract_mna`, `volume_spike`, and `low_liquidity`.
- Added attribution-driven family selection from SPEC-AI-112 output; insufficient attribution keeps all families NO-GO.
- Added per-family readiness reporting with baseline precision, added TP/FP, candidate-count inflation, and production GO/NO-GO.
- Added explicit shadow lane breakdown for `same_day` and `next_day`; shadow candidates do not emit `FundSignal` and have zero standard T-1 predicted-set impact.
- Production emission remains disabled by design until shadow evidence satisfies guardrails.
