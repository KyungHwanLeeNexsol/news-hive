---
id: SPEC-VIZ-001
version: "0.1.0"
status: draft
created: "2026-03-26"
updated: "2026-03-26"
author: MoAI
priority: medium
tier: 3
issue_number: 0
---

# SPEC-VIZ-001: Advanced Visualization & AI Conversational Analysis

## HISTORY

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1.0 | 2026-03-26 | MoAI | Initial draft from roadmap analysis |

---

## 1. Overview

Enhance the frontend with interactive data visualizations and introduce AI-powered conversational analysis for natural language stock/market queries.

### 1.1 Background

- Sector overview is text-based cards only — no visual market overview
- Stock price data exists but is displayed as numbers, not charts
- AI fund manager generates one-directional briefings; users cannot ask follow-up questions
- Technical indicators (RSI, MACD, Bollinger) are available but not visually charted
- Backtesting capability is missing despite having signal accuracy tracking data

### 1.2 Goals

- Interactive sector heatmap for instant market overview
- Candlestick/line charts with technical indicator overlays
- AI chat interface for natural language market analysis
- Signal backtesting dashboard with historical performance visualization
- News sentiment timeline correlated with price movement

---

## 2. Requirements (EARS Format)

### Module 1: Sector Heatmap

**REQ-VIZ-001 [Ubiquitous]**
The dashboard SHALL display an interactive sector heatmap where each cell represents a sector, sized by constituent stock count and colored by daily performance (green: positive, red: negative, gray: neutral).

**REQ-VIZ-002 [Event-driven]**
WHEN a user clicks a sector cell in the heatmap, the system SHALL navigate to the sector detail page.

**REQ-VIZ-003 [Ubiquitous]**
The heatmap SHALL auto-refresh using WebSocket price updates (or polling fallback).

### Module 2: Interactive Charts

**REQ-VIZ-004 [Ubiquitous]**
The stock detail page SHALL display an interactive candlestick chart with configurable time ranges (1W, 1M, 3M, 6M, 1Y).

**REQ-VIZ-005 [Ubiquitous]**
The chart SHALL support overlay toggles for: SMA (5/20/60), Bollinger Bands, volume bars.

**REQ-VIZ-006 [Ubiquitous]**
A secondary chart panel SHALL display RSI and MACD indicators synchronized with the main price chart.

**REQ-VIZ-007 [Ubiquitous]**
News events SHALL be marked on the price chart as clickable annotation dots, colored by sentiment (green/red/gray).

### Module 3: AI Conversational Analysis

**REQ-VIZ-008 [Ubiquitous]**
The system SHALL provide a chat interface at `/chat` where users can ask natural language questions about stocks, sectors, and market conditions.

**REQ-VIZ-009 [Ubiquitous]**
The AI chat SHALL have access to: current stock prices, recent news, technical indicators, financial data, sector performance, and signal history as context.

**REQ-VIZ-010 [Ubiquitous]**
The AI SHALL respond in Korean with structured analysis including relevant data points, not generic answers.

**REQ-VIZ-011 [Ubiquitous]**
The chat SHALL support follow-up questions with conversation memory within a session.

**REQ-VIZ-012 [Event-driven]**
WHEN a user asks about a specific stock, the system SHALL automatically fetch and inject the latest price, news, and technical analysis into the AI context.

### Module 4: Backtesting Dashboard

**REQ-VIZ-013 [Ubiquitous]**
The fund manager page SHALL display a signal accuracy timeline chart showing cumulative return of buy/sell signals over time.

**REQ-VIZ-014 [Ubiquitous]**
The backtesting dashboard SHALL show: win rate, average return, max drawdown, Sharpe ratio, and comparison against KOSPI benchmark.

**REQ-VIZ-015 [Ubiquitous]**
Users SHALL be able to filter backtest results by: date range, stock, sector, signal type (buy/sell), confidence threshold.

### Module 5: News-Price Correlation View

**REQ-VIZ-016 [Ubiquitous]**
The stock detail page SHALL display a sentiment timeline showing news sentiment scores overlaid on the price chart.

**REQ-VIZ-017 [Ubiquitous]**
The system SHALL calculate and display a rolling news-price correlation coefficient (7-day window) for each stock.

---

## 3. Technical Approach

### 3.1 Visualization Libraries
- recharts (already installed) for basic charts
- lightweight-charts (TradingView) for candlestick + technical overlays
- d3.js or react-heatmap-grid for sector heatmap

### 3.2 AI Chat Architecture
```
User Query -> /api/chat endpoint
  -> Context Builder (fetch stock/news/technical data)
  -> Gemini/Claude API with structured prompt
  -> Streaming response to frontend
```

### 3.3 Backtesting Data
- Leverage existing FundSignal + price_after_1d/3d/5d data
- Backend aggregation endpoint for time-series performance data
- Frontend visualization with recharts

---

## 4. Acceptance Criteria Summary

| Scenario | Criteria |
|----------|----------|
| Heatmap | All sectors displayed, color reflects daily performance |
| Candlestick chart | Price data rendered with technical overlays |
| News annotations | Clickable dots on chart linked to news articles |
| AI chat | Natural language query returns data-backed Korean analysis |
| Follow-up | Chat maintains context for multi-turn conversation |
| Backtesting | Signal accuracy chart with filters and benchmark comparison |
| Sentiment timeline | News sentiment overlaid on price chart |
