---
id: SPEC-SCALE-001
version: "0.1.0"
status: completed
created: "2026-03-26"
updated: "2026-03-29"
author: MoAI
priority: low
tier: 4
issue_number: 0
---

# SPEC-SCALE-001: Scalability Infrastructure

## HISTORY

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1.0 | 2026-03-26 | MoAI | Initial draft from roadmap analysis |

---

## 1. Overview

Migrate background job processing to Celery for distributed execution, add comprehensive monitoring, support international markets, and prepare for mobile app delivery.

### 1.1 Background

- APScheduler runs all 9 jobs in a single process — no horizontal scaling
- No observability: no metrics, no alerting, no performance dashboards
- Only Korean stock market (KOSPI/KOSDAQ) supported
- Web-only access, no native mobile experience
- Oracle Cloud VM has limited resources (1 CPU, 1GB RAM)

### 1.2 Goals

- Celery + Redis for distributed task queue (replace APScheduler)
- Prometheus + Grafana monitoring stack
- US stock market support (NYSE, NASDAQ) via Yahoo Finance / Alpha Vantage
- Progressive Web App (PWA) for mobile access

---

## 2. Requirements (EARS Format)

### Module 1: Celery Task Queue

**REQ-SCALE-001 [Ubiquitous]**
The system SHALL replace APScheduler with Celery Beat for job scheduling and Celery Workers for task execution.

**REQ-SCALE-002 [Ubiquitous]**
Each of the 9 current scheduler jobs SHALL be migrated to individual Celery tasks with retry policies and dead letter queues.

**REQ-SCALE-003 [Ubiquitous]**
The Celery worker SHALL support horizontal scaling — running N workers across M processes.

**REQ-SCALE-004 [Event-driven]**
WHEN a Celery task fails after 3 retries, the system SHALL log the failure to a dead letter queue and send an alert via monitoring.

### Module 2: Monitoring & Observability

**REQ-SCALE-005 [Ubiquitous]**
The system SHALL expose Prometheus metrics at `/metrics` including: request count/latency, cache hit rate, crawl success/failure, task queue depth, active WebSocket connections.

**REQ-SCALE-006 [Ubiquitous]**
A Grafana dashboard SHALL visualize: API latency (p50/p95/p99), news crawl volume, AI classification rate, signal accuracy over time, system resource usage.

**REQ-SCALE-007 [Event-driven]**
WHEN API p95 latency exceeds 2 seconds or crawl failure rate exceeds 30%, the system SHALL trigger an alert (email or Slack webhook).

**REQ-SCALE-008 [Ubiquitous]**
Application logs SHALL be structured (JSON format) with correlation IDs for request tracing.

### Module 3: International Market Support

**REQ-SCALE-009 [Ubiquitous]**
The Stock model SHALL support a `market` field with values: KOSPI, KOSDAQ, NYSE, NASDAQ, with market-specific behavior (timezone, trading hours, currency).

**REQ-SCALE-010 [Ubiquitous]**
The news crawler SHALL support English-language sources (Yahoo Finance, Reuters, Bloomberg RSS) for US market stocks.

**REQ-SCALE-011 [Ubiquitous]**
The AI classifier SHALL handle bilingual classification (Korean + English articles) mapped to the correct market/sector.

**REQ-SCALE-012 [Ubiquitous]**
The frontend SHALL display prices in appropriate currency (KRW for Korean, USD for US) with currency indicator.

### Module 4: Progressive Web App

**REQ-SCALE-013 [Ubiquitous]**
The Next.js frontend SHALL be configured as a PWA with: service worker, web manifest, offline-capable shell, and install prompt.

**REQ-SCALE-014 [Ubiquitous]**
The PWA SHALL cache the dashboard, watchlist, and last-fetched news for offline access.

**REQ-SCALE-015 [Event-driven]**
WHEN the PWA detects network recovery after offline mode, the system SHALL sync cached watchlist changes and refresh data.

---

## 3. Technical Approach

### 3.1 Celery Stack
- Celery 5.x + Redis broker (reuses SPEC-CACHE-001 Redis)
- celery-beat for scheduling
- Flower for task monitoring dashboard

### 3.2 Monitoring Stack
- prometheus-fastapi-instrumentator (auto metrics)
- Grafana Cloud (free tier: 10K metrics, 50GB logs)
- Structured logging via python-json-logger

### 3.3 International Markets
- yfinance (Yahoo Finance) for US stock data
- Alpha Vantage (free tier: 25 req/day) for historical data
- Market-specific crawl schedules (KST for Korean, EST for US)

### 3.4 PWA
- next-pwa plugin
- Service worker for caching strategy (network-first for API, cache-first for assets)
- Web manifest for installability

---

## 4. Acceptance Criteria Summary

| Scenario | Criteria |
|----------|----------|
| Celery migration | All 9 jobs run via Celery, APScheduler removed |
| Horizontal scaling | 2 workers process tasks concurrently |
| Metrics endpoint | /metrics returns Prometheus format data |
| Grafana dashboard | Visualizes latency, crawl rate, signal accuracy |
| Alert trigger | Latency spike sends notification |
| US stock support | NYSE/NASDAQ stocks with English news |
| PWA install | App installable on mobile, works offline |
| Offline sync | Watchlist syncs on network recovery |
