# SPEC-AI-006: Implementation Plan

| Field       | Value         |
|-------------|---------------|
| SPEC ID     | SPEC-AI-006   |
| Status      | Planned       |

---

## Implementation Strategy

This SPEC leverages heavily from existing infrastructure. The key insight is that ~70% of the self-improvement pipeline already exists (signal verification, A/B test evaluation, prompt version management, ML feature collection). The work is primarily about **connecting the dots** and adding the missing orchestration layer.

### Dependency Analysis

```
Existing (no changes needed):
  - signal_verifier.py          (verify_signals, error classification)
  - prompt_versioner.py         (evaluate_ab_test, _promote_version, z-test)
  - ml_feature_engineering.py   (capture_daily_features)
  - FundSignal model            (is_correct, error_category, factor_scores, prompt_version)
  - PromptVersion model         (A/B test fields)

Existing (minor modifications):
  - fund_manager.py             (add prompt version selection for A/B split)
  - factor_scoring.py           (load weights from DB instead of DEFAULT_WEIGHTS)
  - scheduler.py                (add 4 new jobs)
  - daily_briefing.py           (add model health section)
  - fund_router.py              (add /model-health endpoint)

New:
  - improvement_loop.py         (central orchestration service)
  - FactorWeightHistory model   (new table)
  - ImprovementLog model        (new table)
  - Alembic migration           (2 new tables + 2 columns on prompt_versions)
```

---

## Milestones

### Primary Goal: Failure Pattern Aggregation + Monitoring

**Scope**: REQ-006-001, REQ-006-002, REQ-006-013, REQ-006-014, REQ-006-015

**Tasks**:
1. Create `improvement_loop.py` with `aggregate_failure_patterns()` function
2. Create `ImprovementLog` model and Alembic migration
3. Create `FactorWeightHistory` model (needed for Phase 4, but define schema now)
4. Add `failure_aggregation` scheduler job (daily 18:30 KST)
5. Add `GET /api/fund/model-health` endpoint
6. Add "Model Health" section to daily briefing generator
7. Write tests for aggregation logic

**Rationale**: This milestone produces immediate value (visibility into model performance) and creates the data foundation for subsequent phases. No Gemini API calls consumed. Can be deployed independently.

### Secondary Goal: Prompt Improvement + A/B Test Activation

**Scope**: REQ-006-003, REQ-006-004, REQ-006-005, REQ-006-006, REQ-006-007, REQ-006-008, REQ-006-009

**Tasks**:
1. Add `prompt_template` and `generation_source` columns to `prompt_versions` table
2. Implement `generate_improved_prompt()` in `improvement_loop.py`
   - Build meta-prompt from failure patterns + worst signals
   - Call Gemini via existing `ai_client.py`
   - Register new PromptVersion as treatment
3. Implement `resolve_stale_ab_test()` for 30-day timeout
4. Modify `fund_manager.py` signal generation to select prompt version based on stock_id parity
5. Add `prompt_improvement` scheduler job (Sunday 22:00 KST)
6. Add `ab_test_evaluation` scheduler job (Sunday 22:30 KST)
7. Seed initial baseline PromptVersion ("v1.0-baseline") if not exists
8. Write tests for prompt generation and A/B routing

**Rationale**: This is the core self-improvement mechanism. Depends on Primary Goal for failure pattern data. Requires careful testing to ensure existing signal flow is not disrupted.

**Risk**: Gemini rate limit (20/day). Mitigation: weekly batch (1-2 calls), scheduled at 22:00 KST when daily quota is likely available.

### Final Goal: Factor Weight Adaptation

**Scope**: REQ-006-010, REQ-006-011, REQ-006-012

**Tasks**:
1. Implement `adapt_factor_weights()` in `improvement_loop.py`
   - Pearson correlation calculation (no scipy dependency -- manual implementation)
   - Weight normalization with [0.10, 0.40] bounds
   - Dampening logic (max 0.10 change per cycle)
2. Modify `factor_scoring.py` to load active weights from `FactorWeightHistory` table
   - Cache weights in module-level variable with TTL (1 hour)
   - Fall back to DEFAULT_WEIGHTS if no active record
3. Add `factor_weight_adapt` scheduler job (monthly 1st 23:00 KST)
4. Write tests for correlation calculation, normalization, and dampening

**Rationale**: Monthly cadence ensures sufficient data accumulation (30+ signals). Dampening prevents sudden scoring disruptions. Separate from prompt improvement to isolate effects.

**Risk**: Insufficient verified signals for meaningful correlation. Mitigation: 30-signal minimum threshold; skip cycle if not met.

---

## Technical Approach

### Failure Pattern Aggregation

Query pattern:
```sql
-- 최근 30일 검증 완료 시그널 집계
SELECT
  signal_type,
  COUNT(*) as total,
  SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) as correct,
  AVG(return_pct) as avg_return,
  error_category,
  COUNT(error_category) as error_count
FROM fund_signals
WHERE verified_at IS NOT NULL
  AND verified_at >= NOW() - INTERVAL '30 days'
GROUP BY signal_type, error_category
```

### Prompt Meta-Prompt Design

The meta-prompt for Gemini will follow this structure:
1. System context: "You are an AI prompt engineer optimizing stock signal generation prompts."
2. Current prompt template (from PromptVersion.prompt_template)
3. Performance data: accuracy %, error distribution, worst signals
4. Instruction: "Generate an improved version addressing these failure patterns. Explain each change."

This uses 1 Gemini call per week.

### A/B Split Logic

```python
# fund_manager.py 수정 -- 시그널 생성 시 버전 선택
# stock_id 짝수 = control, 홀수 = treatment
control, treatment = get_ab_versions(db)
version = treatment if (stock_id % 2 == 1 and treatment) else control
```

### Pearson Correlation (scipy 미사용)

```python
# 수동 Pearson 상관계수 계산
def pearson_correlation(x: list[float], y: list[float]) -> float:
    n = len(x)
    sum_x, sum_y = sum(x), sum(y)
    sum_xy = sum(xi * yi for xi, yi in zip(x, y))
    sum_x2 = sum(xi**2 for xi in x)
    sum_y2 = sum(yi**2 for yi in y)
    num = n * sum_xy - sum_x * sum_y
    den = ((n * sum_x2 - sum_x**2) * (n * sum_y2 - sum_y**2)) ** 0.5
    return num / den if den != 0 else 0.0
```

---

## Architecture Impact

### Files Modified (5)

| File | Change |
|------|--------|
| `backend/app/services/fund_manager.py` | Add prompt version selection in signal generation |
| `backend/app/services/factor_scoring.py` | Load active weights from DB, cache with TTL |
| `backend/app/services/scheduler.py` | Add 4 new scheduler jobs |
| `backend/app/services/daily_briefing.py` | Add model health section |
| `backend/app/routers/fund.py` | Add GET /api/fund/model-health endpoint |

### Files Created (4)

| File | Purpose |
|------|---------|
| `backend/app/services/improvement_loop.py` | Central self-improvement orchestration |
| `backend/app/models/factor_weight.py` | FactorWeightHistory model |
| `backend/app/models/improvement_log.py` | ImprovementLog model |
| `backend/alembic/versions/0XX_spec_ai_006_*.py` | Migration for new tables + columns |

### Files Tested (3 new)

| File | Scope |
|------|-------|
| `backend/tests/test_improvement_loop.py` | Aggregation, prompt generation, weight adaptation |
| `backend/tests/test_factor_weight_adapt.py` | Correlation, normalization, dampening |
| `backend/tests/test_model_health_api.py` | API endpoint response |

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Gemini rate limit exceeded | Prompt generation fails | Weekly batch + 22:00 KST timing; skip on failure, retry next week |
| Insufficient verified signals | Correlation is meaningless | Minimum threshold checks (20 for prompt, 30 for weights) |
| Bad prompt variant degrades accuracy | Signal quality drops | A/B test isolates impact; auto-revert via z-test (loser deactivated) |
| Factor weight oscillation | Unstable scoring | Dampening (max 0.10 change/cycle) + [0.10, 0.40] bounds |
| New scheduler jobs conflict with existing ones | Timing overlap | Stagger times (18:30, 22:00, 22:30, 23:00) away from existing jobs |
