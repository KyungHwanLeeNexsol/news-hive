# SPEC-AI-006: Acceptance Criteria

| Field       | Value         |
|-------------|---------------|
| SPEC ID     | SPEC-AI-006   |
| Status      | Planned       |

---

## Phase 1: Failure Pattern Aggregation

### AC-001: Daily Failure Aggregation

**Given** at least 5 verified signals exist from the past 30 days
**When** the `failure_aggregation` scheduler job runs at 18:30 KST
**Then** the system creates an `ImprovementLog` entry with action_type="failure_aggregation" containing:
- Total verified count and accuracy percentage
- Error category distribution as JSON
- Per-signal_type accuracy breakdown
- Average return_pct for correct vs incorrect signals
- Factor score averages for correct vs incorrect groups

### AC-002: Low Accuracy Warning

**Given** signal_type "sector_ripple" has 10 verified signals with accuracy below 50%
**When** the failure aggregation runs
**Then** the system logs a WARNING-level message: "Signal type sector_ripple accuracy below threshold: {accuracy}%"

### AC-003: Model Health API Endpoint

**Given** the system has failure aggregation data and at least 1 active PromptVersion
**When** a GET request is made to `/api/fund/model-health`
**Then** the response contains:
```json
{
  "prompt_version": {
    "current": "v1.0-baseline",
    "accuracy_30d": 62.5,
    "total_signals_30d": 40
  },
  "ab_test": {
    "active": false,
    "control": "v1.0-baseline",
    "treatment": null
  },
  "factor_weights": {
    "news_sentiment": 0.25,
    "technical": 0.25,
    "supply_demand": 0.25,
    "valuation": 0.25,
    "source": "default"
  },
  "signal_type_accuracy": {
    "sector_ripple": {"total": 35, "accuracy": 60.0},
    "disclosure_impact": {"total": 3, "accuracy": 66.7},
    "gap_pullback_candidate": {"total": 2, "accuracy": 50.0}
  },
  "improvement_history": [...]
}
```
**And** the response status code is 200

### AC-004: Model Health in Daily Briefing

**Given** the daily briefing generation runs at 08:30 KST
**When** the briefing content is generated
**Then** the briefing includes a "Model Health" section with current prompt version, accuracy, and active A/B test status

---

## Phase 2: Prompt Improvement + A/B Test

### AC-005: Automatic Prompt Generation

**Given** 20+ verified signals exist since the last PromptVersion was created
**And** no active A/B test is running (no treatment version exists)
**When** the `prompt_improvement` scheduler job runs on Sunday 22:00 KST
**Then** the system:
1. Calls Gemini API with a meta-prompt containing failure patterns
2. Creates a new `PromptVersion` record with is_active=True, is_control=False
3. Stores the generated prompt text in `prompt_template` column
4. Stores the failure summary in `generation_source` column
5. Creates an `ImprovementLog` entry with action_type="prompt_generation"

### AC-006: Skip When A/B Test Active

**Given** an active treatment version exists in `prompt_versions`
**When** the `prompt_improvement` scheduler job runs
**Then** the system skips prompt generation and logs: "A/B test already active, skipping prompt generation"

### AC-007: Skip When Insufficient Data

**Given** only 15 verified signals exist since the last PromptVersion was created
**When** the `prompt_improvement` scheduler job runs
**Then** the system skips and logs: "Insufficient signals (15/20) for prompt improvement"

### AC-008: A/B Split Assignment

**Given** an active A/B test exists with control="v1.0-baseline" and treatment="v1.1-improved"
**When** a signal is generated for stock_id=100 (even)
**Then** the signal uses the control version ("v1.0-baseline")

**Given** an active A/B test exists
**When** a signal is generated for stock_id=101 (odd)
**Then** the signal uses the treatment version ("v1.1-improved")

### AC-009: A/B Test Auto-Evaluation

**Given** control has 12 verified signals and treatment has 11 verified signals
**When** the `ab_test_evaluation` scheduler job runs on Sunday 22:30 KST
**Then** the system calls `evaluate_ab_test()` and:
- If p_value < 0.05: winner is promoted, loser is deactivated
- If p_value >= 0.05: no action taken, test continues

### AC-010: Stale A/B Test Resolution

**Given** an A/B test has been active for 31 days
**And** p_value >= 0.05 (not statistically significant)
**When** the `ab_test_evaluation` job runs
**Then** the treatment version is deactivated
**And** an `ImprovementLog` entry is created with action_type="ab_resolution" and details containing "result": "inconclusive"

### AC-011: Gemini API Failure Handling

**Given** the Gemini API returns an error during prompt generation
**When** the `prompt_improvement` job is running
**Then** the system:
1. Logs the error at ERROR level
2. Does NOT create any partial PromptVersion record
3. Creates an `ImprovementLog` with action_type="prompt_generation" and details containing "status": "failed"
4. The next weekly run retries normally

---

## Phase 3: Factor Weight Adaptation

### AC-012: Monthly Weight Computation

**Given** 35 verified signals exist from the past 60 days with valid factor_scores
**When** the `factor_weight_adapt` job runs on the 1st of the month at 23:00 KST
**Then** the system:
1. Computes Pearson correlation for each of 4 factors vs is_correct
2. Normalizes to weights summing to 1.0
3. Applies bounds [0.10, 0.40] per factor
4. Stores in `FactorWeightHistory` with is_active=True
5. Sets previous active record to is_active=False
6. Creates `ImprovementLog` with action_type="weight_update"

### AC-013: Weight Dampening

**Given** current weights are {news_sentiment: 0.25, technical: 0.25, supply_demand: 0.25, valuation: 0.25}
**And** computed target weights are {news_sentiment: 0.40, technical: 0.15, supply_demand: 0.30, valuation: 0.15}
**When** weight adaptation runs
**Then** applied weights are half-stepped: {news_sentiment: 0.325, technical: 0.20, supply_demand: 0.275, valuation: 0.20}
(each factor moves at most half the distance to target, then re-normalized to sum=1.0)

### AC-014: Insufficient Data Skip

**Given** only 20 verified signals exist from the past 60 days
**When** the `factor_weight_adapt` job runs
**Then** the system skips and logs: "Insufficient signals (20/30) for weight adaptation"

### AC-015: Factor Scoring Loads DB Weights

**Given** a `FactorWeightHistory` record exists with is_active=True
**When** `compute_composite_score()` is called without explicit weights parameter
**Then** the function uses weights from the active DB record instead of DEFAULT_WEIGHTS

**Given** no `FactorWeightHistory` record with is_active=True exists
**When** `compute_composite_score()` is called
**Then** the function falls back to DEFAULT_WEIGHTS ({0.25, 0.25, 0.25, 0.25})

---

## Quality Gates

### Definition of Done

- [ ] All 15 acceptance criteria pass
- [ ] 4 new scheduler jobs registered and tested
- [ ] Alembic migration applies cleanly on fresh DB and existing DB
- [ ] `GET /api/fund/model-health` returns valid response
- [ ] Daily briefing includes model health section
- [ ] No existing tests break (pytest full suite passes)
- [ ] Gemini API calls in improvement_loop.py use existing ai_client.py fallback chain
- [ ] All new functions have type hints and docstrings
- [ ] Test coverage for new files >= 85%

### Verification Methods

| Criterion | Method |
|-----------|--------|
| Failure aggregation correctness | Unit test with mock signals (varying is_correct, error_category, signal_type) |
| Prompt generation flow | Integration test with mocked Gemini response |
| A/B split determinism | Unit test: stock_id=100 -> control, stock_id=101 -> treatment |
| Weight correlation math | Unit test with known factor scores and outcomes |
| Dampening bounds | Parametrized test with extreme weight targets |
| Scheduler registration | Integration test verifying job IDs in scheduler |
| API response schema | Pydantic response model validation test |
| Backward compatibility | Test with signals having prompt_version=NULL |
