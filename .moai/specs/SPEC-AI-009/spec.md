---
id: SPEC-AI-009
version: 1.0.0
status: draft
created: 2026-04-14
updated: 2026-04-14
author: Nexsol
priority: Medium
issue_number: 0
---

# SPEC-AI-009: 증권사 컨센서스 목표주가 집계 및 fund_manager 통합

## HISTORY

- v1.0.0 (2026-04-14): 초기 SPEC 작성 - 기존 SecuritiesReport 데이터를 기반으로 컨센서스 목표주가 집계 기능 설계

## 개요 (Overview)

NewsHive의 `fund_manager.analyze_stock()` 함수는 현재 종목별 증권사 리포트를 최근 14일 이내 최대 5건만 조회하여 AI 프롬프트에 전달합니다. 본 SPEC은 동일한 `SecuritiesReport` 테이블에서 최근 90일 데이터를 집계하여 **컨센서스 목표주가**, **매수/중립/매도 비율**, **목표주가 프리미엄**, **추세**를 계산하고 AI 프롬프트의 독립 섹션으로 통합합니다.

신규 크롤러나 DB 테이블 없이 기존 데이터를 활용하여 AI 분석 품질을 향상시키는 것이 핵심 목표입니다.

## 배경 및 동기 (Background & Motivation)

- 기존 `_gather_securities_reports()`는 단순 나열 형태로 AI에 전달되어, 다수 리포트의 **통계적 컨센서스**를 AI가 직접 계산해야 함
- 증권사 컨센서스는 기관 수급 및 시장 기대치의 중요 지표이며, 집계된 형태가 AI 분석에 훨씬 유용함
- 데이터는 이미 `securities_report_crawler.py`가 수집 중이므로 추가 인프라 없이 즉시 구현 가능

## 요구사항 (EARS Format Requirements)

### Ubiquitous Requirements

- **REQ-CONSENSUS-001**: The system **shall** aggregate `target_price` from `SecuritiesReport` within last 90 days per stock (expanding from current 14-day window).
- **REQ-CONSENSUS-002**: The system **shall** compute `avg_target_price`, `median_target_price`, `min_target`, `max_target` from reports with non-null `target_price`.
- **REQ-CONSENSUS-003**: The system **shall** compute `buy_ratio`, `hold_ratio`, `sell_ratio` from the `opinion` field (매수/비중확대 → buy, 중립/보유 → hold, 매도/비중축소 → sell).
- **REQ-CONSENSUS-004**: The system **shall** compute `premium_pct = (avg_target_price - current_price) / current_price * 100`.
- **REQ-CONSENSUS-007**: The system **shall** compute `target_price_trend` by comparing `avg_target_price` of reports from last 30 days vs 31-90 days (rising / falling / stable).
- **REQ-CONSENSUS-008**: The system **shall** include a consensus summary in the `analyze_stock()` AI prompt as a dedicated section.

### Event-Driven Requirements

- **REQ-CONSENSUS-005**: **When** `report_count >= 3` **and** `buy_ratio >= 0.7` **and** `premium_pct >= 15`, **then** the system **shall** set `consensus_signal = "strong_buy"`.
- **REQ-CONSENSUS-006**: **When** `sell_ratio >= 0.5` **or** `premium_pct < 0`, **then** the system **shall** set `consensus_signal = "caution"`.

## Exclusions (What NOT to Build)

- 신규 웹 크롤러 또는 스크래퍼 개발 (데이터는 이미 `securities_report_crawler.py`가 수집 중)
- 실시간 컨센서스 외부 API 연동 (네이버/한경/에프앤가이드 등)
- 컨센서스 결과를 별도 DB 테이블에 저장 (기존 `SecuritiesReport`에서 on-the-fly 계산)
- ETF / 펀드에 대한 가격 컨센서스 (주식 종목만 지원)
- 과거 컨센서스 추적 히스토리 관리 (현재 시점 스냅샷만 제공)
- 증권사별 가중치 또는 신뢰도 시스템 (모든 리포트 동일 가중치)

## 제약사항 (Constraints)

- **데이터 소스**: `backend/app/models/securities_report.py`의 `SecuritiesReport` 테이블만 사용
- **집계 윈도우**: 최근 90일 (현재 14일 윈도우에서 확장)
- **Opinion 매핑**: 한국어 원문 opinion 필드 기준 분류
  - Buy: "매수", "비중확대", "Strong Buy", "Buy"
  - Hold: "중립", "보유", "Neutral", "Hold"
  - Sell: "매도", "비중축소", "Sell"
- **Null 처리**: `target_price`가 `None`인 리포트는 목표주가 집계에서 제외하되 opinion 비율에는 포함
- **최소 샘플**: `report_count < 3`인 경우 `consensus_signal = "insufficient"`

## 성공 기준 (Success Criteria)

- `_gather_securities_consensus()` 함수가 모든 acceptance 시나리오를 통과
- `analyze_stock()` AI 프롬프트에 `## 9-1. 증권사 컨센서스` 섹션이 포함됨
- 기존 `_gather_securities_reports()`의 14일 윈도우 동작에는 영향 없음
- 프롬프트 토큰 증가량이 종목당 평균 200 토큰 이하로 제한됨

## 관련 SPEC

- SPEC-AI-003 (선행 기술 탐지기): 유사하게 `fund_manager.py`에서 기술 지표를 집계하여 프롬프트에 통합한 패턴 참조
- SPEC-AI-004 (공시 기반 선제적 시그널): `analyze_stock()` 프롬프트 확장 패턴 참조
