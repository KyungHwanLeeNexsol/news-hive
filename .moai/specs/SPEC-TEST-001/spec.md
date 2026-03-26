---
id: SPEC-TEST-001
version: "0.1.0"
status: draft
created: "2026-03-26"
updated: "2026-03-26"
author: MoAI
priority: critical
tier: 1
issue_number: 0
---

# SPEC-TEST-001: Test Infrastructure & Core Service Tests

## HISTORY

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1.0 | 2026-03-26 | MoAI | Initial draft from roadmap analysis |

---

## 1. Overview

Build a comprehensive pytest test suite from scratch for the NewsHive backend. Current test coverage is 0%, creating significant risk for a production application with 9 scheduled jobs, 50+ Python files, and external API integrations.

### 1.1 Background

- NewsHive backend has 0% test coverage despite being in production
- 15+ external API integrations (Naver, KIS, DART, Gemini, Groq) need mocking
- 9 APScheduler jobs run 24/7 with no automated verification
- fund_manager.py alone is 2000+ LOC with complex AI-driven logic
- SPEC-NEWS-001 defined acceptance criteria but no permanent test suite exists

### 1.2 Goals

- Establish pytest infrastructure with fixtures, factories, and mocking patterns
- Achieve 85%+ coverage on critical services (news_crawler, ai_classifier, fund_manager)
- Create integration tests for API routers
- Set up test database with migrations
- Enable CI-ready test execution

---

## 2. Environment

### 2.1 System

- **Runtime**: Python 3.11+ / pytest 8.x
- **Backend**: FastAPI / SQLAlchemy 2.0 (async)
- **Database**: PostgreSQL 16 (test instance via docker-compose or testcontainers)
- **External APIs**: Naver Search, KIS, DART, Gemini, Groq, Naver Finance

### 2.2 Constraints

- Tests must not call real external APIs (all mocked)
- Test DB must be isolated from development DB
- Tests must complete within 5 minutes for CI feasibility
- Async test support required (pytest-asyncio)

---

## 3. Assumptions

- A1: pytest-asyncio is compatible with SQLAlchemy async sessions
- A2: All external API responses can be captured and replayed as fixtures
- A3: APScheduler jobs can be tested by invoking their handler functions directly
- A4: Factory Boy or similar can generate realistic test data for Korean stock/news domain

---

## 4. Requirements (EARS Format)

### Module 1: Test Infrastructure

**REQ-TST-001 [Ubiquitous]**
The test suite SHALL use pytest as the test runner with pytest-asyncio for async support.

**REQ-TST-002 [Ubiquitous]**
The test suite SHALL provide a shared database fixture that creates a test PostgreSQL database, runs all Alembic migrations, and tears down after the test session.

**REQ-TST-003 [Ubiquitous]**
The test suite SHALL provide factory functions for creating Sector, Stock, NewsArticle, NewsStockRelation, and all other model instances with realistic Korean market data.

**REQ-TST-004 [Ubiquitous]**
The test suite SHALL mock all external HTTP calls (Naver API, KIS API, DART, Gemini, Groq, Naver Finance scraping) using pytest fixtures with recorded response data.

**REQ-TST-005 [Ubiquitous]**
The test suite SHALL include a FastAPI TestClient fixture for integration testing of all routers.

### Module 2: Service Unit Tests

**REQ-TST-006 [Ubiquitous]**
The test suite SHALL test news_crawler.py including: multi-source orchestration, URL deduplication, title similarity detection (bigram Jaccard), query budget management, and round-robin stock selection.

**REQ-TST-007 [Ubiquitous]**
The test suite SHALL test ai_classifier.py including: keyword index building, sentiment classification, non-financial article filtering (74 patterns), keyword extraction, and batch translation.

**REQ-TST-008 [Ubiquitous]**
The test suite SHALL test fund_manager.py including: daily briefing generation, signal creation, portfolio analysis, accuracy calculation, and data enrichment pipeline.

**REQ-TST-009 [Ubiquitous]**
The test suite SHALL test news_price_impact_service.py including: snapshot capture, 1D/5D backfill, return calculation, and 30-day statistics aggregation.

**REQ-TST-010 [Ubiquitous]**
The test suite SHALL test macro_risk.py including: keyword detection, sliding window logic, threshold escalation (warning/critical), cooldown deduplication, and positive context filtering.

### Module 3: Router Integration Tests

**REQ-TST-011 [Ubiquitous]**
The test suite SHALL test all sector router endpoints: GET /api/sectors, POST /api/sectors, GET /api/sectors/{id}, DELETE /api/sectors/{id}, GET /api/sectors/{id}/news.

**REQ-TST-012 [Ubiquitous]**
The test suite SHALL test all stock router endpoints including real-time price enrichment, technical analysis, financial analysis, and news impact stats.

**REQ-TST-013 [Ubiquitous]**
The test suite SHALL test all news router endpoints including search, filtering, pagination, and manual refresh trigger.

**REQ-TST-014 [Ubiquitous]**
The test suite SHALL test fund_manager router endpoints with admin authentication (token validation, unauthorized access rejection).

### Module 4: Scheduler Tests

**REQ-TST-015 [Ubiquitous]**
The test suite SHALL test each of the 9 scheduler job handler functions in isolation, verifying they call the correct service functions with expected parameters.

### Module 5: Coverage & CI

**REQ-TST-016 [Ubiquitous]**
The test suite SHALL achieve minimum 85% line coverage across all services/ and routers/ directories.

**REQ-TST-017 [State-driven]**
WHILE test coverage is below 85%, the CI pipeline SHALL block merges to the main branch.

---

## 5. Technical Approach

### 5.1 Directory Structure

```
backend/
  tests/
    conftest.py          # Shared fixtures (DB, client, factories)
    factories.py         # Model factories
    fixtures/            # Recorded API responses (JSON)
    test_services/
      test_news_crawler.py
      test_ai_classifier.py
      test_fund_manager.py
      test_news_price_impact.py
      test_macro_risk.py
      test_scheduler.py
    test_routers/
      test_sectors.py
      test_stocks.py
      test_news.py
      test_fund_manager.py
      test_disclosures.py
    test_models/
      test_relationships.py
```

### 5.2 Key Dependencies

- pytest, pytest-asyncio, pytest-cov
- httpx (AsyncClient for FastAPI testing)
- factory-boy or polyfactory
- freezegun (time manipulation for scheduler tests)
- respx or pytest-httpx (HTTP mocking)

### 5.3 Estimated Effort

- Infrastructure setup: 1 day
- Service tests (5 services): 3 days
- Router tests (5 routers): 2 days
- Scheduler tests: 0.5 day
- CI integration: 0.5 day

---

## 6. Acceptance Criteria Summary

| Scenario | Criteria |
|----------|----------|
| Test infrastructure | pytest runs, DB fixture works, factories produce valid data |
| Service coverage | 85%+ on news_crawler, ai_classifier, fund_manager, news_price_impact, macro_risk |
| Router coverage | All endpoints tested with success and error cases |
| Scheduler coverage | All 9 job handlers tested |
| External API isolation | Zero real API calls during test execution |
| CI readiness | Tests complete within 5 minutes, coverage report generated |
