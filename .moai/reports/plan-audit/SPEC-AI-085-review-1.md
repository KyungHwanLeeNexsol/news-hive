# SPEC Review Report: SPEC-AI-085
Iteration: 1/3
Verdict: PASS
Overall Score: 0.94 (category harmonic mean)

Reasoning context ignored per M1 Context Isolation. This audit is based solely on `spec.md`, `plan.md`, `acceptance.md` at `.moai/specs/SPEC-AI-085/`, direct reading of `backend/app/services/news_crawler.py` and `backend/app/services/ai_classifier.py`, and the prior `SPEC-AI-084-review-{1,2,3}.md` reports (consulted only for this project's established EARS-defect-class precedent and frontmatter-schema precedent, per the audit brief).

## Must-Pass Results

- **[PASS] MP-1 REQ number consistency**: `spec.md:L186-254` contains REQ-AI085-001 through REQ-AI085-009, sequential, zero-padded consistently (3 digits), no gaps, no duplicates. Verified end-to-end (all 9 entries individually read, not sampled).

- **[PASS] MP-2 EARS format compliance**: All 9 REQ statements (`spec.md`) and all 9 AC sections / 17 individual EARS sentences (`acceptance.md:L15-119`) were read end-to-end. Every EARS sentence carries exactly one bolded trigger keyword (`**WHEN**`/`**WHILE**`/`**IF**...**THEN**`/`**WHERE**`, or no trigger for Ubiquitous) and exactly one bolded `**SHALL**`/`**SHALL NOT**`, with polarity matching the sentence's real governing predicate (e.g. `acceptance.md:L40-43` AC-085-003 correctly splits a positive-guard clause and a negative-cap clause into two separate EARS sentences, rather than mixing polarities in one sentence as the project's own precedent — `SPEC-AI-084-review-2.md:L40-67` — ruled a blocking defect). No Given-When-Then-only prose was found (contrast with `SPEC-AI-084-review-1.md:L35-59`, which found 100% GWT format with zero bolded EARS in that SPEC's iteration 1). `acceptance.md:L4-8` explicitly self-declares the bolded-EARS-only convention and the "no mixed compound sentence" rule, directly citing the SPEC-AI-081/084 iteration history — SPEC-AI-085 does not repeat that defect class.

- **[PASS] MP-3 YAML frontmatter validity**: `spec.md:L1-14` — `id: SPEC-AI-085` (string, matches pattern), `version: 0.1.0` (string), `status: draft` (string), `created_at: "2026-07-22"` (ISO date string), `priority: High` (string), `labels: [...]` (array) — all 6 fields required by this audit's own MP-3 checklist are present with correct types.
  - **Caveat (non-blocking, consistent with prior precedent)**: this project's own SSOT rule `spec-frontmatter-schema.md` (cross-referenced by `internal/spec/lint.go` `FrontmatterSchemaRule`) defines a stricter canonical 12-field schema (`id, title, version, status, created, updated, author, priority, phase, module, lifecycle, tags`) and explicitly names `created_at`/`labels` as rejected aliases. `spec.md:L1-14` is missing `title`, `phase`, `module`, `lifecycle`, and uses `labels`/`created_at` instead of `tags`/`created`. This SPEC would generate `FrontmatterInvalid` lint findings under that stricter schema. However, `SPEC-AI-084-review-1.md:L70-78` already identified and dispositioned this identical gap as a minor, non-blocking Defect (D3) because it reflects a consistent project-wide convention across the entire SPEC-AI-08x series (verified: `SPEC-AI-083/spec.md:L1-13` and `SPEC-AI-084/spec.md:L1-13` use the identical six-field convention). Applying the same precedent here for consistency — recorded as Defect D1 below, not blocking MP-3.

- **[N/A] MP-4 Section 22 language neutrality**: N/A — single-language (Python/FastAPI backend) news-relation-generation SPEC. No multi-language tooling surface; no language-specific tool named as primary/default.

## Category Scores (0.0-1.0, rubric-anchored)

| Dimension | Score | Rubric Band | Evidence |
|-----------|-------|-------------|----------|
| Clarity | 1.0 | 1.0 band — every requirement has a single, unambiguous interpretation; no pronoun ambiguity | Every REQ/AC anchors to a specific, independently-verified code location (`news_crawler.py:531-543`, `:554-558`, `:570-573`, `:690-761`, `:812-818`; `ai_classifier.py:268`, `:332`, `:344-363`). `spec.md:L76-84` "[중대 정정]" section explicitly corrects an inaccurate prior claim with cited evidence rather than leaving ambiguity. |
| Completeness | 1.0 | 1.0 band — all required sections present, frontmatter complete (see MP-3 caveat), at least one exclusion entry | HISTORY (`spec.md:L18-41`), Overview/WHY+WHAT (`spec.md:L44-110`), Environment & Assumptions (`spec.md:L113-176`), REQUIREMENTS (`spec.md:L179-254`, 9 entries), ACCEPTANCE CRITERIA (`acceptance.md`, 9 AC sections + 7 edge cases), Exclusions (`spec.md:L258-289`, 9 concrete entries with named functions/config keys) all present. |
| Testability | 1.0 | 1.0 band — every AC is binary-testable, no weasel words | Full-text grep of both `spec.md` and `acceptance.md` for `적절/합리적/충분히/reasonable/appropriate/adequate/proper` returned zero matches. Every AC names a concrete, observable artifact (`NewsStockRelation` row existence, `stocks.keywords` NULL/non-NULL state, per-article relation-count cap, log-count summary) — see `acceptance.md:L15-119`. |
| Traceability | 1.0 | 1.0 band — every REQ has ≥1 AC, every AC references a valid REQ, no orphans | REQ-AI085-001..009 (`spec.md`) map 1:1 to AC-085-001..009 (`acceptance.md:L15-119`) — verified individually for all 9 pairs, not sampled. No orphaned AC, no uncovered REQ. |

## Independent Code-Verification Findings (per audit brief's 4 specific asks)

1. **Root cause / evidence matches real code**: CONFIRMED. Independently read `news_crawler.py:505-624` and `:690-761`, and `ai_classifier.py:260-395`. All six `[E-1]`–`[E-6]` evidentiary claims in `spec.md:L123-157` check out exactly against the current source:
   - `[E-1]`/`[E-2]`: `classify_news(ad["title"], index)` at `news_crawler.py:542` is called unconditionally for every article inside the relation-computation loop (`:531-543`), confirmed — this is NOT query-gated. The SPEC's stated correction of the orchestrator's initial "query-only" claim is accurate.
   - `[E-3]`: `classify_news` (`ai_classifier.py:332`) reads only the `title` argument; `calculate_relevance_score` (`ai_classifier.py:268`) is called only against relations already present in `ad["_relations"]` (verified at `news_crawler.py:611-618` and `:728-735`) — it boosts score for existing relations, it does not generate new ones from description text. Confirmed accurate.
   - `[E-4]`: the no-relation discard filter is at `news_crawler.py:555` (`unique_articles = [a for a in unique_articles if a.get("_relations")]`), and content scraping (`ad["_content"]`) happens at `:570-573`, strictly after the filter. Confirmed the ordering claim that description text is available pre-filter while content is not.
   - `[E-5]`: `_build_search_queries` (`news_crawler.py:217-248`) confirmed to follow exactly the 3-tier priority claimed: all sectors-with-stocks (`:221-228`), keyword-bearing stocks (`:230-236`), then round-robin sample of the remainder (`:238-246`).
   - `[E-6]`: `_touched_stock_ids.add(rel["stock_id"])` at `news_crawler.py:747` and the `refresh_stock_keywords` call at `:812-816` confirmed to fire only for relations that already passed the score/threshold check at `:741-743` — confirming the SPEC's claim that new relations automatically flow into keyword promotion via the existing wiring.

2. **Additive scoping, no regression risk to title/query paths**: CONFIRMED at the mechanism level. The proposed insertion point ("immediately after `:542`, before the `:543` assignment `ad["_relations"] = relations`") extends the same local `relations` list rather than replacing or reordering existing entries. The downstream insertion loop's existing `seen_pairs` dedup (`news_crawler.py:718-722`, deduping by `(stock_id, sector_id)`) already provides first-write-wins protection — since title/query relations are appended to the list before any description-based merge, a duplicate description-match for the same stock/sector pair is naturally absorbed by pre-existing dedup logic without any new code. This is a positive finding: plan.md's "reuses the existing insertion pipeline" claim is not hand-waved, it is mechanically correct given the actual code.

3. **Full-content matching and round-robin fairness honestly scoped out**: CONFIRMED. `spec.md:L266-274` `[X-2]`/`[X-3]` state the exclusions with concrete rationale (content is only available after the discard filter; round-robin reordering mitigates but does not eliminate the cycle), and `spec.md:L345-350` §8(a)/(b) explicitly carry them forward as named follow-up candidates. Nothing is silently dropped.

4. **No overclaim of guaranteed 6-stock recovery**: CONFIRMED. `spec.md:L167-170` `[A-3]` explicitly states "본 SPEC은 '설명에 종목명이 등장하면 관계가 생긴다'는 구조적 결손 해소를 보증하며, 특정 6종 전수 회수는 관측 지표로 다룬다" (the SPEC guarantees the structural-gap closure, and treats full 6-stock recovery as an observation metric, not a plan-stage guarantee). None of AC-085-001..009 or the Definition of Done (`acceptance.md:L141-149`) assert recovery of the specific 6 stocks as a pass/fail criterion — the DoD's last item explicitly labels observation of recovery counts as "범위 밖 계측" (out-of-scope measurement, §8(c)). Additionally verified independently: description-only matches (no title match) compute to `raw_score=20`, and with `get_source_credibility` ranging from 1.0 (major dailies) down to a 0.5 default / as low as an implied 0.3 floor (`ai_classifier.py:196-227`), a description-only match does NOT reliably clear the `min_score=10` threshold for low-credibility sources (20 × 0.3 = 6 < 10) — this independently confirms OQ-2's deferral is substantively grounded, not a hand-wave.

## Defects Found

D1. `spec.md:L1-14` — Frontmatter is missing `title`, `phase`, `module`, `lifecycle` (required by this project's own canonical `spec-frontmatter-schema.md`/`internal/spec/lint.go` 12-field schema) and uses the rejected aliases `labels`/`created_at` instead of `tags`/`created`. Non-blocking per the `SPEC-AI-084-review-1.md` precedent (same gap, same disposition, consistent project-wide convention across SPEC-AI-083/084/085) — Severity: minor. Recommend project-wide reconciliation in a future housekeeping SPEC, not a rework of this SPEC.

D2. `spec.md:L196-201` (REQ-AI085-002) and `spec.md:L206-213` (REQ-AI085-003) each bundle two distinct normative actions into a single REQ sentence via a conjunctive "-하고" clause (e.g. REQ-003: apply the name-boundary guard AND cap per-article relation count). This does not violate MP-2 (both actions share the same polarity, and `acceptance.md` correctly decomposes each into separate single-action EARS sentences at the AC level), but it is a minor clarity/precision nit at the REQ level — Severity: minor.

(No other defects found — see Chain-of-Verification Pass below for confirmation this is not an artifact of a shallow first pass.)

## Chain-of-Verification Pass

Second-look findings: none new. Re-verified explicitly:
- REQ numbering re-counted end-to-end (001→009, no gaps/dupes) a second time independent of the first pass.
- Traceability re-checked for all 9 REQ↔AC pairs individually (not sampled) — confirmed 1:1, no orphans.
- Exclusions section (`spec.md:L258-289`) re-read for specificity — all 9 entries name a concrete function, config key, or explicit behavior, not vague placeholders.
- Contradiction scan performed across all 9 REQs pairwise for conflicting normative claims — none found (REQ-001 create vs REQ-005 don't-change-title/query are compatible/additive by construction; REQ-003's per-article cap vs REQ-001's create-on-match is an intentional, documented trade-off in §5 Risks, not a contradiction).
- Re-verified that `classify_news`'s `relevance: "direct"` labeling for stock-name matches (`ai_classifier.py:361`) would mislabel a description-only match as "direct" if the SPEC's OQ-1 option (i) (`classify_news` re-call on description) is chosen naively — confirmed the SPEC's own OQ-2/DP-2 already anticipates and defers exactly this labeling nuance to Run-phase, so this is not an undisclosed gap.
- Re-confirmed the HISTORY section's narrated live-DB observation counts (6 stocks with 0-1 relation rows; 로보스타/한라캐스트 exactly 1 each) are UNVERIFIED by this audit — no production DB access — but this is motivational narrative, not a normative REQ/AC claim, so it does not affect the PASS verdict on the actual plan content.

## Recommendation

PASS. Rationale citing evidence for each must-pass criterion:
- MP-1: `spec.md:L186-254`, 9 sequential REQ entries, zero gaps/duplicates, verified twice.
- MP-2: `acceptance.md:L15-119`, all 17 EARS sentences individually confirmed single-trigger + single-SHALL + polarity-matched; explicitly does not repeat the GWT-only (SPEC-AI-084 iteration 1) or mixed-polarity (SPEC-AI-084 iteration 2) defect classes documented in this project's own prior audit history.
- MP-3: `spec.md:L1-14`, all 6 fields required by this audit's checklist present with correct types; the stricter-schema gap is recorded as non-blocking Defect D1 consistent with established project precedent.
- MP-4: N/A, single-language SPEC.

Minor, non-blocking defects D1-D2 are recorded for optional follow-up but do not require a re-iteration of this SPEC's plan-phase artifacts.
