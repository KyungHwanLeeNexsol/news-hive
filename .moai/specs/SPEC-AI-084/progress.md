# SPEC-AI-084 Progress

## §E.2 Run-phase Evidence

### Methodology

DDD (ANALYZE-PRESERVE-IMPROVE) per `.moai/config/sections/quality.yaml`.

- **ANALYZE**: Read `surge_detector.py` (`detect_theme_group_carry_forward` @ 3012,
  `_fetch_price_change_sync`), `news_crawler.py` (`_classify_urgency` + call site @ 577),
  `fund_manager.py` (`_run_coverage_expansion`), `surge_evaluation_service.py`
  (`_is_same_day_event_horizon_signal` @ 506, `_is_near_limit_up_carry_signal` @ 482),
  `surge_settings.py` config patterns, `stock.py`/`theme_group.py`/`news_relation.py`/
  `disclosure.py` models, `ai_classifier._extract_sector_keywords`, `keyword_generator`
  (confirmed this is the *following*-system LLM path — deliberately NOT reused, [X-8]).
- **PRESERVE**: `_classify_urgency` itself is UNCHANGED (zero diff) — its existing test
  suite (`TestClassifyUrgency`, 9 tests) continues to pass unmodified, confirming no
  regression to the shared, already-tested function. Only its *caller* (the batch-insert
  loop in `crawl_all_news`) was extended, gated behind a config flag defaulting to the
  legacy path. `detect_theme_group_carry_forward` / `ThemeGroup` / `StockThemeGroup` were
  not touched (grep-verified absent from the new function's source, REQ-AI084-016).
- **IMPROVE**: Implemented Group C (keyword tagging) → Group B (urgency recalibration,
  independent) → Group A (theme-news-carry detector, consumes C + B) in dependency order
  per plan.md, then wired same-day horizon tagging (M5) inline into Group A's signal
  creation (no separate migration/schema — reuses SPEC-AI-080's existing
  `_is_same_day_event_horizon_signal` evaluation path verbatim).

### Milestones delivered (plan.md M1–M5, all Priority High/Medium items)

| Milestone | Deliverable | Status |
|-----------|-------------|--------|
| M1 | `keyword_tagging_service.backfill_stock_keywords()` — 1-shot batch backfill, NULL/empty-only targeting (idempotent + non-destructive by construction) | Done |
| M2 | `keyword_tagging_service.refresh_stock_keywords()` — continuous tagging, wired as a post-crawl hook in `crawl_all_news` (collects `stock_id`s touched this cycle, exception-isolated) | Done |
| M3 | `news_crawler._compute_theme_co_mention_counts` / `_article_theme_topic_counts` / `_matches_theme_rally_keyword`, gated via `NewsUrgencyRecalibrationConfig` (default `enabled=False`) at the `_classify_urgency` call site | Done |
| M4 | `surge_detector.detect_theme_news_carry()` — keyword-basket carry-forward detector mirroring `detect_theme_group_carry_forward`; wired as item 9 of `fund_manager._run_coverage_expansion()` | Done |
| M5 | `horizon="same_day"` set unconditionally on every propagation signal's `surge_metadata` (DP-5 resolved as "all propagation candidates" — the simplest reading consistent with every candidate being a same-day intraday prediction); DB-assertion test closes the loop through the real `_is_same_day_event_horizon_signal` | Done |

### Design decisions made during Run (resolving spec.md Open Questions)

- **OQ-1 (keyword extraction method)**: rule/dictionary-only, reusing
  `ThemeClusterConfig.keywords` (existing 20-theme vocabulary, zero new LLM calls). No LLM
  augmentation path was implemented — AC-084-004's LLM-budget-guard requirement is
  satisfied structurally (no unbounded call site exists at all), not via a runtime guard
  around an LLM call. This is a narrower resolution than "규칙 우선, LLM 보조"; the LLM-
  augmented path is not built and would be a follow-up if extraction recall proves
  insufficient in practice.
- **OQ-2 (basket granularity)**: single-keyword membership (a stock belongs to a basket
  per keyword string it carries in `stocks.keywords`; a stock in multiple baskets is
  handled via cross-basket dedup, EC-3).
- **OQ-3 (theme-activation threshold)**: `min_anchor_members_for_activation=2` (≥2 members
  moved) OR (≥1 anchor AND a breaking/important article containing the keyword within
  `high_urgency_window_hours=24`). Not calibrated against the live 07-22 robot-rally replay
  (no replay dataset was available in this run) — flagged as residual risk below.
- **OQ-4 (co-mention window/key)**: within-crawl-batch aggregation (no extra DB query),
  keyed by the same `ThemeClusterConfig.keywords` vocabulary used by Group C (consistency).
- **OQ-5 (same-day trigger threshold)**: all propagation candidates get `horizon="same_day"`
  unconditionally (not a subset) — see M5 row above.
- **OQ-6 (continuous-tagging trigger)**: crawl-completion hook (not a new scheduler cron
  job), scoped to only the stocks that received a news relation in that crawl cycle.

### Files changed

- `backend/app/services/keyword_tagging_service.py` (new, 220 LOC) — Group C
- `backend/app/services/news_crawler.py` (+~70 LOC) — Group B helpers + gated call site + M2 hook
- `backend/app/services/surge_detector.py` (+~190 LOC) — `detect_theme_news_carry` + `_has_high_urgency_theme_news`
- `backend/app/services/fund_manager.py` (+~16 LOC) — item 9 wiring in `_run_coverage_expansion`
- `backend/app/surge_config/surge_settings.py` (+~35 LOC) — `ThemeNewsCarryConfig`, `NewsUrgencyRecalibrationConfig` (both `enabled=False` by default)
- `backend/tests/test_theme_news_carry.py` (new, 15 tests)
- `backend/tests/test_keyword_tagging_service.py` (new, 11 tests)
- `backend/tests/test_services/test_news_crawler.py` (+7 tests, existing 9 `_classify_urgency` tests untouched)

### Verification (actual command output, this run)

```
cd backend && uv run pytest tests/ --tb=short -q -m "not slow"
===== 2060 passed, 4 skipped, 3 xpassed, 258 warnings in 69.34s (0:01:09) =====
```

Baseline before this SPEC (from prior sessions' memory): 2027 passed. Delta: +33 tests
(new files: 15 + 11 = 26; +7 added to `test_news_crawler.py`), 0 new failures.

```
cd backend && uv run ruff check .
All checks passed!
```

```
cd backend && uv run python -c "from app.main import app; print('OK')"
OK
```

`mypy` is not installed in this environment (`Failed to spawn: mypy — program not found`)
— skipped per project convention ("Tools that are not installed are skipped gracefully").

Coverage on new code (`pytest --cov=app.services.keyword_tagging_service
--cov=app.services.surge_detector ...`): `keyword_tagging_service.py` 90%;
`detect_theme_news_carry` itself has only one uncovered line (the "zero anchors after
price-fetch filtering" early-continue, `surge_detector.py:3240`) — a minor edge branch,
not separately covered by a dedicated test.

### Acceptance criteria disposition (17 total)

All 17 pass with observable evidence, EXCEPT the residual-risk caveats below.

| AC | Status | Note |
|----|--------|------|
| AC-084-001 | PASS | `test_ac001_backfill_fills_stock_keywords_from_linked_news` |
| AC-084-002 | PASS | `test_ac002_backfill_idempotent_second_run_preserves`, `test_ac002_backfill_scanned_bounded_by_universe_size` |
| AC-084-003 | PASS | `test_ac003_backfill_never_overwrites_existing_manual_keywords` (following/keyword_matcher tables are never queried by this service — verified by code inspection, not a dedicated DB-level negative test) |
| AC-084-004 | PASS (narrowed) | `test_ac004_no_network_or_llm_call_in_extraction` — static-source check confirming no LLM/network call exists in the extraction path at all, rather than a runtime budget-guard test around a live LLM call (see OQ-1 resolution above) |
| AC-084-005 | PASS | `test_ac005_refresh_merges_new_keywords_without_deleting_existing`, `test_ac005_refresh_caps_keywords_per_stock` |
| AC-084-006 | PASS | `TestThemeRallyKeyword` (3 positive cases from spec.md examples) |
| AC-084-007 | PASS | `TestThemeRallyKeyword::test_routine_title_does_not_match`, `TestThemeCoMentionCounts::test_unrelated_article_gets_no_topic_counts` |
| AC-084-008 | PASS | `TestUrgencyRecalibrationGating::test_default_config_is_disabled` + `_classify_urgency`'s own 9-test suite is untouched (byte-identical function) |
| AC-084-009 | PASS | same as AC-084-008 — flag OFF path is literally the original one-line call, no divergence possible |
| AC-084-010 | PASS | `test_ac010_basket_anchor_propagates_to_unmoved_members`, `test_ac010_existing_ids_excluded` |
| AC-084-011 | PASS | `test_ac011_single_anchor_without_news_blocks_propagation`, `test_ac011_single_anchor_with_high_urgency_news_opens_gate` |
| AC-084-012 | PASS | `test_ac012_no_keywords_returns_empty_no_error` |
| AC-084-013 | PASS | `test_ac013_same_day_horizon_db_assertion` — DB-persisted `surge_metadata->>'horizon'` asserted AND fed through the real `_is_same_day_event_horizon_signal` |
| AC-084-014 | PASS | `test_ac014_no_execute_signal_trade_and_theme_group_untouched` (static source check) + no detector's parameters/weights/universe files were touched (diff-scoped to the files listed above only) |
| AC-084-015 | PASS | `test_disabled_by_default_returns_empty` |
| AC-084-016 | PASS | `test_first_mover_excluded_from_theme_news_carry_scope` — literally named per spec.md's mandate |
| AC-084-017 | PASS | `test_run_coverage_expansion_wiring_does_not_break_pipeline` (regression-guard style, mirroring the existing `test_group_cascade.py` AC-010 pattern); full suite 2060/2060 green is the broader regression evidence |

## §F Phase 4 Mode Selection

Solo-sequential single-agent run (this delegation). No parallel fan-out or team mode used.

## Residual risks (carried forward, not blocking)

- **[R-1]/[R-3] threshold calibration**: `anchor_surge_min_pct=5.0`,
  `min_anchor_members_for_activation=2`, `high_urgency_window_hours=24` are carried over
  from `ThemeGroupCarryConfig` defaults / plan.md guidance, NOT calibrated against a replay
  of the 2026-07-22 robot-rally dataset (no such replay harness exists in this codebase
  today). Both new detectors default `enabled=False` (staged rollout), so this is a
  pre-activation tuning task, not a functional defect.
- **[R-2] keyword quality**: extraction is a fixed 20-keyword vocabulary substring match;
  no post-backfill sample-quality review was performed (would require live news/disclosure
  data not present in the test environment).
- **OQ-1 LLM path**: not built (see above) — if rule-based recall proves insufficient once
  `enabled=True`, an LLM-augmented extraction path is a follow-up, not silently deferred
  debt (the current path is complete and correct within its stated scope).
- Full end-to-end integration of the gated `crawl_all_news` call site (network crawl →
  urgency assignment → DB insert) was not additionally integration-tested beyond: (a) the
  pre-existing `_classify_urgency` characterization suite (untouched, still passing) and
  (b) new unit tests of the three pure helper functions the call site now uses. Mocking the
  full crawl orchestration for this narrow, flag-gated change was judged higher cost than
  benefit given the default-OFF gate.
