---
id: SPEC-CACHE-001
version: "0.1.0"
status: completed
created: "2026-03-26"
updated: "2026-03-29"
author: MoAI
priority: high
tier: 2
issue_number: 0
---

# SPEC-CACHE-001: Redis Caching Layer & API Rate Limiting

## HISTORY

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1.0 | 2026-03-26 | MoAI | Initial draft from roadmap analysis |

---

## 1. Overview

Introduce Redis as a centralized caching and rate limiting layer to reduce external API costs, improve response times, and protect the application from abuse.

### 1.1 Background

- Current caching is in-memory (Python dict) with no persistence across restarts
- Naver Finance scraping and KIS API calls have per-service TTL logic duplicated in each module
- No rate limiting exists on public API endpoints
- Backend cold-start on Oracle Cloud VM takes 10-30 seconds, losing all cached data

### 1.2 Goals

- Centralized Redis cache replacing scattered in-memory caches
- 3-5x response time improvement for cached data (stock prices, financials)
- API rate limiting: 60 req/min per IP for public endpoints, 10 req/min for expensive operations
- Cache persistence across application restarts
- Reduced Naver/KIS API call volume by 70%+

---

## 2. Environment

### 2.1 System

- **Backend**: FastAPI / SQLAlchemy 2.0
- **Cache**: Redis 7.x (docker-compose addition)
- **Rate Limiter**: slowapi or custom Redis-based implementation
- **Affected Services**: naver_finance.py, kis_api.py, financial_scraper.py, ai_client.py

### 2.2 Constraints

- Oracle Cloud VM has 1GB RAM — Redis memory must be bounded (max 256MB)
- Must gracefully degrade if Redis is unavailable (fallback to direct API calls)
- Cache invalidation must be automatic (TTL-based) and manual (admin endpoint)

---

## 3. Requirements (EARS Format)

### Module 1: Redis Infrastructure

**REQ-CACHE-001 [Ubiquitous]**
The system SHALL add Redis 7.x to docker-compose.yml with a 256MB memory limit and LRU eviction policy.

**REQ-CACHE-002 [Ubiquitous]**
The system SHALL provide a shared Redis connection pool via `database.py` or a dedicated `cache.py` module, using `redis.asyncio` for async support.

**REQ-CACHE-003 [Event-driven]**
WHEN Redis is unavailable, the system SHALL fall back to direct API calls without caching, logging a warning on each fallback occurrence.

### Module 2: Caching Strategy

**REQ-CACHE-004 [Ubiquitous]**
Stock price data (from Naver Finance and KIS API) SHALL be cached in Redis with a configurable TTL (default: 5 minutes during market hours, 30 minutes outside).

**REQ-CACHE-005 [Ubiquitous]**
Financial data (PER, PBR, market cap, revenue) SHALL be cached with a 24-hour TTL.

**REQ-CACHE-006 [Ubiquitous]**
AI classification results (Gemini/Groq responses) SHALL be cached by input hash with a 1-hour TTL to prevent duplicate classifications for the same article content.

**REQ-CACHE-007 [Ubiquitous]**
Sector performance data (from Naver sector pages) SHALL be cached with a 10-minute TTL.

**REQ-CACHE-008 [Event-driven]**
WHEN an admin triggers manual refresh via POST /api/news/refresh, the system SHALL invalidate all news-related caches.

### Module 3: Rate Limiting

**REQ-CACHE-009 [Ubiquitous]**
All public API endpoints SHALL enforce a rate limit of 60 requests per minute per client IP using Redis-backed sliding window counters.

**REQ-CACHE-010 [Ubiquitous]**
Expensive endpoints (POST /api/news/refresh, POST /api/fund/briefing, POST /api/fund/portfolio/analyze) SHALL enforce a stricter limit of 10 requests per minute per client IP.

**REQ-CACHE-011 [Event-driven]**
WHEN a rate limit is exceeded, the system SHALL return HTTP 429 (Too Many Requests) with a `Retry-After` header indicating seconds until the limit resets.

### Module 4: Cache Management

**REQ-CACHE-012 [Ubiquitous]**
The system SHALL provide an admin endpoint `DELETE /api/admin/cache` to flush specific cache namespaces or all caches.

**REQ-CACHE-013 [Ubiquitous]**
The system SHALL expose cache hit/miss statistics via `GET /api/admin/cache/stats` for monitoring.

---

## 4. Technical Approach

### 4.1 Cache Key Strategy
```
newshive:price:{stock_code}           # TTL: 5min/30min
newshive:financial:{stock_code}       # TTL: 24h
newshive:sector:{sector_id}:perf      # TTL: 10min
newshive:ai:classify:{content_hash}   # TTL: 1h
newshive:ratelimit:{ip}:{endpoint}    # TTL: 60s sliding window
```

### 4.2 Dependencies
- redis[hiredis] (async Redis client)
- slowapi or custom middleware (rate limiting)

### 4.3 Migration Path
1. Add Redis to docker-compose + deployment scripts
2. Create cache.py utility module
3. Migrate naver_finance.py cache -> Redis
4. Migrate kis_api.py cache -> Redis
5. Add rate limiting middleware
6. Add admin cache management endpoints

---

## 5. Acceptance Criteria Summary

| Scenario | Criteria |
|----------|----------|
| Redis setup | Redis runs via docker-compose, connection pool works |
| Cache hit | Second request for same stock price returns from cache (< 10ms) |
| Cache miss | First request calls external API, stores result in Redis |
| Graceful degradation | App works without Redis (direct API calls, warning logged) |
| Rate limiting | 61st request in a minute returns 429 |
| Cache flush | Admin endpoint clears specific namespace |
| Memory bound | Redis memory stays under 256MB with LRU eviction |
