# SPEC-AI-023 Research: Near-Limit-Up Carry-Forward Signal

## 1. Problem Statement and Live Evidence

### 1.1 Trigger Case (2026-05-29 KST)

| Stock | Code | Close Change | Limit-Up? | Surge Signal Today |
|-------|------|---------------|-----------|---------------------|
| LG씨엔에스 | 064400 | +29.91% | No (1 tick below) | No |
| (representative) | — | +25.0% ~ +29.99% | No | Often No |

These stocks finished within the near-limit-up band (`+25% ~ +29.99%`) but received no surge_candidate signal because the existing 4 detectors (theme cluster, volume+news combo, disclosure pattern, immediate disclosure) all key off news/disclosure/volume — not the closing price change rate itself.

Industry empirical observation (and the user's stated rationale): stocks that close just below the +30% upper limit typically carry leftover buying pressure into the next trading day, leading to a statistically meaningful probability of further gains at open. The current pipeline has no path to convert this signal into a buy candidate.

### 1.2 Why Existing `_carry_over_strong_signals` Does Not Cover This

The existing carry-over mechanism in `app/services/fund_manager._carry_over_strong_signals` (around line 1430) only re-emits **stocks that already had a surge_candidate signal yesterday**, with confidence decayed by 5%. The relevant filter:

```python
already_today = db.query(FundSignal).filter(
    FundSignal.stock_id == prev.stock_id,
    FundSignal.signal_type == "surge_candidate",
    FundSignal.created_at >= today_start,
).first()
if already_today:
    continue
```

If a stock had no prior signal, it is invisible to this mechanism. The +29% case from 2026-05-29 falls exactly in this gap.

---

## 2. Existing Pipeline and Integration Surface

### 2.1 Service Topology (after SPEC-AI-022)

```
scheduler.py (15:20 KST weekday)
  └─► fund_manager.run_surge_signal_generation()                       [line 2842]
        └─► gather_surge_candidates(...)
              └─► merge + ensemble + threshold → surge_candidate signals (persist)
        └─► db.commit()                                                [line 2868]
        └─► _run_coverage_expansion(db, candidates)                    [line 2866 → 3654]
              ├─► try: propagate_theme_group_signals (SPEC-AI-022)
              └─► try: detect_volume_anomaly_dormant_stocks (SPEC-AI-022)
```

`_run_coverage_expansion` runs in two independent `try/except` blocks, each fault-isolated from the surge_candidate commit. This is the proven integration pattern from SPEC-AI-022. SPEC-AI-023 adds a third `try/except` block in the same function, after `detect_volume_anomaly_dormant_stocks`.

### 2.2 surge_candidate signal_type Reuse Rationale

Three options were considered:

| Option | signal_type | get_today_signals filter | Buy queue inclusion |
|--------|-------------|---------------------------|---------------------|
| A | `surge_candidate` (reuse) | passes automatically | YES (immediate) |
| B | `near_limit_up_carry` (new) | requires code change | NO until filter updated |
| C | `surge_candidate` + `paper_executed=False` | passes filter | NO (excluded by paper_executed flag downstream) |

The user explicitly requested **buy queue inclusion** (the signal should let the next morning's 09:05 batch buy the stock). Therefore Option A is selected. The new signal is differentiated by `surge_metadata.surge_basis == ["near_limit_up_carry"]`, which provides full backtest observability without affecting downstream consumers.

This is the **opposite** policy from SPEC-AI-022 (`theme_propagation`, `volume_anomaly` use new signal_types with `paper_executed=False`) because the conviction level is different: a +29% close is a strong public price signal, not a soft propagated signal.

---

## 3. Data Source: `fetch_current_price_with_change_sync`

### 3.1 Function Signature (from `naver_finance.py:810`)

```python
def fetch_current_price_with_change_sync(stock_code: str) -> dict | None:
    """Returns {"current_price": int, "change_rate": float} or None on failure."""
```

- Source: `https://m.stock.naver.com/api/stock/{code}/integration` (Naver mobile)
- Timeout: 5 seconds (httpx.Client)
- On HTTP error / parse error: returns None, exception suppressed
- `change_rate` is already the closing percentage change (negative for losses, positive for gains)

### 3.2 Why Use This Over `fetch_stock_price_history_sync`

The user's spec text initially suggested `fetch_stock_price_history_sync(code, pages=1)` to derive close-on-close change. Analysis:

| Aspect | `fetch_stock_price_history_sync` | `fetch_current_price_with_change_sync` |
|--------|----------------------------------|------------------------------------------|
| Returns | `list[PriceRecord]` (latest-first) | `dict` with current price + change_rate |
| Has change_rate built-in | No (must compute `(records[0].close - records[1].close) / records[1].close * 100`) | Yes (direct field) |
| Latency | ~300-500ms (HTML parse) | ~150-300ms (JSON) |
| Cache | Hit via `_price_cache` (TTL=1h) | No cache (fresh each call) |
| Cost per call | 1 HTTP request | 1 HTTP request |
| Accuracy at close | Depends on Naver page caching | Direct from mobile API |

For SPEC-AI-023, accuracy at the moment of decision (post-15:30 KST close) matters more than caching, and the `change_rate` is already computed by Naver. The SPEC mandates `fetch_current_price_with_change_sync`. (If batch throughput becomes a concern, the RUN phase can switch to `_price_cache.data` mining.)

### 3.3 Rate Limiting

`fetch_current_price_with_change_sync` has no built-in rate limit. Worst case: 500 stocks × 200ms = 100 seconds of sequential blocking. This is acceptable for a once-per-day batch but justifies the `max_candidates_per_day=500` cap (REQ-AI023-001 (b)).

---

## 4. Confidence Formula Analysis

### 4.1 Formula

`confidence = round(change_rate / 30.0 * 0.5, 4)`

| change_rate | confidence | Rationale |
|-------------|-----------|-----------|
| 25.0% | 0.4167 | Lower bound of band |
| 27.0% | 0.4500 | Mid-band |
| 28.0% | 0.4667 | Strong |
| 29.0% | 0.4833 | Very strong |
| 29.99% | 0.4998 | Just below limit-up |
| 30.0% | (excluded) | Limit-up itself excluded |

### 4.2 Comparison with Other surge_candidate confidence sources

| Source | confidence range | paper_executed default |
|--------|------------------|--------------------------|
| Ensemble pipeline (SPEC-AI-012) | 0.45+ (`min_score_for_signal`) | True |
| `_carry_over_strong_signals` (decay) | 0.265+ (`yesterday * 0.95`) | True (inherited) |
| Theme propagation (SPEC-AI-022) | 0.25 (fixed) | False |
| Volume anomaly (SPEC-AI-022) | `min(ratio/10, 0.40)` | False |
| **SPEC-AI-023 (this)** | 0.4167 ~ 0.4998 | True |

The formula caps at 0.50 because the underlying observation is a single-day price move. A higher confidence would inflate the signal relative to multi-detector ensemble outputs (which can reach 0.85+ via consensus multipliers). Capping at 0.50 ensures the surge_trading_service's buy ordering logic does not over-weight this single-factor signal.

### 4.3 Threshold against `min_probability=0.30` (get_today_signals)

The minimum confidence of 0.4167 (at change_rate=25%) is comfortably above `min_probability=0.30`, so all generated signals pass the buy queue filter. This is intentional: if the user wanted these in the buy queue, the formula must clear the threshold.

---

## 5. Duplicate Prevention Logic

### 5.1 Today's Signal Lookup Pattern (from SPEC-AI-022)

The existing pattern queries by `created_at >= today_start` (KST 00:00:00) and `signal_type IN (...)`:

```python
today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
# Note: SPEC-AI-022 uses UTC, but for KST market logic the boundary should ideally be KST 00:00.
# For consistency with existing code, SPEC-AI-023 follows the same UTC-based today_start.
```

### 5.2 Exclusion Set

REQ-AI023-001 excludes a stock if **any** of these signals exists for the stock today:
- `signal_type='surge_candidate'` (includes carry_over + ensemble + this SPEC's own past adds within same run)
- `signal_type='theme_propagation'`
- `signal_type='volume_anomaly'`

The exclusion is broader than just `surge_candidate` because the user's intent is "convert near-limit-up into a buy candidate ONLY IF no other detector has already produced a signal." If theme_propagation already flagged the stock, no additional signal is needed.

### 5.3 Implementation Optimization

To avoid N+1 queries, the implementation should pre-fetch the set of stock_ids that already have any of these three signal_types today, via a single grouped query:

```sql
SELECT DISTINCT stock_id FROM fund_signals
WHERE created_at >= :today_start
  AND signal_type IN ('surge_candidate', 'theme_propagation', 'volume_anomaly');
```

This pattern is consistent with `detect_volume_anomaly_dormant_stocks` (line 1364-1376 of surge_detector.py).

---

## 6. Market Cap Filter and Candidate Cap

### 6.1 Why min_market_cap_eok=300?

Aligns with `VolumeAnomalyConfig.min_market_cap=300` (SPEC-AI-022). Sub-300억원 stocks are micro-caps where +29% moves are often manipulation or thin-liquidity spikes — exactly the noise this SPEC should filter out.

### 6.2 Why max_candidates_per_day=500?

- Operational: ~500 stocks × ~200ms API latency = ~100 seconds (acceptable for once/day batch).
- Statistical: KOSPI + KOSDAQ has ~2600 listed stocks (per CLAUDE.md note: "stocks 2,605"). Top 500 by market cap covers ~90% of total market cap and excludes micro-cap noise.
- Pragmatic: 500 stocks × ~5% probability of being in the +25% ~ +29.99% band on any given day = ~25 candidates evaluated. Realistic average is ~3-15 actual signals/day.

### 6.3 Why allow `market_cap IS NULL`?

`Stock.market_cap` is updated by a separate batch and can be stale or NULL for newly-listed stocks. The existing `detect_theme_news_cluster` allows NULL (line 263 of surge_detector.py via `or_(Stock.market_cap >= min_market_cap_eok, Stock.market_cap.is_(None))`). SPEC-AI-023 follows the same convention to avoid excluding newly-listed candidates with strong opening-day moves.

---

## 7. Scheduler Timing Considerations

### 7.1 Current Schedule

`run_surge_signal_generation` runs weekday at 15:20 KST (per scheduler.py).

### 7.2 Concern: Market Close is 15:30 KST

If the detector runs at 15:20, the closing price is not yet final. Three options:

| Option | Impact |
|--------|--------|
| A. Keep 15:20 schedule, accept intra-day price | Close_rate may not reflect true close; some +25% calls may be premature |
| B. Move scheduler to 15:35 KST | Affects all of `run_surge_signal_generation` — out of scope for this SPEC |
| C. Add separate 15:35 cron just for this detector | Adds complexity; defer to follow-up |

SPEC-AI-023 takes Option A but notes the concern. The scheduler adjustment is explicitly excluded from this SPEC (see Exclusions section). For initial deployment, the 15:20 run will use the most recent intraday `change_rate`, which on most days converges to the close within 0.1-0.5% by 15:20. False positives at the threshold boundary (e.g., +24.9% → +25.1% by close) are acceptable initial noise.

---

## 8. @MX Tag Recommendations

| Function | Tag | Reason |
|----------|-----|--------|
| `detect_near_limit_up_carries` | `@MX:NOTE` + `@MX:SPEC: SPEC-AI-023 REQ-001` | New SPEC implementation marker |
| `detect_near_limit_up_carries` | `@MX:WARN` + `@MX:REASON: 외부 API 일 500회 동기 호출, naver_finance 레이트 리미트 위험` | External API call density |
| `_run_coverage_expansion` | (update existing tag or none) | Already has integration comment from SPEC-AI-022; just add a one-line note about the third try block |
| `NearLimitUpConfig` | `@MX:NOTE` + `@MX:SPEC: SPEC-AI-023 REQ-002` | Config class marker |

Per `mx-tag-protocol.md`:
- WARN requires `@MX:REASON`
- ANCHOR requires `fan_in >= 3` — not applicable here (fan_in=1)
- TODO is not needed since the SPEC will be fully implemented (no deferred work)

---

## 9. Test Mock Strategy

### 9.1 `fetch_current_price_with_change_sync` patching

The function is called directly inside `detect_near_limit_up_carries`. There is no existing provider injection point (unlike `_price_change_provider` for the volume_combo detector). Two approaches:

| Approach | Pros | Cons |
|----------|------|------|
| A. `monkeypatch` the module function | Standard pytest pattern; matches existing test style | Couples test to import path |
| B. Add a `_near_limit_up_price_provider` injection (like `_price_change_provider`) | Cleaner abstraction | Adds production code complexity for test-only purpose |

SPEC-AI-023 selects Approach A for simplicity. Tests use `monkeypatch.setattr("app.services.surge_detector.fetch_current_price_with_change_sync", mock_fn)`.

### 9.2 DB Mock Strategy

Use the existing pytest SQLite in-memory pattern (consistent with `test_theme_propagation.py`, `test_volume_anomaly.py`). Seed:
- N stocks with varied `market_cap`
- M FundSignal rows with varied `signal_type` and `created_at`

### 9.3 Coverage Targets

- `detect_near_limit_up_carries`: 90%+ (covers AC-001 ~ AC-006, AC-008 ~ AC-010)
- `_run_coverage_expansion` modification: 85%+ (covers AC-007, AC-011, AC-012)
- `NearLimitUpConfig`: trivial — 100% by instantiation

---

## 10. Comparison Matrix: SPEC-AI-023 vs Existing Mechanisms

| Mechanism | Trigger | signal_type | confidence | paper_executed | Source |
|-----------|---------|-------------|------------|-----------------|--------|
| Ensemble (SPEC-AI-012) | News + volume + disclosure ensemble | `surge_candidate` | `>=0.45` (ensemble) | True | `gather_surge_candidates` |
| Carry-over (SPEC-AI-012) | Prior surge_candidate decay | `surge_candidate` | `prev × 0.95` | True | `_carry_over_strong_signals` |
| Theme propagation (SPEC-AI-022) | Anchor `theme_cluster_score >= 0.80` | `theme_propagation` | `0.25` fixed | False | `propagate_theme_group_signals` |
| Volume anomaly (SPEC-AI-022) | Dormant + volume_ratio >= 5 | `volume_anomaly` | `min(ratio/10, 0.40)` | False | `detect_volume_anomaly_dormant_stocks` |
| **Near-limit-up carry (SPEC-AI-023)** | **change_rate ∈ [25, 30)** | **`surge_candidate`** | **`change_rate / 30 × 0.5`** | **True** | **`detect_near_limit_up_carries`** |

The new mechanism is orthogonal to all four existing mechanisms in trigger logic, but reuses the `surge_candidate` signal_type for direct buy-queue inclusion.

---

## 11. Operational Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Naver API rate limit hit on 500 sequential calls | Medium | `max_candidates_per_day=500` cap; document concern; can downshift via config |
| False positive at exactly +25.0% boundary | Low | Threshold is intentional; users can tune `near_limit_up_min_pct` |
| Intra-day vs close-of-day change_rate discrepancy at 15:20 | Medium | Documented; scheduler adjustment is follow-up work |
| Double-counting if same SPEC runs twice in one day | Low | Duplicate check (REQ-AI023-001) excludes existing surge_candidate; second run is no-op |
| New signal type pollutes `get_today_signals` quality if change_rate < 30 stocks always have negative next-day return | Medium | `paper_executed=True` enables backtest tracking; first 30 days are observation-only via dashboard; explicit follow-up SPEC for accuracy validation |
| `_run_coverage_expansion` runs serially; volume_anomaly already takes ~50-150s; adding another 100s pushes batch beyond market close | Low | Each block independent; coverage_expansion is post-commit so latency does not affect surge_candidate publication |

---

## 12. Out-of-Scope / Deferred Work

Items identified during research that are NOT in this SPEC's scope:

1. **Scheduler timing adjustment** (15:20 → 15:35): operational change, separate ticket.
2. **Backtest accuracy validation** for `near_limit_up_carry` signals: requires 30+ days of paper-traded data; follow-up SPEC.
3. **Dynamic threshold tuning** (`near_limit_up_min_pct` adjusted by market regime): explicit exclusion; future ML-driven SPEC.
4. **Multi-day momentum patterns** (e.g., 3 consecutive days of +20%): different feature; future SPEC.
5. **Volume + price combined criterion**: this SPEC is price-only intentionally. Volume is covered by `volume_anomaly` (SPEC-AI-022) under different conditions.
6. **Upper limit (+30%, hit) handling**: limit-up stocks have different next-day dynamics (often pullback). Excluded by design.

---

## 13. Related Files (Read for Implementation)

| Path | Why |
|------|-----|
| `backend/app/services/surge_detector.py` | Add new function; consult `detect_volume_anomaly_dormant_stocks` (line 1321) as the template (similar shape: iterate stocks, check existing signals, create FundSignal, fault-isolated) |
| `backend/app/services/fund_manager.py:3654` | `_run_coverage_expansion` integration site |
| `backend/app/services/fund_manager.py:1430` | `_carry_over_strong_signals` for confidence pattern reference |
| `backend/app/services/naver_finance.py:810` | `fetch_current_price_with_change_sync` API contract |
| `backend/app/surge_config/surge_settings.py:156` | `ThemePropagationConfig` / `VolumeAnomalyConfig` for Pydantic class pattern |
| `backend/app/models/fund_signal.py` | FundSignal column list (no schema change needed) |
| `backend/alembic/versions/055_spec_ai_022_theme_groups.py` | Confirms no migration needed (this SPEC does not modify schema) |
| `backend/tests/test_theme_propagation.py` / `test_volume_anomaly.py` (existing) | Test scaffolding pattern reference |

---

## 14. Open Questions for Plan-Phase Annotation

1. **Should the SPEC require KST 00:00 boundary** for `today_start` instead of UTC? (SPEC-AI-022 uses UTC for consistency; SPEC-AI-023 follows the same. User confirmation suggested.)
2. **Should `surge_metadata` use full `surge_probability_score` field** (like ensemble pipeline) for backtest compatibility? Current spec: only `surge_basis` and `yesterday_change_pct`. Adding `surge_probability_score = confidence` would normalize the metadata schema across all surge_candidate signals.
3. **Should `enabled=False` be propagated** to a global feature flag in `app.surge_config`? Current spec: configuration is local to `_run_coverage_expansion`. Alternative: env var or `surge_detection.yaml` toggle.

These can be resolved during the annotation cycle in Plan Phase.
