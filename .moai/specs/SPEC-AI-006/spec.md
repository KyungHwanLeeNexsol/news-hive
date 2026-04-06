# SPEC-AI-006: Self-Improving Prediction Model via Paper Trading Feedback Loop

| Field       | Value                                                     |
|-------------|-----------------------------------------------------------|
| SPEC ID     | SPEC-AI-006                                               |
| Title       | Self-Improving Prediction Model via Paper Trading Feedback |
| Status      | Planned                                                   |
| Priority    | High                                                      |
| Created     | 2026-04-06                                                |
| Lifecycle   | spec-anchored                                             |
| Related     | SPEC-AI-003, SPEC-AI-004, SPEC-AI-005                     |

---

## Problem Statement

NewsHive's AI fund manager generates buy/sell signals via Gemini LLM and tracks their accuracy through paper trading. However, the system currently operates as an **open loop** -- signal outcomes are recorded but never fed back to improve future predictions. Specifically:

1. **A/B Test Infrastructure is Dormant**: `prompt_versioner.py` has full A/B test + z-test + auto-promotion logic, but no treatment version has ever been created. The loop never activates.
2. **ML Feature Data is Collected but Unused**: `MLFeatureSnapshot` captures daily factor averages, trend distributions, and volatility, but no service consumes this data for weight optimization.
3. **Error Patterns are Classified but Ignored**: Failed signals receive `error_category` labels (macro_shock, supply_reversal, etc.) but these patterns never influence prompt generation.
4. **Factor Weights are Static**: `DEFAULT_WEIGHTS` in `factor_scoring.py` are hardcoded at 0.25 each, regardless of historical factor-outcome correlations.
5. **Signal Type Imbalance**: `sector_ripple` dominates (21 trades), while `disclosure_impact` and `gap_pullback_candidate` have 0 trades -- no mechanism to analyze or correct this imbalance.

The result: the system accumulates valuable performance data but never learns from it.

---

## User Stories

### US-1: System Administrator
As a system administrator, I want the prediction model to automatically analyze its own failures and generate improved prompt variants, so that signal accuracy improves over time without manual intervention.

### US-2: Investor User
As an investor, I want to see which prompt version is currently active and its historical accuracy, so that I can trust the system's signal quality.

### US-3: System Operator
As a system operator, I want factor weights to adapt based on actual performance data, so that the scoring system reflects real market conditions rather than static assumptions.

---

## Environment

- **Backend**: FastAPI on OCI VM (140.245.76.242:8000), Python 3.13+, PostgreSQL 16
- **AI Provider**: Gemini free tier (20 req/day limit), OpenRouter fallback
- **Scheduler**: APScheduler with 17+ existing jobs
- **Paper Trading**: 21 open positions, 0 closed trades (as of 2026-04-06)
- **Existing Services**: `signal_verifier.py`, `prompt_versioner.py`, `ml_feature_engineering.py`, `factor_scoring.py`, `fund_manager.py`

---

## Assumptions

- A-1: Paper trading will accumulate at least 30 closed trades within 2-3 weeks, providing sufficient data for the first improvement cycle.
- A-2: Gemini free tier's 20 req/day budget can accommodate 1-2 additional weekly requests for prompt analysis and generation.
- A-3: The existing `evaluate_ab_test()` z-test implementation is statistically sound and requires no modification.
- A-4: `error_category` classification by `signal_verifier.py` is accurate enough to serve as failure pattern input.
- A-5: Factor weight adjustments within a bounded range (0.10-0.40 per factor) will not destabilize the scoring system.

---

## Functional Requirements (EARS Format)

### Phase 1: Failure Pattern Aggregation (패턴 수집)

**REQ-006-001** (Event-Driven):
WHEN signal verification completes daily at 18:00 KST AND at least 5 new signals have been verified,
THEN the system shall generate a failure pattern summary containing:
- Total verified count, accuracy rate
- Error category distribution (macro_shock, supply_reversal, earnings_miss, sector_contagion, technical_breakdown)
- Signal type distribution (sector_ripple, disclosure_impact, gap_pullback_candidate) with per-type accuracy
- Average return_pct for correct vs incorrect signals
- Factor score averages for correct vs incorrect signals (from factor_scores JSON)

**REQ-006-002** (State-Driven):
IF the failure pattern summary shows accuracy below 50% for any signal_type with at least 5 verified signals,
THEN the system shall flag that signal_type for prompt review and log a warning.

### Phase 2: Automatic Prompt Improvement (프롬프트 자동 개선)

**REQ-006-003** (Event-Driven):
WHEN the weekly improvement job runs (Sunday 22:00 KST) AND at least 20 verified signals have accumulated since the last prompt version was created,
THEN the system shall:
1. Aggregate all failure patterns from the past 30 days
2. Build an LLM meta-prompt containing: current signal prompt template, failure pattern summary, top 5 worst-performing signals with full context (reasoning, factor_scores, error_category, return_pct)
3. Call Gemini to generate an improved prompt variant with specific changes explained
4. Register the new variant as a `PromptVersion` (treatment, is_active=True, is_control=False)
5. Log the generation event with rationale

**REQ-006-004** (Ubiquitous):
The system shall limit prompt improvement to at most 1 new treatment version per week to conserve Gemini API quota.

**REQ-006-005** (Unwanted):
The system shall NOT generate a new treatment version if an active A/B test is already running (i.e., both control and treatment exist in PromptVersion with is_active=True).

### Phase 3: A/B Test Lifecycle (A/B 테스트 자동화)

**REQ-006-006** (Event-Driven):
WHEN a new PromptVersion treatment is registered,
THEN the system shall automatically activate A/B testing:
- 50% of new signals use the control prompt
- 50% use the treatment prompt
- Assignment is deterministic based on stock_id parity (even=control, odd=treatment)

**REQ-006-007** (Event-Driven):
WHEN the weekly evaluation job runs AND both control and treatment have at least 10 verified signals each,
THEN the system shall call `evaluate_ab_test()` which already performs z-test comparison and auto-promotes the winner.

**REQ-006-008** (Event-Driven):
WHEN `evaluate_ab_test()` determines a winner with p_value < 0.05,
THEN the loser version shall be deactivated and the winner promoted to control (already implemented in `_promote_version()`).

**REQ-006-009** (State-Driven):
IF an A/B test has been running for more than 30 days without reaching statistical significance (both versions have 10+ signals but p_value >= 0.05),
THEN the system shall auto-resolve by keeping the current control and deactivating the treatment, logging "inconclusive" as the result.

### Phase 4: Factor Weight Adaptation (팩터 가중치 적응)

**REQ-006-010** (Event-Driven):
WHEN the monthly weight adaptation job runs (1st of each month, 23:00 KST) AND at least 30 verified signals exist in the past 60 days,
THEN the system shall:
1. Query all verified signals with factor_scores from the past 60 days
2. For each factor (news_sentiment, technical, supply_demand, valuation), compute the Pearson correlation between factor score and is_correct outcome
3. Normalize correlations to new weights (sum = 1.0, each bounded to [0.10, 0.40])
4. Store the new weights in a `FactorWeightHistory` record
5. Update the active weights used by `factor_scoring.py`

**REQ-006-011** (Ubiquitous):
The system shall always keep factor weights bounded within [0.10, 0.40] per factor, summing to 1.0.

**REQ-006-012** (Unwanted):
The system shall NOT apply new factor weights if the computed weights would change any individual factor by more than 0.10 from current values in a single update cycle (dampening). Instead, it shall apply a half-step toward the target weights.

### Phase 5: Monitoring and Reporting (모니터링)

**REQ-006-013** (Event-Driven):
WHEN the daily briefing is generated at 08:30 KST,
THEN the system shall include a "Model Health" section containing:
- Current prompt version and its accuracy (last 30 days)
- Active A/B test status (if any) with preliminary results
- Current factor weights vs default weights
- Signal type accuracy breakdown

**REQ-006-014** (Event-Driven):
WHEN any self-improvement action occurs (prompt generation, A/B test resolution, weight update),
THEN the system shall create a log entry in a new `ImprovementLog` table with: action_type, details (JSON), timestamp.

**REQ-006-015** (Event-Driven):
WHEN an API request is made to `GET /api/fund/model-health`,
THEN the system shall return the current model health status including: prompt version info, A/B test status, factor weights, accuracy metrics by signal type, and improvement history (last 10 entries).

---

## Non-Functional Requirements

**NFR-001 (API Budget Efficiency)**:
The entire self-improvement loop shall consume no more than 3 Gemini API calls per week (1 for prompt analysis, 1 for prompt generation, 1 buffer).

**NFR-002 (Safety / No Regression)**:
No automated change shall break the existing signal generation flow. All new scheduler jobs shall have independent error handling with `@retry_with_backoff`.

**NFR-003 (Backward Compatibility)**:
Existing signals without `prompt_version` shall be treated as belonging to the baseline control version ("v1.0-baseline").

**NFR-004 (Observability)**:
All self-improvement decisions shall be logged with full context (input data, computed metrics, action taken) for post-hoc analysis.

**NFR-005 (Graceful Degradation)**:
IF Gemini API fails during prompt generation, the system shall skip the improvement cycle and retry next week. No partial state shall be left.

---

## System Design

### Data Flow Diagram

```
                     Daily 18:00 KST
                          |
                          v
               +---------------------+
               | signal_verifier.py  |
               | verify_signals()    |
               | sets is_correct,    |
               | error_category      |
               +----------+----------+
                          |
                          v
               +---------------------+
               | improvement_loop.py | <-- NEW SERVICE
               | (FailureAggregator) |
               +----------+----------+
                          |
            +-------------+-------------+
            |                           |
            v                           v
  Weekly (Sun 22:00)           Monthly (1st 23:00)
            |                           |
            v                           v
  +-------------------+     +------------------------+
  | PromptImprover    |     | FactorWeightAdapter    |
  | - analyze_failures|     | - correlate_factors()  |
  | - generate_prompt |     | - compute_new_weights()|
  | - register_version|     | - apply_dampened()     |
  +--------+----------+     +-----------+------------+
           |                            |
           v                            v
  +-------------------+     +------------------------+
  | PromptVersion     |     | FactorWeightHistory    |
  | (treatment entry) |     | (new weights record)   |
  +--------+----------+     +------------------------+
           |
           v
  +-------------------+
  | A/B Test Active   |
  | 50/50 split by    |
  | stock_id parity   |
  +--------+----------+
           |
    Weekly evaluation
           |
           v
  +-------------------+
  | evaluate_ab_test()|  <-- EXISTING (prompt_versioner.py)
  | z-test + promote  |
  +-------------------+
```

### New Service: `improvement_loop.py`

Central orchestrator for the self-improvement cycle. Contains:

- `aggregate_failure_patterns(db, days=30)` -- Collects and summarizes signal outcomes
- `generate_improved_prompt(db, failure_summary)` -- Calls Gemini to create treatment prompt
- `register_treatment_version(db, prompt_text, rationale)` -- Creates PromptVersion entry
- `adapt_factor_weights(db, days=60)` -- Correlates factors with outcomes, updates weights
- `resolve_stale_ab_test(db, max_days=30)` -- Auto-closes inconclusive A/B tests
- `get_model_health(db)` -- Aggregates all model metrics for API/briefing

### New Scheduler Jobs

| Job ID                   | Schedule              | Function                        |
|--------------------------|-----------------------|---------------------------------|
| `failure_aggregation`    | Daily 18:30 KST       | `aggregate_failure_patterns()`  |
| `prompt_improvement`     | Sunday 22:00 KST      | `generate_improved_prompt()`    |
| `ab_test_evaluation`     | Sunday 22:30 KST      | `evaluate_ab_test()` + stale check |
| `factor_weight_adapt`    | Monthly 1st 23:00 KST | `adapt_factor_weights()`        |

---

## DB Schema Changes

### New Table: `factor_weight_history`

| Column         | Type          | Description                           |
|----------------|---------------|---------------------------------------|
| id             | SERIAL PK     | Auto-increment ID                     |
| news_sentiment | FLOAT NOT NULL| Weight for news_sentiment factor      |
| technical      | FLOAT NOT NULL| Weight for technical factor           |
| supply_demand  | FLOAT NOT NULL| Weight for supply_demand factor       |
| valuation      | FLOAT NOT NULL| Weight for valuation factor           |
| correlations   | TEXT          | JSON: per-factor correlation values   |
| sample_size    | INTEGER       | Number of signals used for computation|
| is_active      | BOOLEAN       | Whether these weights are currently active |
| created_at     | TIMESTAMP(tz) | Creation timestamp                    |

### New Table: `improvement_logs`

| Column      | Type          | Description                                |
|-------------|---------------|--------------------------------------------|
| id          | SERIAL PK     | Auto-increment ID                          |
| action_type | VARCHAR(30)   | prompt_generation / ab_resolution / weight_update / failure_aggregation |
| details     | TEXT          | JSON: full context of the action           |
| created_at  | TIMESTAMP(tz) | Timestamp                                  |

### Modified Table: `prompt_versions`

| Column         | Type     | Change    | Description                        |
|----------------|----------|-----------|------------------------------------|
| prompt_template| TEXT     | ADD       | Actual prompt text for the version |
| generation_source | TEXT  | ADD       | JSON: failure summary that triggered this version |

---

## Exclusions (What NOT to Build)

- Shall NOT implement full ML model training or neural network inference (reason: OCI micro VM lacks GPU/memory; factor weight correlation is sufficient)
- Shall NOT implement real money trading integration (reason: out of scope, regulatory concerns)
- Shall NOT add new AI providers beyond existing Gemini/OpenRouter/Groq (reason: provider management is separate concern)
- Shall NOT modify the existing signal generation flow in `fund_manager.py` beyond adding prompt version selection (reason: minimize blast radius)
- Shall NOT implement real-time prompt switching mid-day (reason: consistency within daily batch; version changes take effect next signal generation cycle)
- Shall NOT auto-tune ATR multipliers for TP/SL in this SPEC (reason: deferred to future iteration after 100+ closed trades, as noted in product.md)

---

## Expert Consultation Recommendations

- **expert-backend**: API design for `/api/fund/model-health`, scheduler integration, DB migration strategy
- **expert-testing**: Statistical validation of correlation-based weight adaptation, edge cases in z-test with small samples

---

## Traceability

| Requirement   | Service File              | Test File                          |
|---------------|---------------------------|------------------------------------|
| REQ-006-001   | improvement_loop.py       | test_improvement_loop.py           |
| REQ-006-003   | improvement_loop.py       | test_improvement_loop.py           |
| REQ-006-006   | fund_manager.py (modified)| test_fund_manager.py               |
| REQ-006-010   | improvement_loop.py       | test_improvement_loop.py           |
| REQ-006-013   | daily_briefing.py (modified)| test_daily_briefing.py           |
| REQ-006-015   | fund_router.py (modified) | test_fund_router.py                |
