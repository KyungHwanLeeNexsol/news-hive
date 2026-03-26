---
id: SPEC-COMMODITY-001
version: "0.1.0"
status: draft
created: "2026-03-26"
updated: "2026-03-26"
author: MoAI
priority: critical
tier: 0
issue_number: 0
---

# SPEC-COMMODITY-001: Commodity Price Tracking System

## HISTORY

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1.0 | 2026-03-26 | MoAI | Initial draft |

---

## 1. Overview

Track and visualize real-time and historical commodity prices (crude oil, gold, copper, natural gas, etc.) that directly impact Korean industrial sectors and stock valuations.

### 1.1 Background

- NewsHive tracks sector-based stock news but lacks commodity price context
- Commodity prices (oil, copper, steel) are leading indicators for sectors like construction machinery, shipbuilding, petrochemicals
- Investors in sectors like "건설기계" (Daechang Forging) need raw material price trends to assess margin impacts
- No existing commodity tracking exists in the system

### 1.2 Goals

- Real-time commodity price feeds (major commodities relevant to Korean market)
- Historical price charts (1W/1M/3M/6M/1Y)
- Sector-commodity correlation mapping (e.g., copper price -> 건설기계 sector)
- Price change alerts integrated with macro risk system
- Commodity data integration into AI fund manager briefings

---

## 2. Environment

### 2.1 System

- **Backend**: FastAPI / SQLAlchemy 2.0
- **Frontend**: Next.js / TypeScript / Tailwind CSS v4
- **Data Sources**: Yahoo Finance API (yfinance), Investing.com RSS, or free commodity APIs
- **Charts**: recharts or lightweight-charts (already available in frontend)

### 2.2 Constraints

- Free API tier preferred (no paid data subscriptions)
- Price update frequency: every 10 minutes (aligned with news crawl cycle)
- Must support at least 10 major commodities
- Historical data: minimum 1 year

---

## 3. Requirements (EARS Format)

### Module 1: Data Model & Collection

**REQ-CMD-001 [Ubiquitous]**
The system SHALL maintain a `commodities` table with: id, symbol, name_ko, name_en, category (energy/metal/agriculture), unit, currency, created_at.

**REQ-CMD-002 [Ubiquitous]**
The system SHALL maintain a `commodity_prices` table with: id, commodity_id, price, change_pct, volume, recorded_at, source.

**REQ-CMD-003 [Ubiquitous]**
The system SHALL collect prices for at minimum these commodities:
- Energy: WTI crude oil (CL=F), Brent crude (BZ=F), natural gas (NG=F)
- Precious metals: Gold (GC=F), Silver (SI=F)
- Industrial metals: Copper (HG=F), Aluminum, Steel (rebar)
- Agriculture: Corn (ZC=F), Wheat (ZW=F), Soybeans (ZS=F)

**REQ-CMD-004 [Event-driven]**
WHEN the news crawl scheduler runs (every 10 minutes), the system SHALL also fetch and store latest commodity prices.

**REQ-CMD-005 [Ubiquitous]**
The system SHALL provide historical price data via yfinance or equivalent free API with at least 1 year of daily OHLCV data.

### Module 2: Sector-Commodity Mapping

**REQ-CMD-006 [Ubiquitous]**
The system SHALL maintain a `sector_commodity_relations` table mapping sectors to relevant commodities with correlation_type ('positive'/'negative'/'neutral') and description.

**REQ-CMD-007 [Ubiquitous]**
The system SHALL seed default sector-commodity mappings:
- 건설기계 -> Copper (positive), Steel (positive)
- 정유/화학 -> WTI (positive), Brent (positive)
- 반도체 -> Natural Gas (negative - energy cost)
- 자동차 -> Steel (negative - cost), Aluminum (negative)
- 금융 -> Gold (neutral/inverse)

**REQ-CMD-008 [Event-driven]**
WHEN a commodity price changes more than 3% in a single day, the system SHALL create a MacroAlert for related sectors.

### Module 3: API Endpoints

**REQ-CMD-009 [Ubiquitous]**
The system SHALL provide `GET /api/commodities` returning all tracked commodities with latest prices.

**REQ-CMD-010 [Ubiquitous]**
The system SHALL provide `GET /api/commodities/{id}/history?period=1M` returning historical OHLCV data for charting.

**REQ-CMD-011 [Ubiquitous]**
The system SHALL provide `GET /api/sectors/{id}/commodities` returning related commodities with correlation info.

### Module 4: Frontend

**REQ-CMD-012 [Ubiquitous]**
The dashboard SHALL display a commodity price ticker bar showing major commodity prices with daily change %.

**REQ-CMD-013 [Ubiquitous]**
The system SHALL provide a `/commodities` page with:
- Commodity price cards grouped by category (Energy, Metal, Agriculture)
- Sparkline charts showing 7-day price trend per commodity
- Click to expand: full historical chart with period selector

**REQ-CMD-014 [Ubiquitous]**
The sector detail page SHALL display related commodity prices and their correlation indicators.

### Module 5: AI Integration

**REQ-CMD-015 [Ubiquitous]**
The daily AI briefing SHALL include a "Commodity Market Overview" section with significant price movements and their potential sector impacts.

**REQ-CMD-016 [Event-driven]**
WHEN generating investment signals, the fund manager SHALL consider commodity price trends as an input factor for sectors with commodity correlations.

---

## 4. Technical Approach

### 4.1 Data Collection
- Primary: yfinance (free, no API key needed, Yahoo Finance symbols)
- Fallback: Investing.com RSS for price change alerts
- Schedule: Piggyback on existing 10-min news crawl cycle

### 4.2 Database
- `commodities` table (master data, seeded)
- `commodity_prices` table (time-series, partitioned by date)
- `sector_commodity_relations` table (mapping)

### 4.3 Frontend
- Dashboard ticker: horizontal scrolling bar component
- Commodities page: card grid with sparklines
- recharts for historical charts

---

## 5. Acceptance Criteria Summary

| Scenario | Criteria |
|----------|----------|
| Price collection | 10+ commodities updated every 10 minutes |
| Historical data | 1Y daily OHLCV available for all commodities |
| Sector mapping | Default correlations seeded, displayed on sector page |
| Alert trigger | 3%+ daily move creates MacroAlert for related sectors |
| Dashboard ticker | Commodity prices visible on main dashboard |
| Commodities page | All commodities listed with sparklines and full charts |
| AI briefing | Commodity overview section in daily briefing |
