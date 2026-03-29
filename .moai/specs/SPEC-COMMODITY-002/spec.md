---
id: SPEC-COMMODITY-002
version: "0.1.0"
status: completed
created: "2026-03-26"
updated: "2026-03-26"
author: MoAI
priority: critical
tier: 0
issue_number: 0
---

# SPEC-COMMODITY-002: Commodity Newsroom

## HISTORY

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1.0 | 2026-03-26 | MoAI | Initial draft |

---

## 1. Overview

Create a dedicated commodity newsroom that aggregates and AI-classifies news specifically about raw materials, energy markets, and commodity-related events, separate from the stock news feed.

### 1.1 Background

- Current news crawling focuses on stock-related keywords
- Commodity news ("유가 급등", "구리 수요 증가", "철강 가격 인하") is often missed or buried
- Commodity news is a leading indicator — it precedes stock price movements
- Users need a dedicated space to monitor commodity market intelligence

### 1.2 Goals

- Dedicated commodity news crawling pipeline (separate from stock news)
- Commodity-specific keyword matching and AI classification
- Dedicated newsroom page with commodity-filtered news feed
- Commodity-news → sector impact auto-tagging
- Integration with SPEC-COMMODITY-001 price data for context

---

## 2. Environment

### 2.1 System

- **Backend**: FastAPI / SQLAlchemy 2.0 / Existing news crawler infrastructure
- **Frontend**: Next.js / TypeScript / Tailwind CSS v4
- **News Sources**: Google News RSS, Naver News API, Yahoo Finance RSS (commodity keywords)
- **AI**: Gemini/Groq (existing multi-provider fallback)

### 2.2 Dependencies

- SPEC-COMMODITY-001 (commodity master data, sector-commodity mapping)
- Existing news_crawler.py, ai_classifier.py infrastructure

---

## 3. Requirements (EARS Format)

### Module 1: Commodity News Crawling

**REQ-CNR-001 [Ubiquitous]**
The system SHALL maintain a set of commodity-specific search keywords:
- Korean: 유가, 금값, 구리가격, 원자재, 철강가격, 원유, 천연가스, 곡물가격, 알루미늄, 리튬
- English: crude oil price, gold price, copper futures, commodity market, steel price, natural gas

**REQ-CNR-002 [Ubiquitous]**
The system SHALL crawl commodity news from existing sources (Naver, Google RSS, Yahoo) using commodity-specific keywords, separate from stock news queries.

**REQ-CNR-003 [Event-driven]**
WHEN the news crawl scheduler runs, the system SHALL execute commodity news crawling as an additional phase after stock news crawling.

**REQ-CNR-004 [Ubiquitous]**
Commodity news articles SHALL be stored in the existing `news_articles` table with a new source tag or category field to distinguish them from stock news.

### Module 2: Commodity News Classification

**REQ-CNR-005 [Ubiquitous]**
The AI classifier SHALL map commodity news to relevant commodities (from SPEC-COMMODITY-001 commodities table) and related sectors.

**REQ-CNR-006 [Ubiquitous]**
The system SHALL maintain a `news_commodity_relations` table with: id, news_id, commodity_id, relevance ('direct'/'indirect'), match_type ('keyword'/'ai_classified').

**REQ-CNR-007 [Ubiquitous]**
The AI classifier SHALL assess commodity news impact direction: 'price_up', 'price_down', 'supply_disruption', 'demand_change', 'policy_change', 'neutral'.

**REQ-CNR-008 [Ubiquitous]**
The system SHALL auto-tag commodity news with impacted sectors using the sector_commodity_relations mapping from SPEC-COMMODITY-001.

### Module 3: API Endpoints

**REQ-CNR-009 [Ubiquitous]**
The system SHALL provide `GET /api/commodities/news` returning commodity-related news feed with pagination, filtering by commodity and impact type.

**REQ-CNR-010 [Ubiquitous]**
The system SHALL provide `GET /api/commodities/{id}/news` returning news for a specific commodity.

**REQ-CNR-011 [Ubiquitous]**
The system SHALL provide `GET /api/sectors/{id}/commodity-news` returning commodity news that impacts a specific sector.

### Module 4: Commodity Newsroom Frontend

**REQ-CNR-012 [Ubiquitous]**
The system SHALL provide a `/commodities/news` (or integrated within `/commodities`) page featuring:
- Commodity news feed with impact direction badges (up/down/disruption)
- Filter by commodity category (Energy, Metal, Agriculture)
- Filter by impact type
- Related commodity price context (inline mini-chart from SPEC-COMMODITY-001)

**REQ-CNR-013 [Ubiquitous]**
Each commodity news card SHALL display:
- Title, source, published time
- Mapped commodities with price change badges
- Impact direction indicator
- Affected sectors list

**REQ-CNR-014 [Ubiquitous]**
The sector detail page SHALL include a "Commodity News" tab showing commodity news that impacts the sector, alongside the existing stock news feed.

### Module 5: AI Integration

**REQ-CNR-015 [Ubiquitous]**
The daily AI briefing SHALL include a "Commodity News Highlights" subsection summarizing significant commodity news and their potential sector impacts.

**REQ-CNR-016 [Event-driven]**
WHEN commodity news classified as 'supply_disruption' or with > 3% price impact is detected, the system SHALL generate a MacroAlert with relevant sector tags.

---

## 4. Technical Approach

### 4.1 Crawling Strategy
- Add commodity keyword queries to existing crawl cycle (separate phase)
- Reuse existing crawler infrastructure (Naver, Google RSS)
- Deduplication against both stock news and commodity news pools

### 4.2 Classification Pipeline
```
Commodity News Article
  -> Keyword Matching (commodity names, price terms)
  -> AI Classification (impact direction, affected commodities)
  -> Sector Auto-Tagging (via sector_commodity_relations)
  -> Store in news_articles + news_commodity_relations
```

### 4.3 Database Additions
- `news_commodity_relations` table (news_id, commodity_id, relevance, impact_direction)
- Optional: `news_articles.category` field ('stock'/'commodity'/'both') or use relation tables

### 4.4 Frontend
- New `/commodities/news` route or tab within `/commodities`
- Reuse NewsCard component with commodity-specific badges
- Add "Commodity News" tab to sector detail page

---

## 5. Acceptance Criteria Summary

| Scenario | Criteria |
|----------|----------|
| Keyword crawling | Commodity keywords return relevant news from Naver/Google |
| Classification | News mapped to correct commodities with impact direction |
| Sector auto-tag | Commodity news auto-linked to affected sectors |
| Newsroom page | Dedicated feed with commodity/impact filters |
| News card | Shows commodity badges, impact direction, affected sectors |
| Sector integration | Commodity news tab on sector detail page |
| AI briefing | Commodity highlights in daily briefing |
| Supply disruption alert | Critical commodity news triggers MacroAlert |
