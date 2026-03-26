---
id: SPEC-AUTH-001
version: "0.1.0"
status: draft
created: "2026-03-26"
updated: "2026-03-26"
author: MoAI
priority: medium
tier: 3
issue_number: 0
---

# SPEC-AUTH-001: User Authentication & Personalization

## HISTORY

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1.0 | 2026-03-26 | MoAI | Initial draft from roadmap analysis |

---

## 1. Overview

Implement user authentication system and personalization features to enable cross-device watchlist sync, personalized alerts, and push notifications.

### 1.1 Background

- Current auth is admin-only (single password for fund manager portal)
- Watchlist is localStorage-based, lost on browser clear or device switch
- No per-user alert preferences (all users see all macro alerts)
- Push notifications impossible without user identity

### 1.2 Goals

- OAuth2 + JWT authentication (Google, Kakao social login)
- Server-side watchlist with cross-device sync
- Per-user notification preferences (which sectors/stocks to follow)
- Web Push notifications for critical alerts and signals
- User dashboard with personalized news feed

---

## 2. Requirements (EARS Format)

### Module 1: Authentication

**REQ-AUTH-001 [Ubiquitous]**
The system SHALL support user registration and login via OAuth2 social login (Google, Kakao).

**REQ-AUTH-002 [Ubiquitous]**
The system SHALL issue JWT access tokens (15-minute expiry) and refresh tokens (7-day expiry) upon successful authentication.

**REQ-AUTH-003 [Ubiquitous]**
The system SHALL store user profiles in a `users` table with: id, email, name, provider, avatar_url, created_at, last_login_at.

**REQ-AUTH-004 [Event-driven]**
WHEN a JWT access token expires, the frontend SHALL automatically refresh it using the stored refresh token without user interaction.

### Module 2: Personalization

**REQ-AUTH-005 [Ubiquitous]**
The system SHALL store user watchlists server-side in a `user_watchlists` table, replacing localStorage-based persistence.

**REQ-AUTH-006 [Ubiquitous]**
The system SHALL provide a `user_preferences` table storing: notification_enabled, followed_sectors[], followed_stocks[], alert_level_threshold.

**REQ-AUTH-007 [State-driven]**
WHILE a user is not authenticated, the system SHALL continue to use localStorage for watchlist (backward compatible).

**REQ-AUTH-008 [Event-driven]**
WHEN a user first authenticates, the system SHALL merge their localStorage watchlist with server-side data (union, no duplicates).

### Module 3: Push Notifications

**REQ-AUTH-009 [Ubiquitous]**
The system SHALL support Web Push API notifications via service worker registration.

**REQ-AUTH-010 [Event-driven]**
WHEN a macro alert with level "critical" is created AND the user has notification_enabled=true, the system SHALL send a push notification.

**REQ-AUTH-011 [Event-driven]**
WHEN a new FundSignal is generated for a stock in the user's followed_stocks list, the system SHALL send a push notification with signal details.

**REQ-AUTH-012 [Event-driven]**
WHEN significant news (sentiment != neutral) is published for a user's followed sector/stock, the system SHALL queue a digest notification (batched every 30 minutes).

### Module 4: Personalized Feed

**REQ-AUTH-013 [Ubiquitous]**
The dashboard SHALL display a personalized news feed prioritizing the user's followed sectors and stocks.

**REQ-AUTH-014 [State-driven]**
WHILE a user has no followed sectors/stocks configured, the dashboard SHALL show the default global feed.

---

## 3. Technical Approach

### 3.1 Auth Stack
- python-jose (JWT), authlib (OAuth2 providers)
- Google OAuth2 + Kakao OAuth2
- HttpOnly cookie for refresh token, Authorization header for access token

### 3.2 Database Additions
- `users` table (profile)
- `user_watchlists` table (user_id, stock_id)
- `user_preferences` table (user_id, settings JSON)
- `push_subscriptions` table (user_id, endpoint, keys)

### 3.3 Push Notification Stack
- pywebpush (server-side VAPID push)
- Service Worker (frontend push receiver)
- Notification batching via scheduler job

---

## 4. Acceptance Criteria Summary

| Scenario | Criteria |
|----------|----------|
| Social login | Google/Kakao OAuth2 flow completes, JWT issued |
| Token refresh | Expired access token silently refreshed |
| Watchlist sync | Watchlist persists across devices after login |
| localStorage merge | First login merges existing watchlist |
| Push notification | Critical alert triggers browser notification |
| Personalized feed | Dashboard shows followed stocks/sectors first |
| Backward compatible | Unauthenticated users retain full functionality |
