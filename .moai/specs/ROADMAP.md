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

## Execution Order

```
Phase 0: SPEC-COMMODITY-001 -> SPEC-COMMODITY-002  ✅ COMPLETED
Phase 1: SPEC-TEST-001 + SPEC-FIX-001              ✅ COMPLETED (2026-03-29)
Phase 2: SPEC-CACHE-001 + SPEC-REALTIME-001         ✅ COMPLETED (2026-03-29)
Phase 3: SPEC-AUTH-001 -> SPEC-VIZ-001              ⚠️ AUTH pending, VIZ completed (2026-03-29)
Phase 4: SPEC-SCALE-001                             ✅ COMPLETED (2026-03-29, APScheduler改善 approach)
```

## Usage

To implement any SPEC:
1. `/moai plan SPEC-XXX` - Detail the SPEC with deep research
2. `/moai run SPEC-XXX` - Implement using DDD methodology
3. `/moai sync SPEC-XXX` - Generate docs and PR
