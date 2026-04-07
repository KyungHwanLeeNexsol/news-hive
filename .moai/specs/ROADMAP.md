---
project: NewsHive
version: "2.0.0"
created: "2026-03-26"
updated: "2026-03-29"
author: MoAI
---

# NewsHive Enhancement Roadmap

## Overview

NewsHive has completed Phase 1-5 (core implementation) plus 7 extended feature phases.
This roadmap defines the systematic enhancement strategy across 5 tiers (0-4).

## Current State

| Metric | Value |
|--------|-------|
| Backend Files | 60+ Python files |
| Frontend Pages | 12 pages (+/chat) |
| DB Migrations | 16 applied |
| Scheduler Jobs | 15 active (with retry) |
| Test Coverage | ~60% (650+ tests) |
| Deployment | Oracle Cloud (BE) + Vercel (FE) |
| Infrastructure | Redis cache, WebSocket, Prometheus, CI/CD |
| Known Bugs | 1 (news_crawler.py classify_sentiment shadowing) |

## SPEC Registry

### TIER 0: Top Priority Features (Priority: Highest)

| SPEC ID | Title | Status | Dependencies |
|---------|-------|--------|--------------|
| SPEC-COMMODITY-001 | Commodity Price Tracking System | completed | none |
| SPEC-COMMODITY-002 | Commodity Newsroom | completed | SPEC-COMMODITY-001 |

### TIER 1: Stability & Quality (Priority: Critical)

| SPEC ID | Title | Status | Dependencies |
|---------|-------|--------|--------------|
| SPEC-TEST-001 | Test Infrastructure & Core Tests | completed | none |
| SPEC-FIX-001 | Code Quality Improvement | completed | none |

### TIER 2: Architecture (Priority: High)

| SPEC ID | Title | Status | Dependencies |
|---------|-------|--------|--------------|
| SPEC-CACHE-001 | Redis Caching Layer & Rate Limiting | completed | SPEC-FIX-001 |
| SPEC-REALTIME-001 | Real-time Notifications & CI/CD | completed | SPEC-TEST-001 |

### TIER 3: Feature Enhancement (Priority: Medium)

| SPEC ID | Title | Status | Dependencies |
|---------|-------|--------|--------------|
| SPEC-AUTH-001 | User Authentication & Personalization | draft | SPEC-CACHE-001 |
| SPEC-VIZ-001 | Visualization & AI Chat | completed | SPEC-AUTH-001 |

### TIER 4: Scale & Expansion (Priority: Low)

| SPEC ID | Title | Status | Dependencies |
|---------|-------|--------|--------------|
| SPEC-SCALE-001 | Scalability Infrastructure | completed | SPEC-CACHE-001, SPEC-TEST-001 |

### TIER 5: AI Enhancement (Priority: High)

| SPEC ID | Title | Status | Dependencies |
|---------|-------|--------|--------------|
| SPEC-AI-001 | AI Fund Prediction Enhancement Master | completed | none |
| SPEC-AI-002 | AI Fund Prediction Phase 2 | completed | SPEC-AI-001 |
| SPEC-AI-003 | Pre-emptive Buy Signal Detection | completed | SPEC-AI-002 |
| SPEC-AI-004 | Disclosure-Based Pre-emptive Signal | completed | SPEC-AI-003 |
| SPEC-AI-005 | Dynamic Target Price / Stop Loss | completed | SPEC-AI-004 |

### TIER 6: Self-Learning (Priority: Medium — 데이터 수집 후 진행)

| SPEC ID | Title | Status | Dependencies | Trigger Condition |
|---------|-------|--------|--------------|-------------------|
| SPEC-AI-006 | TP/SL Parameter Auto-Tuning | planned | SPEC-AI-005 | 종료 거래 100건+ 달성 시 |

**SPEC-AI-006 로드맵**:

- **현재 (2026-04-05~)**: 데이터 수집 단계. SPEC-AI-005 동적 TP/SL 시스템 운영 중. `/api/paper-trading/tp-sl-backtest` API로 수동 검증 가능
- **1차 검증 (50건+ 종료 거래)**: 고정 vs 동적 방식 승률/수익률 비교. ATR 배수(2.0/1.5)가 부적합하면 수동 조정
- **2차 자가 학습 구현 (100건+)**: 주간 배치로 최적 ATR 배수 자동 계산, 섹터별/신뢰도별 파라미터 학습, 변경 폭 제한 및 롤백 안전장치 포함

**설계 원칙**: 데이터 없이 자가 학습 로직을 만들지 않는다. 충분한 샘플이 확보된 후 통계적으로 유의미한 개선만 적용한다.

### TIER 7: Investment Tracking (Priority: High)

| SPEC ID | Title | Status | Dependencies |
|---------|-------|--------|--------------|
| SPEC-FOLLOW-001 | Company Following System (기업 팔로잉) | planned | SPEC-AUTH-001 |
| SPEC-FOLLOW-002 | Securities Report Collection and Keyword Notification | planned | SPEC-FOLLOW-001 |

**SPEC-FOLLOW-002 개요**:

네이버 금융 리서치의 종목분석 리포트를 주기적으로 수집하여 DB에 저장하고, 기존 SPEC-FOLLOW-001 키워드 매처가 뉴스/공시와 동일한 방식으로 리포트에 대해서도 텔레그램/Web Push 알림을 발송하도록 확장한다.

- **신규 모델**: `SecuritiesReport` (title, company_name, stock_id, securities_firm, opinion, target_price, url, published_at)
- **신규 크롤러**: `securities_report_crawler.py` (네이버 리서치 종목분석 페이지, dart_crawler 패턴 재사용)
- **확장**: `keyword_matcher.match_keywords_and_notify()` 에 `content_type="report"` 루프 추가 (스키마는 이미 지원)
- **DB 마이그레이션**: `041_spec_follow_002_securities_reports.py`
- **프론트엔드 변경 없음**: 기존 텔레그램/Web Push 알림 채널 100% 재사용

**SPEC-FOLLOW-001 개요**:

사용자가 종목을 팔로잉하면 AI가 핵심 키워드를 자동 생성하고, 뉴스/공시에서 키워드 매칭 시 텔레그램 알림을 발송하는 시스템.

- **핵심 기능**: 종목 팔로잉, AI 키워드 생성 (4카테고리), 키워드 매칭 알림, 텔레그램 봇 연동
- **신규 인프라**: 텔레그램 Bot API 연동, 키워드 매칭 스케줄러
- **기존 활용**: JWT 인증, Stock DB, 뉴스/공시 크롤러, ask_ai() 다중 프로바이더

## Execution Order

```
Phase 0: SPEC-COMMODITY-001 -> SPEC-COMMODITY-002  ✅ COMPLETED
Phase 1: SPEC-TEST-001 + SPEC-FIX-001              ✅ COMPLETED (2026-03-29)
Phase 2: SPEC-CACHE-001 + SPEC-REALTIME-001         ✅ COMPLETED (2026-03-29)
Phase 3: SPEC-AUTH-001 -> SPEC-VIZ-001              ⚠️ AUTH pending, VIZ completed (2026-03-29)
Phase 4: SPEC-SCALE-001                             ✅ COMPLETED (2026-03-29)
Phase 5: SPEC-AI-001~005                            ✅ COMPLETED (2026-04-05)
Phase 6: SPEC-AI-006                                ⏳ PLANNED (100건+ 거래 데이터 확보 후)
Phase 7: SPEC-FOLLOW-001                             ⏳ PLANNED
```

## Usage

To implement any SPEC:
1. `/moai plan SPEC-XXX` - Detail the SPEC with deep research
2. `/moai run SPEC-XXX` - Implement using DDD methodology
3. `/moai sync SPEC-XXX` - Generate docs and PR
