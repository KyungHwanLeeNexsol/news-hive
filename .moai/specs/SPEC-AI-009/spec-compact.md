# SPEC-AI-009 Compact

**Title**: 증권사 컨센서스 목표주가 집계 및 fund_manager 통합
**Status**: draft | **Priority**: Medium | **Created**: 2026-04-14

## Requirements (EARS)

- REQ-CONSENSUS-001: System SHALL aggregate `target_price` from `SecuritiesReport` within last 90 days per stock.
- REQ-CONSENSUS-002: System SHALL compute `avg_target_price`, `median_target_price`, `min_target`, `max_target` from reports with non-null `target_price`.
- REQ-CONSENSUS-003: System SHALL compute `buy_ratio`, `hold_ratio`, `sell_ratio` from `opinion` field (매수/비중확대→buy, 중립/보유→hold, 매도/비중축소→sell).
- REQ-CONSENSUS-004: System SHALL compute `premium_pct = (avg_target_price - current_price) / current_price * 100`.
- REQ-CONSENSUS-005: WHEN `report_count >= 3` AND `buy_ratio >= 0.7` AND `premium_pct >= 15` THEN `consensus_signal = "strong_buy"`.
- REQ-CONSENSUS-006: WHEN `sell_ratio >= 0.5` OR `premium_pct < 0` THEN `consensus_signal = "caution"`.
- REQ-CONSENSUS-007: System SHALL compute `target_price_trend` by comparing avg of last 30 days vs 31-90 days (rising/falling/stable).
- REQ-CONSENSUS-008: System SHALL include consensus summary in `analyze_stock()` AI prompt as dedicated section "## 9-1. 증권사 컨센서스".

## Acceptance (Given/When/Then)

1. **Given** 5 reports target=[85000,90000,92000,88000,95000], current=80000 **When** consensus computed **Then** avg=90000, premium_pct=12.5.
2. **Given** buy_ratio=0.8, premium=18%, report_count=5 **When** consensus computed **Then** consensus_signal="strong_buy".
3. **Given** 0 reports with target_price (all None) **When** consensus computed **Then** consensus_signal="insufficient", avg_target_price=None.
4. **Given** 30d avg=90000, 31-90d avg=80000 **When** trend computed **Then** target_price_trend="rising".
5. **Given** sell_ratio=0.6 **When** consensus computed **Then** consensus_signal="caution" regardless of premium.

## Files to Modify

- `backend/app/services/fund_manager.py`:
  1. Add `_gather_securities_consensus(db, stock_id, current_price) -> dict` after `_gather_securities_reports()` (~line 408+)
  2. Call in `analyze_stock()` after `_gather_securities_reports()` using `current_price` from market_data
  3. Add "## 9-1. 증권사 컨센서스" section to AI prompt

## No New Files

- No new model
- No new migration
- No new crawler
- Data source: existing `SecuritiesReport` table

## Exclusions

- New crawler/scraper (data already collected)
- Real-time consensus API integration
- Storing consensus as separate DB table (compute on-the-fly)
- ETF/fund price consensus (stocks only)
- Historical consensus tracking
- Broker-specific weighting/credibility system

## MX Tags

- `_gather_securities_consensus()`: @MX:ANCHOR (high fan_in from `analyze_stock`)
