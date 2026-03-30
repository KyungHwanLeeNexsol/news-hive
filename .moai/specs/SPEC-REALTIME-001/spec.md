---
id: SPEC-REALTIME-001
version: "0.1.0"
status: completed
created: "2026-03-26"
updated: "2026-03-29"
author: MoAI
priority: high
tier: 2
issue_number: 0
---

# SPEC-REALTIME-001: Real-time Notifications & CI/CD Pipeline

## HISTORY

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1.0 | 2026-03-26 | MoAI | Initial draft from roadmap analysis |

---

## 1. Overview

Replace polling-based updates with WebSocket real-time notifications and establish a CI/CD pipeline for automated testing and deployment.

### 1.1 Background

- Frontend polls every 15 seconds during market hours, 5 minutes otherwise
- Macro risk alerts have up to 15-second delay before user sees them
- New investment signals and daily briefings are not pushed to users
- No CI/CD pipeline: deployment is manual via GitHub webhook, no automated testing
- Frontend uses props drilling for state; complex pages (fund, stocks) are hard to maintain

### 1.2 Goals

- WebSocket connection for instant push notifications (alerts, signals, news)
- GitHub Actions CI pipeline with pytest + linting + type checking
- Frontend state management migration (Zustand or React Context)
- Automated deployment with test gate

---

## 2. Requirements (EARS Format)

### Module 1: WebSocket Server

**REQ-RT-001 [Ubiquitous]**
The backend SHALL provide a WebSocket endpoint at `/ws` using FastAPI's WebSocket support.

**REQ-RT-002 [Ubiquitous]**
The WebSocket server SHALL support topic-based subscriptions: `alerts`, `signals`, `news`, `prices`.

**REQ-RT-003 [Event-driven]**
WHEN a new MacroAlert is created with level "critical", the system SHALL broadcast to all `alerts` subscribers within 1 second.

**REQ-RT-004 [Event-driven]**
WHEN a new FundSignal is generated, the system SHALL push to all `signals` subscribers.

**REQ-RT-005 [Event-driven]**
WHEN new news articles are classified and stored, the system SHALL push article count and latest titles to `news` subscribers.

**REQ-RT-006 [State-driven]**
WHILE no WebSocket connection is active, the frontend SHALL fall back to the existing polling mechanism.

### Module 2: Frontend State Management

**REQ-RT-007 [Ubiquitous]**
The frontend SHALL use Zustand for global state management, replacing prop drilling patterns in complex pages.

**REQ-RT-008 [Ubiquitous]**
Shared state stores SHALL include: watchlistStore, alertStore, newsStore, priceStore.

**REQ-RT-009 [Ubiquitous]**
The WebSocket connection SHALL be managed by a dedicated React hook (`useWebSocket`) that auto-reconnects on disconnect with exponential backoff.

### Module 3: CI/CD Pipeline

**REQ-RT-010 [Ubiquitous]**
A GitHub Actions workflow SHALL run on every push to main and on pull requests, executing: lint (ruff), type check (mypy), and tests (pytest).

**REQ-RT-011 [State-driven]**
WHILE any CI check fails, merging to main SHALL be blocked via GitHub branch protection.

**REQ-RT-012 [Event-driven]**
WHEN all CI checks pass on main branch, the system SHALL automatically trigger backend deployment to Oracle Cloud VM.

**REQ-RT-013 [Ubiquitous]**
The CI pipeline SHALL include frontend checks: ESLint, TypeScript compilation, and build verification.

---

## 3. Technical Approach

### 3.1 WebSocket Architecture
```
Client <--WebSocket--> FastAPI /ws
                          |
                    ConnectionManager
                          |
              Topic Subscriptions (in-memory set)
                          |
              Event Hooks in Services
              (news_crawler, macro_risk, fund_manager)
```

### 3.2 State Management Migration
- Install Zustand
- Create stores: useWatchlistStore, useAlertStore, useNewsStore
- Gradually migrate pages from local state to Zustand
- WebSocket updates flow through Zustand stores

### 3.3 CI/CD Stack
- GitHub Actions (free tier: 2000 min/month)
- pytest + pytest-cov (backend)
- ruff check + mypy (backend linting/typing)
- eslint + tsc --noEmit (frontend)
- SSH deploy action for Oracle Cloud

---

## 4. Acceptance Criteria Summary

| Scenario | Criteria |
|----------|----------|
| WebSocket connection | Client connects, subscribes to topics, receives events |
| Alert push | Critical macro alert delivered to client within 1 second |
| Reconnection | Client auto-reconnects after disconnect with backoff |
| Fallback | App works without WebSocket (polling mode) |
| Zustand migration | Fund page uses stores instead of prop drilling |
| CI pipeline | Push to PR triggers lint + test + build |
| CD pipeline | Merge to main auto-deploys after green CI |
