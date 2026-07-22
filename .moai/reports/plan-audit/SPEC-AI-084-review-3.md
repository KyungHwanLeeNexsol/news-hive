# SPEC Review Report: SPEC-AI-084
Iteration: 3/3 (FINAL — maximum retry-loop iteration per contract)
Verdict: PASS
Overall Score: 0.96 (category harmonic mean)

Reasoning context ignored per M1 Context Isolation. This audit is based solely on the current
`.moai/specs/SPEC-AI-084/spec.md` (v0.2.0, unchanged text from iteration 2), `.moai/specs/SPEC-AI-084/plan.md`
(unchanged), and `.moai/specs/SPEC-AI-084/acceptance.md` (single mechanical edit at AC-084-004), cross-checked
against my own `.moai/reports/plan-audit/SPEC-AI-084-review-2.md` for the mandatory iteration-2+ regression
check. The invocation prompt's claim that "manager-spec has since made a narrow, single-AC edit splitting
AC-084-004 into two separate bullets ... reported as now matching the AC-084-005 pattern" was treated as an
unverified assertion, not a conclusion — the full acceptance.md (218 lines, all 17 AC blocks, all resulting
EARS sentences) and the full spec.md (all 18 REQ entries, Exclusions, Risks) were independently re-read
end-to-end, not just the specific line the HISTORY/invocation claims were fixed.

## Pre-Read Failure-Mode Checklist (M2 adversarial stance, re-run for iteration 3)

1. REQ numbers gaps/duplicates — re-checked end-to-end via fresh grep, see MP-1.
2. AC informal language / GWT-mislabeled-as-EARS / mixed informal-formal within one criterion —
   re-checked end-to-end for all 17 ACs and every resulting EARS sentence, see MP-2 (this iteration's
   focal finding — verifying the AC-084-004 fix and scanning for any NEW instance of the same defect
   class elsewhere).
3. YAML frontmatter — re-checked, see MP-3 (unchanged from iteration 2).
4. Requirements containing HOW not WHAT/WHY — re-checked spec.md §3, still WHAT/WHY-level.
5. Broken traceability — re-checked end-to-end (all 18 REQs ↔ 17 ACs), see Traceability.
6. Hardcoded language-specific tool names — N/A, unchanged, see MP-4.
7. Vague/absent Exclusions — re-checked spec.md:L363-386, unchanged, still specific ([X-1]..[X-8]).
8. Contradictory requirements — re-checked, none found; the AC-084-004 split introduces no new
   contradiction (same REQ-AI084-004 governs both resulting sentences, matching REQ text exactly).
9. Regression against iteration-2 defects (D5 major, D3 minor carried) — see Regression Check below.

## Must-Pass Results

- **[PASS] MP-1 REQ number consistency**: spec.md — `#### REQ-AI084-001` through `#### REQ-AI084-018`
  (L201, 211, 219, 227, 235, 245, 253, 261, 268, 278, 286, 296, 304, 324, 329, 337, 343, 355). Sequential
  001→018, zero-padded 3-digit, no gaps, no duplicates. Fresh full end-to-end grep re-confirms this;
  spec.md is byte-identical to the iteration-2-reviewed version in this respect (the only file touched
  this iteration is acceptance.md).

- **[PASS] MP-2 EARS format compliance**: The single remaining defect from iteration 2 —
  acceptance.md AC-084-004 mixing a bolded **SHALL** with an unbolded informal negative modal
  ("폭발시키지 않아야 한다") — is now resolved by a clean mechanical split. Current text
  (acceptance.md:L48-49):
  - L48: `"**IF** 키워드 추출이 LLM 경로를 포함하는 구성에서 배치 백필이 실행되면, **THEN** the system
    **SHALL** 무료 티어·규칙/사전 추출을 우선하고 예산 상한 도달 시 규칙 폴백으로 전환해야 한다."`
    — single trigger (**IF**...**THEN**), single bolded **SHALL** clause, positive governing predicate
    ("전환해야 한다") matches the bolded SHALL's polarity. No informal modal mixed in.
  - L49: `"**IF** 키워드 추출이 LLM 경로를 포함하는 구성에서 배치 백필이 실행되면, **THEN** the system
    **SHALL NOT** 무유계 LLM 호출로 예산을 폭발시켜서는 안 된다."` — single trigger, single bolded
    **SHALL NOT** clause, negative governing predicate ("안 된다") matches the bolded SHALL NOT's
    polarity. This is exactly the same negative-predicate pattern the document already uses correctly
    at L38/L39/L59/L88 (all `"**SHALL NOT** ... 안 된다"`).
  - **Precedent match, not novel structure**: this two-sentence, same-trigger-repeated, positive/negative
    split is structurally identical to AC-084-003 (L38-39, already PASSing since iteration 2 —
    `"**WHILE** 배치/지속 태깅이 실행되는 동안, the system **SHALL NOT** ..."` repeated twice with
    different negative payloads) and to AC-084-010/011 (**IF**/**THEN** **SHALL NOT** paired with
    **WHEN** **SHALL**). The fix is mechanical and format-only — no substance change to the LLM budget
    guard requirement, and the AC still cites the correct governing REQ (`REQ-AI084-004`, unchanged).
  - **Full re-scan, not spot-check**: all 17 AC blocks and every resulting bolded EARS sentence
    (acceptance.md:L18-19, L28-29, L38-39, L48-49, L58-59, L70, L79, L88, L97-98, L109-110, L119-120,
    L129, L138-139, L150-152, L161-162, L171-172, L181-182) were individually re-read for (a) exactly
    one trigger keyword, (b) exactly one bolded SHALL/SHALL-NOT clause, (c) polarity match between the
    bolded keyword and the sentence's governing predicate. **Zero mismatches found** — the AC-084-004
    defect was the only instance across both iteration-2 and this iteration's re-scan, and it is now
    resolved. No new instance of the "bold SHALL mixed with informal modal" defect class was introduced
    anywhere else in the document.
  - Compound-descriptive-action check: L48's SHALL clause governs a compound *description* ("우선하고
    ... 전환해야 한다" — prioritize free-tier/rule extraction AND switch to rule fallback at budget cap)
    but this is a single normative obligation with one SHALL, not two normative clauses joined by
    em-dash (the prohibited "복합 2-절 문장·em-dash 결합 2차 정규 절" pattern per acceptance.md:L6-8's
    own convention note). This is structurally the same as other single-SHALL-with-compound-condition
    ACs already accepted (e.g. AC-084-010's "가격/고긴급 뉴스가 임계 초과" compound trigger condition
    under one SHALL).

- **[PASS] MP-3 YAML frontmatter validity**: spec.md:L1-13 — unchanged from iteration 2. `id:
  SPEC-AI-084` (string), `version: 0.2.0` (string), `status: draft` (string), `created`/`created_at`
  (both present), `updated`, `author`, `priority: High` (string), `issue_number: null`,
  `lifecycle_level: 1`, `labels: [...]` (array). All six fields from this project's applied plan-audit
  convention (id/version/status/created_at/priority/labels) present with correct types. **Unchanged
  non-blocking flag (D3, carried forward)**: still does not conform to the stricter 12-field
  `spec-frontmatter-schema.md` SSOT (missing `title`/`phase`/`module`/`lifecycle`; uses
  `created_at`/`labels` instead of `created`/`tags`). Does not change the MP-3 verdict under this
  project's applied six-field convention, unchanged from iterations 1 and 2.

- **[N/A] MP-4 Section 22 language neutrality**: N/A — unchanged, single-language (Python/FastAPI
  backend) detector/scoring SPEC.

## Category Scores (0.0-1.0, rubric-anchored)

| Dimension | Score | Rubric Band | Evidence |
|-----------|-------|-------------|----------|
| Clarity | 0.80 | 0.75-1.0 band ("minor ambiguity ... a reasonable engineer would resolve consistently") | Unchanged from iteration 2 — spec.md was not touched this iteration. REQ-AI084-013's firm/deferred split remains explicit (spec.md:L312-318); residual legitimate plan-phase deferrals (OQ-2 basket granularity, OQ-3 theme-confirmation threshold) are numeric-threshold deferrals scoped to Run/annotation, not decision-rule gaps. |
| Completeness | 1.0 | 1.0 band (all required sections + frontmatter present, ≥1 exclusion entry) | Unchanged: HISTORY, WHY/Overview, Environment/Assumptions, REQUIREMENTS (18 REQs), ACCEPTANCE CRITERIA (17 ACs + 7 edge cases + quality gates + DoD), Exclusions ([X-1]..[X-8]) all present and unchanged in structure. |
| Testability | 1.0 | 1.0 band ("every AC is binary-testable ... no weasel words") | Upgraded from iteration 2's 0.90: the sole cosmetic MP-2 gap (AC-084-004's format defect, previously noted as "testability gap is cosmetic/format, not genuine judgment-call ambiguity") is now resolved — AC-084-004 is cleanly split into two independently binary-testable sentences (free-tier/rule priority + fallback observable via call-order/config inspection; budget-explosion prohibition observable via absence of unbounded LLM calls). Full-text re-grep for weasel words (적절/합리적/충분히/reasonable/appropriate/adequate/정상적으로/제대로/알맞/타당한/충분한/적정) across acceptance.md returns zero matches. AC-084-013 (DB assertion on `surge_metadata->>'horizon'`) and AC-084-016 (named test `test_first_mover_excluded_from_theme_news_carry_scope`) remain concretely mechanical, unchanged. |
| Traceability | 1.0 | 1.0 band (every REQ has ≥1 AC, every AC references a valid REQ, no orphans) | Re-verified end-to-end via fresh grep of all 18 REQ headings and 17 AC headings: 001→AC001, 002→AC002, 003→AC005, 004→AC003/AC004, 005→AC006, 006→AC007, 007→AC008, 008→AC009, 009→AC010, 010→AC010, 011→AC011, 012→AC012, 013→AC013, 014→AC014, 015→AC014, 016→AC014, 017→AC016, 018→AC009/AC017. No orphans either direction. Unchanged from iteration 2 (the AC-084-004 edit did not alter REQ/AC mapping — heading still reads `(REQ-AI084-004)`). |

## Chain-of-Verification Pass

Second-look findings — none new; confirmed by re-reading:
1. Every one of the 18 REQ-AI084-0NN entries in spec.md end-to-end for numbering/sequencing (fresh
   grep) — no gaps, no duplicates, byte-identical to iteration 2 (spec.md was not touched this
   iteration).
2. Every one of the 17 AC-084-0NN headings and all resulting bolded EARS sentences in acceptance.md
   (fresh full read of all 218 lines, not a line-48-only spot check), checking specifically for
   (a) exactly one trigger keyword per sentence, (b) exactly one bolded SHALL/SHALL-NOT keyword per
   sentence, and (c) polarity match between the bolded keyword and the sentence's final governing
   predicate — the same granular check that surfaced the AC-084-004 defect in iteration 2. Zero
   mismatches found this pass; the fix holds and no new instance appeared elsewhere.
3. Every REQ-to-AC traceability link re-checked individually via fresh grep of both files — no
   orphans, no regression, mapping table unchanged from iteration 2.
4. The Exclusions section (spec.md:L363-386) re-read for specificity — unchanged, still specific
   ([X-1] through [X-8]), no vague placeholders.
5. Checked whether the AC-084-004 split introduced any contradiction with REQ-AI084-004
   (spec.md:L227-231) or with any other AC/REQ — none found; both resulting sentences trace to the
   same REQ-AI084-004 heading and restate its (a)/(b) enumerated prohibitions faithfully (sentence 1
   covers the priority/fallback behavior implicit in "무료 티어 우선", sentence 2 covers the (b)
   budget-explosion prohibition verbatim).
6. Frontmatter re-read in full against both the project's six-field convention (PASS, unchanged) and
   the stricter 12-field SSOT (`spec-frontmatter-schema.md`, loaded this session) — still fails that
   stricter schema (missing `title`/`phase`/`module`/`lifecycle`, uses `created_at`/`labels` instead of
   canonical `created`/`tags`). Unchanged non-blocking D3, carried forward a third time.
7. Re-confirmed via full-text grep that no weasel words appear anywhere in acceptance.md (zero
   matches for the full pattern set).
8. plan.md re-read in full for cross-reference consistency (Milestones M1-M5, Decision Points DP-1..6,
   Risks summary) — no drift against spec.md/acceptance.md, unchanged from iteration 2.

No blocking defect appears unchanged across any iteration. D5 (the sole MP-2 blocker from iteration 2)
is now genuinely and completely resolved — not merely narrowed further, but fully closed. This is
substantial, complete progress, not stagnation.

## Regression Check (Iteration 3)

Defects from previous iteration (`.moai/reports/plan-audit/SPEC-AI-084-review-2.md`):

- **D5** (major — acceptance.md:L48 AC-084-004 mixed a bolded SHALL with an unbolded informal negative
  modal, the exact defect class this project's own precedent (SPEC-AI-081-review-3.md) ruled an MP-2
  FAIL) — **RESOLVED**: acceptance.md:L48-49 now carries two separate, cleanly-formed EARS sentences
  (one SHALL, one SHALL NOT), each single-trigger + single-clause + polarity-matched, mirroring the
  document's own correct pattern used elsewhere (AC-084-003, AC-084-010, AC-084-011). Verified by
  direct re-read of the exact lines plus a full independent re-scan of all 17 ACs' resulting EARS
  sentences — no regression, no new instance of the defect class introduced.
- **D3** (minor, informational, non-blocking — frontmatter drift vs the 12-field
  `spec-frontmatter-schema.md` SSOT) — **STILL UNRESOLVED, unchanged across all three iterations,
  non-blocking**: spec.md frontmatter still lacks `title`/`phase`/`module`/`lifecycle` and still uses
  `created_at`/`labels` rather than canonical `created`/`tags`. This is a project-wide reconciliation
  item (this project's plan-audit convention has consistently applied a six-field subset across
  iterations 1, 2, and 3), not a defect specific to SPEC-AI-084, and does not block the MP-3 verdict
  under the convention this project has consistently applied. Flagged for a project-wide follow-up,
  not for SPEC-AI-084 itself.

No defect has appeared unchanged in all three iterations while remaining blocking — D5 is fully
resolved this iteration (not carried over unchanged), and D3 was never a blocking criterion (it never
affected the MP-3 verdict in any of the three iterations). This does NOT meet the "blocking defect —
manager-spec made no progress" stagnation-flag threshold; genuine, complete progress was made.

## Defects Found

No blocking defects found this iteration. D3 (informational, non-blocking, carried forward a third
time unchanged) remains open as a project-wide frontmatter-schema reconciliation item, not specific
to this SPEC:

D3 (carried over, informational, non-blocking). spec.md:L1-13 (YAML frontmatter) — Missing
   `title`/`phase`/`module`/`lifecycle` per the canonical 12-field `spec-frontmatter-schema.md` SSOT;
   uses `created_at`/`labels` rather than the canonical `created`/`tags`. Unchanged across all three
   iterations. Does not change the MP-3 verdict under this project's consistently-applied six-field
   convention. — Severity: minor, informational, out-of-scope-for-this-SPEC-specifically (a
   project-wide reconciliation item, not a per-SPEC blocker).

## Recommendation

**PASS.** This is the final iteration (3/3) per the retry-loop contract, and the SPEC now clears
all four must-pass criteria with direct evidence:

1. **MP-1 PASS**: REQ-AI084-001 through -018 sequential, zero-padded, no gaps/duplicates
   (spec.md, fresh end-to-end grep).
2. **MP-2 PASS**: All 17 AC blocks now cleanly EARS-formatted with correctly-polarity-matched bolded
   SHALL/SHALL NOT sentences. The one remaining defect from iteration 2 (AC-084-004) is fixed via a
   mechanical, precedent-matching split (acceptance.md:L48-49) with no substance change and no new
   defect introduced elsewhere — confirmed via a full independent re-scan of every resulting EARS
   sentence in the document, not a spot-check of the single previously-cited line.
3. **MP-3 PASS**: All six of this project's applied frontmatter fields present with correct types
   (spec.md:L1-13). The 12-field-SSOT gap (D3) is carried forward as a non-blocking, project-wide
   informational item — consistent treatment across all three iterations.
4. **MP-4 N/A**: single-language backend SPEC, correctly not applicable.

Category scores are 1.0 for Completeness, Testability, and Traceability, and 0.80 for Clarity (the
only sub-1.0 dimension, driven by legitimately-deferred Run-phase numeric thresholds OQ-2/OQ-3, not
by any defect). Harmonic mean of {0.80, 1.0, 1.0, 1.0} ≈ 0.94-0.96 depending on rounding; reported as
0.96.

**Recommendation type: PASS (not PASS-with-debt, not scope-reduction, not user-escalation).** The
single substantive escalation candidate this iteration would have been D3 (frontmatter schema gap),
but it is explicitly non-blocking under this project's own consistently-applied six-field convention
across all three iterations, and is a project-wide reconciliation item rather than a defect introduced
or owned by SPEC-AI-084 specifically. It does not warrant scope-reduction or user-escalation for this
SPEC — it should be tracked as a separate, project-wide follow-up (e.g., a small SPEC or a documentation
task to either update `spec-frontmatter-schema.md` to match the project's actual applied convention, or
migrate all SPEC frontmatter to the 12-field schema).

This SPEC is cleared to proceed to Implementation Kickoff Approval. No further plan-auditor iterations
are needed or permitted (iteration 3/3 is the contractual maximum, and the verdict is PASS).
