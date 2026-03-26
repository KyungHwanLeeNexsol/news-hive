---
id: SPEC-FIX-001
version: "0.1.0"
status: draft
created: "2026-03-26"
updated: "2026-03-26"
author: MoAI
priority: critical
tier: 1
issue_number: 0
---

# SPEC-FIX-001: Code Quality Improvement

## HISTORY

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1.0 | 2026-03-26 | MoAI | Initial draft from roadmap analysis |

---

## 1. Overview

Fix known bugs, optimize database query patterns, and externalize hardcoded configuration values across the NewsHive backend.

### 1.1 Background

- fund_manager.py has a variable name bug (`matched_stocks` vs `matched`) causing potential NameError
- N+1 query patterns in fund_manager router (lines 45-74) load stock/sector per signal individually
- 20+ magic numbers scattered across services (query budgets, risk thresholds, cache TTLs, window sizes)
- No consistent error recovery pattern (some services silently fail, others crash)

### 1.2 Goals

- Fix all known bugs with reproduction tests
- Eliminate N+1 query patterns using SQLAlchemy eager loading
- Externalize all configuration constants to config.py or dedicated constants module
- Establish circuit breaker pattern for external API calls

---

## 2. Environment

### 2.1 System

- **Backend**: Python 3.11+ / FastAPI / SQLAlchemy 2.0
- **Database**: PostgreSQL 16
- **Affected Files**: fund_manager.py (service + router), news_crawler.py, macro_risk.py, scheduler.py, ai_classifier.py

### 2.2 Constraints

- All changes must preserve existing behavior (DDD approach)
- No new dependencies unless strictly necessary
- API response format must not change (backward compatible)

---

## 3. Requirements (EARS Format)

### Module 1: Bug Fixes

**REQ-FIX-001 [Ubiquitous]**
The fund_manager service SHALL use the correct variable name `matched` (not `matched_stocks`) at line ~1069 for signal generation logging.

**REQ-FIX-002 [Ubiquitous]**
A reproduction test SHALL be written for each bug fix that fails before the fix and passes after.

### Module 2: N+1 Query Optimization

**REQ-FIX-003 [Ubiquitous]**
The fund_manager router SHALL use SQLAlchemy `selectinload()` or `joinedload()` to eagerly load Stock and Sector relationships when querying FundSignal records.

**REQ-FIX-004 [Ubiquitous]**
The news router SHALL use eager loading for NewsArticle -> NewsStockRelation -> Stock/Sector relationships in list endpoints.

**REQ-FIX-005 [State-driven]**
WHEN loading 100+ records with relationships, the query count SHALL NOT exceed N+2 (1 base query + 1 per eager-loaded relationship).

### Module 3: Configuration Externalization

**REQ-FIX-006 [Ubiquitous]**
All magic numbers in news_crawler.py SHALL be moved to config.py as configurable environment variables with sensible defaults:
- MAX_TOTAL_QUERIES (default: 60)
- MAX_STOCK_QUERIES (default: 20)
- TITLE_SIMILARITY_THRESHOLD (default: 0.5)
- MAX_ARTICLES_PER_SOURCE (default: 100)

**REQ-FIX-007 [Ubiquitous]**
All magic numbers in macro_risk.py SHALL be moved to config.py:
- MACRO_RISK_WINDOW_HOURS (default: 1)
- MACRO_RISK_WARNING_THRESHOLD (default: 3)
- MACRO_RISK_CRITICAL_THRESHOLD (default: 7)
- MACRO_RISK_COOLDOWN_HOURS (default: 6)

**REQ-FIX-008 [Ubiquitous]**
All cache TTL values in naver_finance.py and kis_api.py SHALL be externalized:
- PRICE_CACHE_TTL_SECONDS (default: 300)
- FINANCIAL_CACHE_TTL_SECONDS (default: 86400)
- KIS_TOKEN_REFRESH_MARGIN_SECONDS (default: 3600)

**REQ-FIX-009 [Ubiquitous]**
All scheduler intervals SHALL reference config.py values, not hardcoded cron expressions.

### Module 4: Error Resilience

**REQ-FIX-010 [Event-driven]**
WHEN an external API call (Naver, KIS, DART, Gemini, Groq) fails 3 consecutive times, the system SHALL log a warning and skip that provider for the current cycle instead of retrying indefinitely.

**REQ-FIX-011 [Event-driven]**
WHEN KIS API token refresh is called concurrently, the system SHALL use a lock to prevent race conditions and duplicate token requests.

---

## 4. Technical Approach

### 4.1 Bug Fix Process (per CLAUDE.md Rule 4)
1. Write reproduction test -> verify it fails
2. Apply minimal fix
3. Verify test passes

### 4.2 N+1 Fix Pattern
```python
# Before (N+1)
signals = db.query(FundSignal).all()
for s in signals:
    stock = db.query(Stock).get(s.stock_id)  # N queries

# After (eager)
signals = db.query(FundSignal).options(
    selectinload(FundSignal.stock).selectinload(Stock.sector)
).all()
```

### 4.3 Config Externalization Pattern
- Add new fields to Settings class in config.py with env var mapping
- Update .env.example with new variables and defaults
- Replace hardcoded values with settings.VARIABLE_NAME

---

## 5. Acceptance Criteria Summary

| Scenario | Criteria |
|----------|----------|
| Bug fix | fund_manager.py variable typo fixed, reproduction test passes |
| N+1 elimination | fund_manager + news router use eager loading, query count verified |
| Config externalization | All magic numbers in config.py, .env.example updated |
| Error resilience | 3-retry circuit breaker on external APIs, KIS token lock |
| Backward compatibility | All existing API responses unchanged |
