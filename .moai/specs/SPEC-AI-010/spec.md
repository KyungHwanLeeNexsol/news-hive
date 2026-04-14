---
id: SPEC-AI-010
version: 1.0.0
status: draft
created: 2026-04-14
updated: 2026-04-14
author: Nexsol
priority: Medium
issue_number: 0
---

# SPEC-AI-010: fund_manager 감성 분석 통합 (종토방 + 증권사 컨센서스)

## HISTORY

- 2026-04-14: 초안 작성 (SPEC-AI-008 종토방 수집 및 SPEC-AI-009 증권사 컨센서스와 연계)

## Overview

`fund_manager.analyze_stock()`에 두 가지 추가 감성/컨센서스 채널을 통합하여 AI 기반 종목 분석의 품질을 향상시킨다. 기존 뉴스 센티먼트 로직은 유지하며, 종토방(역발상 지표)과 증권사 컨센서스를 별도 섹션으로 프롬프트에 추가한다.

설계 원칙:
- 뉴스 센티먼트(가중치 1.0)를 주 신호로 유지
- 종토방 센티먼트(가중치 0.2, 역발상)는 보조 지표로만 사용
- 증권사 컨센서스는 독립 섹션으로 프롬프트에 삽입
- 과열/급증 시 AI에 명시적 주의 지시 (매수 신호 억제)

## Dependencies

- **SPEC-AI-008** (종토방 감성 수집): `StockForumHourly` 모델 및 `_gather_forum_sentiment()` 함수가 반드시 선행 구현되어야 함
- **SPEC-AI-009** (증권사 컨센서스): `_gather_securities_consensus()` 함수가 반드시 선행 구현되어야 함

두 선행 SPEC이 배포되지 않아도 본 SPEC은 graceful fallback으로 동작해야 함 (REQ-SENTIMENT-006 참조).

## Requirements (EARS Format)

### REQ-SENTIMENT-001 (Event-Driven)
**WHEN** `analyze_stock()`이 호출되고 StockForumHourly 테이블에 해당 stock의 데이터가 존재하는 경우, **THEN** the system **SHALL** call `_gather_forum_sentiment()` within `analyze_stock()` and include its result in AI analysis context.

### REQ-SENTIMENT-002 (Ubiquitous)
The system **SHALL** include forum sentiment in the AI prompt as a separate section distinct from news sentiment with the header "## 1-2. 종토방 감성 (역발상 지표)".

### REQ-SENTIMENT-003 (Event-Driven)
**WHEN** `overheating_alert` is True in the forum sentiment result, **THEN** the system **SHALL** include explicit caution instruction in the prompt: "※ 종토방이 과열 상태입니다. 개인투자자 쏠림에 의한 고점 가능성을 고려하세요".

### REQ-SENTIMENT-004 (Event-Driven)
**WHEN** `volume_surge` is True in the forum sentiment result, **THEN** the system **SHALL** include the following notice in the prompt: "※ 종토방 댓글 급증 감지: 시장 관심도 급등. 공시/뉴스와 교차 확인 필요".

### REQ-SENTIMENT-005 (Ubiquitous)
The system **SHALL** include `_gather_securities_consensus()` result in the AI prompt under section "## 9-1. 증권사 컨센서스" showing `avg_target_price`, `premium_pct`, `consensus_signal`, and opinion ratios (buy/hold/sell ratios).

### REQ-SENTIMENT-006 (Event-Driven / Graceful Fallback)
**WHEN** forum data is not available (SPEC-AI-008 not deployed, table missing, or no data for the stock), **THEN** the system **SHALL** gracefully skip the forum sentiment section without raising any exception and continue producing the analysis.

### REQ-SENTIMENT-007 (State-Driven)
**WHEN** `consensus_signal` is `"strong_buy"`, **THEN** the system **SHALL** include a positive note in the prompt indicating strong analyst consensus. **WHEN** `consensus_signal` is `"caution"`, **THEN** the system **SHALL** include a warning note indicating analyst caution.

### REQ-SENTIMENT-008 (Unwanted)
The system **SHALL NOT** use forum sentiment as a standalone buy/sell signal. Forum sentiment **MUST** always be presented in the prompt as supporting context alongside news sentiment and market data, never as a primary decision driver.

## Exclusions (What NOT to Build)

- 기존 뉴스 센티먼트 로직(`_gather_sentiment_trend`) 교체 또는 수정 — 유지 원칙
- 신규 DB 테이블 생성 — SPEC-AI-008 및 SPEC-AI-009의 산출물만 소비
- `FundSignal` 모델 스키마 변경 — signal_type 등 컬럼 추가 금지
- Frontend/API 엔드포인트 추가 또는 변경 — 백엔드 분석 로직 전용
- 종토방 센티먼트를 독립 매수/매도 신호로 승격하는 로직
- 가중치/파라미터의 설정 파일 외부화 (하드코딩 상수로 충분)

## Non-Functional Constraints

- **Performance**: `analyze_stock()` 실행 시간은 기준선 대비 500ms 이내 증가
- **Reliability**: 선행 SPEC 미배포 시에도 무장애 동작 (graceful fallback)
- **Observability**: 각 신호 채널(뉴스/종토방/컨센서스)의 존재 여부를 로그로 기록
- **Backward Compatibility**: 기존 프롬프트의 섹션 1-1, 9는 변경되지 않음
