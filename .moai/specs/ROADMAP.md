---
project: NewsHive
version: "2.0.0"
created: "2026-03-26"
updated: "2026-03-26"
author: MoAI
---

# NewsHive Enhancement Roadmap

## Overview

NewsHive has completed Phase 1-5 (core implementation) plus 7 extended feature phases.
This roadmap defines the systematic enhancement strategy across 5 tiers (0-4).

## Current State

| Metric | Value |
|--------|-------|
| Backend Files | 50+ Python files |
| Frontend Pages | 11 pages |
| DB Migrations | 16 applied |
| Scheduler Jobs | 9 active |
| Test Coverage | ~10% (116 tests, infrastructure built) |
| Deployment | Oracle Cloud (BE) + Vercel (FE) |
| Known Bugs | 2 (fund_manager.py typo, news_crawler.py existing_urls) |

## SPEC Registry

### TIER 0: Top Priority Features (Priority: Highest)

| SPEC ID | Title | Status | Dependencies |
|---------|-------|--------|--------------|
| SPEC-COMMODITY-001 | Commodity Price Tracking System | draft | none |
| SPEC-COMMODITY-002 | Commodity Newsroom | draft | SPEC-COMMODITY-001 |

### TIER 1: Stability & Quality (Priority: Critical)

| SPEC ID | Title | Status | Dependencies |
|---------|-------|--------|--------------|
| SPEC-TEST-001 | Test Infrastructure & Core Tests | in_progress | none |
| SPEC-FIX-001 | Code Quality Improvement | draft | none |

### TIER 2: Architecture (Priority: High)

| SPEC ID | Title | Status | Dependencies |
|---------|-------|--------|--------------|
| SPEC-CACHE-001 | Redis Caching Layer & Rate Limiting | draft | SPEC-FIX-001 |
| SPEC-REALTIME-001 | Real-time Notifications & CI/CD | draft | SPEC-TEST-001 |

### TIER 3: Feature Enhancement (Priority: Medium)

| SPEC ID | Title | Status | Dependencies |
|---------|-------|--------|--------------|
| SPEC-AUTH-001 | User Authentication & Personalization | draft | SPEC-CACHE-001 |
| SPEC-VIZ-001 | Visualization & AI Chat | draft | SPEC-AUTH-001 |

### TIER 4: Scale & Expansion (Priority: Low)

| SPEC ID | Title | Status | Dependencies |
|---------|-------|--------|--------------|
| SPEC-SCALE-001 | Scalability Infrastructure | draft | SPEC-CACHE-001, SPEC-TEST-001 |

## Execution Order

```
Phase 0 (Week 1-3):  SPEC-COMMODITY-001 -> SPEC-COMMODITY-002  (sequential, top priority)
Phase 1 (Week 2-4):  SPEC-TEST-001 + SPEC-FIX-001  (parallel, can overlap with Phase 0)
Phase 2 (Week 5-6):  SPEC-CACHE-001 + SPEC-REALTIME-001  (parallel, after Phase 1)
Phase 3 (Week 7-10): SPEC-AUTH-001 -> SPEC-VIZ-001  (sequential)
Phase 4 (Week 11-14): SPEC-SCALE-001  (after Phase 2)
```

## Usage

To implement any SPEC:
1. `/moai plan SPEC-XXX` - Detail the SPEC with deep research
2. `/moai run SPEC-XXX` - Implement using DDD methodology
3. `/moai sync SPEC-XXX` - Generate docs and PR
