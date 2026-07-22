# SPEC-AI-085 — Progress

## §E.1 Plan-phase Audit-Ready Signal

- plan_status: audit-ready
- plan_complete_at: "2026-07-22"
- plan-auditor verdict: PASS (iteration 1, score 0.94) — Implementation Kickoff Approved by user.

## §E.2 Run-phase Evidence

### Methodology: DDD (ANALYZE-PRESERVE-IMPROVE)

- **ANALYZE**: Read `news_crawler.py` relation-computation block (`crawl_all_news` lines
  ~531-543 pre-change, ~690-761 insertion loop) and `ai_classifier.py`'s `classify_news`
  (`:332`) / `calculate_relevance_score` (`:268`) in full before any change.
- **PRESERVE (characterization tests, RED-first)**: Added
  `tests/test_services/test_news_crawler.py::TestDescriptionBasedRelationsCharacterization`
  capturing current behavior — (a) title-stock-name match works (existing behavior,
  regression guard), (b) description-only stock name is **missed** by
  `classify_news(title, index)` (the exact gap SPEC-AI-085 closes), (c) `_query=None`
  RSS-article title matching regression guard. Ran `pytest -k DescriptionRelation` before
  implementation → confirmed RED via `ImportError: cannot import name
  '_resolve_description_relations'` (the new helper did not exist yet).
- **IMPROVE**: Implemented `_resolve_description_relations()` in `news_crawler.py`
  (reuses `classify_news` unchanged — same longest-match + Korean-preceding-character
  boundary guard — applied to `ad.get("description")`), wired into `crawl_all_news`'s
  relation loop behind a new `DescriptionRelationMatchingConfig` gate
  (`app/surge_config/surge_settings.py`, `enabled: bool = False` default, mirrors the
  `NewsUrgencyRecalibrationConfig` SPEC-AI-084 pattern exactly — standalone `BaseModel`,
  instantiated directly, not routed through `get_surge_config()`/YAML).

### Milestones (plan.md)

- **M1 (P0) — Reproduction-first characterization**: DONE. RED confirmed, then GREEN
  after implementation (see below).
- **M2 (P0) — Description-based relation generation**: DONE. Name-boundary guard +
  per-article cap (`max_relations_per_article: int = 5`, DP-1 — see Residual-risk) +
  existing score-filter routing (unchanged, REQ-004) + existing title/query paths
  unchanged (REQ-005, verified by diff — only additive lines inserted).
- **M3 (P1) — Config gating + non-contamination**: DONE. Flag OFF (default) → the new
  code path is never entered (`if _desc_relation_config.enabled:` guards both the
  per-article call and the observability log) → byte-identical to legacy. No
  `stocks.keywords` or following-system data is written by this SPEC — only
  `news_stock_relations` rows via the existing insertion path (REQ-007, unchanged
  table/columns).
- **M4 (P1) — Regression safety + observability**: DONE. Full backend suite green (see
  Evidence below). Bounded 1-line log
  (`[SPEC-AI-085] Description-based relations created this crawl: N`) emitted only when
  the flag is enabled — no per-stock breakdown (REQ-009).

### Files changed (+ line ranges)

- `backend/app/services/news_crawler.py`
  - New function `_resolve_description_relations()` (lines 306-337).
  - Relation-loop wiring: gating config instantiation + per-article call + bounded
    observability log (lines 569-609, wraps the pre-existing lines 578-589/602
    unchanged).
- `backend/app/surge_config/surge_settings.py`
  - New `DescriptionRelationMatchingConfig(BaseModel)` class (after
    `NewsUrgencyRecalibrationConfig`, before `BollingerSqueezeConfig`) — `enabled: bool
    = False`, `max_relations_per_article: int = 5`.
- `backend/tests/test_services/test_news_crawler.py`
  - `TestDescriptionBasedRelationsCharacterization` (RED-first characterization, 3 tests)
  - `TestResolveDescriptionRelations` (GREEN, 6 tests — REQ-001/002/003, EC-1/2/3/4)
  - `TestDescriptionRelationMatchingGating` (1 test — REQ-006 default)

## §E.3 Run-phase Audit-Ready Signal

- run_status: audit-ready
- All milestones (M1-M4) complete.
- Test evidence: see Post-Implementation Review section of the final run-phase report
  (verbatim pytest/ruff output).

## Post-Implementation Review

### Potential issues / edge cases

- **AC-085-001 "in-situ" verification inside `crawl_all_news` is unit-level, not a full
  mocked orchestration test.** `_resolve_description_relations` is fully unit-tested in
  isolation (6 dedicated tests) and the wiring at the call site was verified by direct
  code reading (gating `if`, additive `extend`, unchanged pre-existing lines). A full
  `crawl_all_news`-level integration test with the flag flipped ON was not added because
  the existing `TestCrawlAllNews` mock harness in this file uses a flat
  `db.query.return_value = query_mock` (not a model-dispatched mock), so it cannot build
  a realistic `KeywordIndex` without extensive mock rework — building that rework was
  judged out of scope (drive-by refactor of unrelated test infrastructure). This mirrors
  the existing test depth precedent set by SPEC-AI-084's `NewsUrgencyRecalibrationConfig`
  gating test (default-value check only, no full orchestration test).
- **DP-1 per-article cap (5) is a conservative default, NOT an empirically-calibrated
  value.** spec.md OQ-3 asks for calibration against a "2026-07-22 로봇 랠리 묶음 기사
  replay" — no such replay dataset was available in this run-phase, so 5 is a reasoned
  default (documented honestly in the `DescriptionRelationMatchingConfig` docstring/
  comment) subject to post-deploy observation via the REQ-009 log line.
- **Flag defaults to OFF.** No behavior changes in production until an operator flips
  `DescriptionRelationMatchingConfig.enabled` (currently no env/YAML wiring exists for
  it, matching the `NewsUrgencyRecalibrationConfig` precedent exactly — flipping requires
  a code change to the default, same as that sibling config).

### Suggested additional tests (not added — recorded as residual risk)

- A live-DB integration test (`db` fixture + `make_stock`/`make_sector` + a real
  `crawl_all_news` invocation with mocked crawlers) exercising the flag ON end-to-end,
  once `TestCrawlAllNews`'s mock harness is reworked to model-dispatch `db.query()`.
- A test asserting the score-filter interaction explicitly (a description-only match
  whose `calculate_relevance_score` falls below the min-score threshold is filtered at
  insertion) — currently covered only implicitly (the insertion-time `min_score` filter
  itself is unchanged, REQ-004, and is exercised by pre-existing tests unrelated to this
  SPEC).

### Known limitations / assumptions

- Per spec.md [A-3]/[X-2]: full recovery of the 6 originally-missed robot-theme stocks
  from the 2026-07-22 investigation is explicitly NOT a tested acceptance criterion — it
  is a post-deploy observable metric (description-text richness varies per article, and
  one of the 6 — 씨메스 — has zero news coverage regardless of this fix). No test asserts
  "all 6 stocks get relations now."
- Per spec.md [X-1]/[X-3]: this SPEC does not touch crawl budget, query priority
  round-robin fairness, or content(본문)-based matching — all explicitly out of scope.
