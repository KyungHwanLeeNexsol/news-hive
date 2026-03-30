# SPEC-AI-001 Research: AI Fund Prediction System Deep Analysis

## 1. Architecture Analysis

### 1.1 Signal Generation Pipeline (fund_manager.py, 1,161 lines)

**Core Flow:**
```
Scheduler (30min) / Manual Trigger
  -> generate_daily_briefing()
    -> _gather_stock_news() (3-day window)
    -> _gather_macro_alerts() (keyword-based MacroAlert table)
    -> _gather_pick_candidates() (parallel: KIS API + Naver Finance)
      -> _gather_market_data() per stock (KIS price, fundamentals, technicals, investor flows)
      -> _gather_financial_data() per stock (ROE, margins, growth)
    -> news_price_impact stats injection (30-day lookback)
    -> AI prompt (20KB+) -> _ask_ai() -> JSON parse
    -> DailyBriefing DB save
    -> Background: _generate_signals_background()
      -> _generate_signals_from_picks()
        -> analyze_stock() per pick -> FundSignal DB save
```

**Data Sources Per Signal:**
| Source | Data | Freshness |
|--------|------|-----------|
| KIS API | current_price, change_rate, volume, PER, PBR, EPS, 52w high/low, market_cap, foreign_ratio | Real-time |
| Naver Finance | fundamentals (fallback), price_history (100 days), investor_trading (20 days) | Near real-time |
| Technical Indicators | SMA(5/20/60), RSI(14), MACD, Bollinger Bands | Calculated from price_history |
| News | 3-day articles with sentiment | Crawled every 30 min |
| Disclosures (DART) | 1-day recent filings | Daily |
| MacroAlert | keyword-based risk levels | Event-driven |
| NewsPriceImpact | historical news->price correlation | 30-day lookback |

### 1.2 Signal Verification Pipeline (signal_verifier.py, 199 lines)

**Verification Timeline:**
```
Signal Created (T=0)
  -> T+1d: record price_after_1d
  -> T+3d: record price_after_3d
  -> T+5d: record price_after_5d + calculate return_pct + is_correct + verified_at
```

**Accuracy Statistics (get_accuracy_stats):**
- Total accuracy %
- Buy accuracy %, Sell accuracy %
- Average return %
- By confidence bucket: high (>=0.7), medium (0.4-0.7), low (<0.4)

### 1.3 AI Provider Architecture (ai_client.py)

**Multi-Provider Strategy:**
- Primary: OpenRouter (Groq-hosted models)
- Fallback: Gemini x3 (3 retries)
- JSON response parsing with markdown code block stripping

---

## 2. Existing Patterns (Strengths)

### 2.1 Multi-Provider AI with Graceful Fallback
- OpenRouter -> Gemini chain ensures high availability
- _ask_ai() abstracts provider switching from business logic

### 2.2 Confidence Scoring
- 0.0-1.0 scale attached to every FundSignal
- Bucketed into high/medium/low for accuracy analysis

### 2.3 Verification Loop
- Automated 1d/3d/5d price tracking
- Accuracy stats fed back into AI prompt (last 30 days)

### 2.4 Rich Data Pipeline
- 7 distinct data sources per signal
- Technical indicators calculated from 100-day price history
- Supply/demand (foreign + institutional flows) tracked

### 2.5 NewsPriceImpact Integration
- REQ-NPI-014/015 already injects historical news-price reaction stats
- Provides empirical basis for news-driven predictions

---

## 3. Risks and Constraints

### 3.1 API Dependency & Rate Limits
| API | Rate Limit | Impact |
|-----|-----------|--------|
| KIS API | ~100 req/min | Parallel stock data gathering bottleneck |
| Naver Finance | Scraping-based | IP blocking risk, data format changes |
| OpenRouter/Groq | Token-based | 20KB+ prompts consume significant budget |
| Gemini | 60 RPM (free tier) | Fallback capacity limited |

### 3.2 Data Staleness
- Financial data (ROE, margins): quarterly updates -> stale for up to 90 days
- News retention: 7-day policy -> cannot reanalyze older signals
- MacroAlert: keyword-based detection has no decay function -> stale alerts persist

### 3.3 Single-Threaded AI Processing
- Signals generated sequentially per stock (rate limit consideration)
- No parallel prompt execution framework
- No prompt versioning or A/B testing capability

### 3.4 Prompt Size vs Signal Quality
- 20KB+ per briefing prompt with no weighting or prioritization
- All data fields treated equally regardless of predictive power
- No mechanism to identify which data drove the AI's decision

### 3.5 Feedback Loop Limitations
- Only aggregated accuracy % fed back (no error pattern analysis)
- 5-day verification minimum creates slow adaptation
- No mechanism to detect and adapt to market regime changes

---

## 4. Recommendations by Phase

### Phase A: Quick Wins (Immediate Impact)

**A1. Relax Stock Filtering Criteria**
- Current: change_rate <= 0% or -1%, ALL 4 conditions must pass
- Proposed: change_rate >= -3%, 3-of-4 conditions sufficient
- Impact: Increases buy candidate pool by estimated 40-60%
- Risk: Low (AI still evaluates each candidate)
- Files: `fund_manager.py` (prompt rules section, lines 921-938)

**A2. Time-Weighted News Scoring**
- Current: All 3-day news treated equally
- Proposed: 24h: 1.0x, 48h: 0.7x, 72h: 0.4x weight
- Impact: Recent news gets appropriate urgency
- Files: `fund_manager.py` (_gather_stock_news), prompt template

**A3. Error Pattern Categorization**
- Current: Binary is_correct only
- Proposed: Categorize failures (macro_shock, supply_reversal, earnings_miss, sector_contagion, technical_breakdown)
- Impact: Enables targeted prompt improvement
- Files: `signal_verifier.py`, `fund_signal.py` (new column: error_category)

**A4. Bayesian Confidence Calibration**
- Current: AI assigns arbitrary confidence 0.0-1.0
- Proposed: Post-hoc calibration using historical accuracy per confidence bucket
- Impact: Confidence scores become statistically meaningful
- Files: `signal_verifier.py` (new function), `fund_manager.py` (inject calibration data)

### Phase B: Structural Improvements (Medium-Term)

**B1. Multi-Factor Scoring Engine**
- Independent scores for: news_sentiment, technical, supply_demand, valuation
- Configurable weights (default: 0.25 each, tunable per sector)
- Factor contribution tracking per signal for transparency
- Files: New `factor_scoring.py`, `fund_manager.py` integration

**B2. A/B Testing Framework**
- Prompt versioning with parallel signal generation
- Statistical comparison (paired t-test or bootstrap)
- Auto-promote winning prompts after N trials
- Files: New `prompt_versioner.py`, `fund_signal.py` (new column: prompt_version)

**B3. Fast Verification Loop**
- 6h/12h early checks during market hours (09:00-15:30 KST)
- Intraday price snapshots for faster feedback
- Files: `signal_verifier.py` (new fast_verify function), scheduler config

**B4. News Impact Statistical Learning**
- Use news_price_impact table data for sector-specific impact models
- Historical win_rate and avg_return per news category
- Files: `news_price_impact_service.py` enhancement, prompt injection

**B5. Macro Risk NLP Classifier**
- Replace keyword-based MacroAlert with NLP context analysis
- Use AI to classify macro news severity (not just keyword count)
- Files: `macro_alert_service.py` (new or refactored), `fund_manager.py`

### Phase C: Advanced Prediction (Long-Term)

**C1. ML Ensemble Model**
- XGBoost trained on historical factor scores + AI signal outcomes
- AI signal as one feature among many (not sole predictor)
- Files: New `ml_ensemble.py`, training pipeline, model storage

**C2. Sector Propagation Model**
- Model news impact spread within sectors (e.g., Hyundai Steel news -> Daechang Forging)
- Use news_stock_relations cross-sector patterns
- Files: New `sector_propagation.py`, `ai_classifier.py` enhancement

**C3. Paper Trading Simulation**
- Virtual portfolio tracking with Sharpe ratio
- Benchmark against KOSPI index
- Files: New `paper_trading.py`, new DB tables (virtual_portfolio, trades)

---

## 5. Data Model Impact Summary

### New Columns (Existing Tables)
| Table | Column | Type | Purpose |
|-------|--------|------|---------|
| fund_signals | error_category | VARCHAR(30) | Error pattern classification |
| fund_signals | prompt_version | VARCHAR(20) | A/B testing tracking |
| fund_signals | factor_scores | JSONB | Independent factor score breakdown |
| fund_signals | price_after_6h | INTEGER | Fast verification |
| fund_signals | price_after_12h | INTEGER | Fast verification |
| fund_signals | calibrated_confidence | FLOAT | Post-calibration confidence |

### New Tables (Phase B/C)
| Table | Purpose |
|-------|---------|
| prompt_versions | Store prompt templates with version IDs |
| prompt_ab_results | A/B test results per version pair |
| factor_weights | Configurable per-sector factor weights |
| virtual_portfolios | Paper trading portfolio tracking |
| virtual_trades | Paper trading transaction log |

---

## 6. Key Metrics for Success

| Metric | Current Baseline | Phase A Target | Phase B Target | Phase C Target |
|--------|-----------------|----------------|----------------|----------------|
| Buy candidates per day | 0-2 | 3-5 | 3-5 | 3-5 |
| Signal accuracy (5d) | Unknown baseline | +5% relative | +15% relative | +25% relative |
| Confidence calibration | Uncalibrated | Calibrated | Statistically validated | ML-enhanced |
| Feedback loop speed | 5 days | 5 days | 6 hours | Real-time |
| Factor transparency | None | None | Full breakdown | Full breakdown |
| Sharpe ratio | Not tracked | Not tracked | Not tracked | > 1.0 target |
