---
id: SPEC-AI-110
title: "급등예측 평가 API 지표 명확화"
version: "0.1.0"
status: completed
created: 2026-08-07
updated: 2026-08-07
author: Nexsol
priority: High
phase: "backend surge-evaluation v0.1.0"
module: "backend/app/routers"
lifecycle: spec-anchored
tags: "surge-evaluation, api, metrics, recall, observability"
tier: S
related_specs: [SPEC-AI-068, SPEC-AI-092, SPEC-AI-095, SPEC-AI-109]
---

# SPEC-AI-110: 급등예측 평가 API 지표 명확화

## Context

`surge_prediction_evaluation.recall`은 유니버스가 존재하는 날짜에는 scannable recall로
저장될 수 있다. 반면 운영 현황 점검에서는 시장 전체 actual 대비 recall
(`true_positive / actual_surge_count`)이 필요하다. 기존 API가 `recall`만 노출하면
소비자가 시장 전체 예측력을 과대평가할 수 있다.

## Goals

1. 기존 `recall` 필드는 하위호환을 위해 유지한다.
2. API가 count 기반 `market_recall`과 `market_f1_score`를 별도로 노출한다.
3. scannable/coverage/high-based 병렬 지표도 목록, 상세, prediction-history 행에
   함께 노출한다.

## Non-Goals

- DB 컬럼/마이그레이션을 추가하지 않는다.
- 저장된 `recall` 의미를 즉시 변경하지 않는다.
- 예측 생성, detector, threshold 로직을 변경하지 않는다.

## Requirements

### REQ-AI110-001 (P0, Ubiquitous) — market recall 병렬 노출

the system **shall** evaluation API 응답에 `market_recall = true_positive /
actual_surge_count`를 추가해야 한다. `actual_surge_count == 0`이면
`market_recall`은 `None`이어야 한다.

### REQ-AI110-002 (P0, Ubiquitous) — recall basis 명시

the system **shall** 저장 `recall` 필드가 어떤 기준인지 알 수 있도록 `recall_basis`를
노출해야 한다. `scannable_recall`이 존재하면 `scannable`, 없으면 `market`으로 둔다.

### REQ-AI110-003 (P1, Ubiquitous) — 병렬 지표 노출

the system **shall** `scannable_recall`, `coverage`, `scannable_actual_count`,
`total_actual_count`, `high_based_recall`, `high_based_precision`,
`high_based_coverage`를 evaluation 목록/상세/history 응답에 추가해야 한다.

## Acceptance Criteria

- AC-110-001: evaluation 목록 응답에 `market_recall`과 `recall_basis`가 포함된다.
- AC-110-002: 저장 `recall`과 시장 recall이 다를 때 두 값이 별도 필드로 반환된다.
- AC-110-003: evaluation 상세 응답에도 `market_recall`이 포함된다.
