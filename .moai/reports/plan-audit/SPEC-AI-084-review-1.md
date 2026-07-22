# SPEC Review Report: SPEC-AI-084
Iteration: 1/3
Verdict: FAIL
Overall Score: 0.75 (category harmonic mean; verdict forced to FAIL by M5 Must-Pass Firewall regardless of this number)

Reasoning context ignored per M1 Context Isolation. This audit is based on
`.moai/specs/SPEC-AI-084/spec.md`, `.moai/specs/SPEC-AI-084/plan.md`, and
`.moai/specs/SPEC-AI-084/acceptance.md`, cross-checked against
`.moai/project/product.md`/`.moai/project/tech.md` (read, no conflicting constraints found) and
spot-verified against the live `backend/` codebase (see § Bias-Prevention / Evidence Verification
below). The invocation prompt's framing of the root cause (Samsung robot-org rally, 47/52 misses)
is a factual background claim, not the author's justificatory reasoning, and where independently
checkable against code it was checked rather than trusted.

## Pre-Read Failure-Mode Checklist (M2 adversarial stance, before reading spec.md in detail)

1. REQ numbers gaps/duplicates — checked, see MP-1.
2. AC informal language instead of EARS — checked, see MP-2 (this is the primary defect found).
3. YAML frontmatter missing/wrong-typed fields — checked, see MP-3.
4. Requirements containing HOW not WHAT/WHY — checked, see RQ-3/RQ-4.
5. Broken traceability (orphan REQ or AC) — checked, see Traceability.
6. Hardcoded language-specific tool names — N/A, single-language SPEC, see MP-4.
7. Vague/absent Exclusions — checked, see SC-6.
8. Contradictory requirements — checked, see CN-1/CN-2.
9. SPEC written to justify a predetermined solution rather than following from evidence — checked,
   see § Bias-Prevention below (this was the user's explicit additional ask).

## Must-Pass Results

- **[PASS] MP-1 REQ number consistency**: spec.md — `#### REQ-AI084-001` through
  `#### REQ-AI084-018` (L182, 192, 200, 208, 216, 226, 234, 242, 249, 259, 267, 277, 285, 295, 300,
  308, 314, 320). Sequential 001→018, zero-padded 3-digit, no gaps, no duplicates. Verified via a
  full end-to-end grep of every `#### REQ-AI084-` heading, not spot-checked.

- **[FAIL] MP-2 EARS format compliance**: `acceptance.md` uses **Given-When-Then (GWT) test-scenario
  format exclusively** for all 17 acceptance criteria — zero instances of an EARS-pattern bolded
  sentence (`**WHEN**/**WHILE**/**IF**/**WHERE** ..., the system **SHALL** ...`) anywhere in the
  document. Evidence (representative, all 17 AC blocks follow this identical structure with no
  exception — verified end-to-end, not sampled):
  - acceptance.md:L8-12 (AC-084-001) — `"- **Given** ... - **When** ... - **Then** 그 종목의
    stocks.keywords에 테마 키워드가 채워진다"` — descriptive present-tense "Then X happens", no
    bolded SHALL anywhere in the sentence.
  - acceptance.md:L84-88 (AC-084-013, the P0-HARD "최상위" REQ-013 criterion) — same GWT structure,
    no SHALL.
  - acceptance.md:L102-106 (AC-084-016, the first-mover exclusion criterion) — same GWT structure.
  - acceptance.md:L3 — the document's own header self-declares `"> Given-When-Then 시나리오 + ..."`,
    confirming this was authored as GWT by design, not an accidental drift from EARS.
  - Every AC-084-001 through AC-084-017 heading (acceptance.md:L8,14,20,26,32,40,46,52,58,66,72,78,
    84,90,96,102,108) follows the identical `Given/When/Then` bullet triplet with **zero** bolded
    normative SHALL/SHALL NOT sentences in any "Then" clause.
  - **Direct project precedent for this exact failure mode**: `.moai/reports/plan-audit/
    SPEC-AI-081-review-3.md` L21 records that SPEC-AI-081 **iteration 1** failed this same criterion
    for the identical reason ("Given/When/Then labels used instead of EARS sentences"), and that
    SPEC-AI-081's acceptance.md was subsequently rewritten (by iteration 2/3) into bolded
    WHEN/WHILE/IF...SHALL EARS sentences to reach PASS on MP-2. SPEC-AI-084's acceptance.md has not
    undergone that rewrite — it is at the same pre-fix state SPEC-AI-081 was in at iteration 1, but
    with a larger blast radius (SPEC-AI-081's iteration-1 GWT defect covered ~8 ACs; SPEC-AI-084's
    covers all 17 ACs with no exception).
  - Per MP-2's own literal text — "Given/When/Then test scenarios mislabeled as EARS ... = FAIL" —
    this is a direct, systemic match. Severity: critical, blocks the SPEC unconditionally per M5.

- **[PASS] MP-3 YAML frontmatter validity**: spec.md:L1-13 — `id: SPEC-AI-084` (string, matches
  `SPEC-{DOMAIN}-{NUM}`), `version: 0.1.0` (string), `status: draft` (string), `created_at:
  "2026-07-22"` (quoted ISO date string), `priority: High` (string), `labels: [surge-detection,
  theme-propagation, keyword-basket, news-urgency, keyword-tagging, recall, backend]` (array). All
  six fields present with correct types, matching this project's established plan-audit precedent
  (SPEC-AI-081-review-3.md L49-53 evaluates the identical six-field set). **Non-blocking flag**: the
  project's own canonical frontmatter SSOT (`.claude/rules/moai/development/spec-frontmatter-schema.md`,
  enforced by `internal/spec/lint.go` `FrontmatterSchemaRule`) requires a *different* 12-field
  schema (`id, title, version, status, created, updated, author, priority, phase, module, lifecycle,
  tags`) and explicitly lists `created_at`/`labels` as **rejected snake_case aliases**. spec.md:L1-13
  has `title`, `phase`, `module`, `lifecycle` absent, and uses `created_at`/`labels` (rejected
  aliases) instead of `created`/`tags`. This SPEC would fail `FrontmatterInvalid` lint findings under
  that stricter schema. Recorded as Defect D3 below (minor, since this project's own plan-audit
  practice — established across SPEC-AI-08x — consistently uses the narrower six-field check and
  every other recent SPEC-AI-08x SPEC in this repo appears to follow the same six-field convention,
  not the 12-field lint.go schema); does not change the MP-3 verdict here, but should be reconciled
  project-wide.

- **[N/A] MP-4 Section 22 language neutrality**: N/A — single-language (Python/FastAPI backend)
  detector/scoring SPEC. No multi-language tooling surface; no language-specific tool named as
  primary/default.

## Category Scores (0.0-1.0, rubric-anchored)

| Dimension | Score | Rubric Band | Evidence |
|-----------|-------|-------------|----------|
| Clarity | 0.75 | 0.75 band ("minor ambiguity in one or two requirements a reasonable engineer would resolve consistently") | Core narrative (spec.md §1-§2) is unusually well-evidenced with exact code line citations ([E-1]..[E-6]), independently spot-verified (see below). However, three P0/HARD requirements defer their concrete decision rule to open questions: REQ-009/011 basket-activation threshold → OQ-2/OQ-3 (spec.md:L399-402), and REQ-013 same-day-attribution trigger condition → OQ-5 (spec.md:L405-406, plan.md:L131 DP-5). Deferring "which" parameters to Run is normal at plan-phase, but leaving the *decision rule itself* (all vs conditional; which threshold) undecided for a P0-HARD criterion (REQ-011, REQ-013) is a real, if self-disclosed, ambiguity. |
| Completeness | 1.0 | 1.0 band (all required sections + frontmatter present, at least one exclusion entry) | HISTORY spec.md:L17-34; WHY/Overview spec.md:L37-99; Environment/Assumptions spec.md:L103-170; REQUIREMENTS spec.md:L174-325 (18 REQs across 4 groups); ACCEPTANCE CRITERIA acceptance.md (17 ACs + 7 edge cases + quality gates + DoD); Exclusions spec.md:L328-350 ([X-1]..[X-8], each with a specific rationale, not vague placeholders). |
| Testability | 0.50 | 0.50 band ("several ACs contain weasel words or require judgment calls to evaluate") | (a) Format-level: every AC is GWT prose ("Then X happens") rather than a binary SHALL/SHALL NOT assertion — see MP-2. (b) Substance-level, specifically for the two items flagged by the invocation: AC-084-013 (REQ-013, P0/HARD "최상위") asserts "`same-day 서브지표에 관찰 가능한 편입 증거가 존재한다`" (acceptance.md:L88) without naming the concrete mechanism — see § Verification Item 2 below, this is a genuine gap, not merely a style nit. AC-084-016 (first-mover exclusion) asserts "`측정 대상이 아니다`" (acceptance.md:L106) — a scope/policy statement with no stated mechanical test (e.g., no named evaluation-code branch or config flag that a tester could assert against). No classic weasel words ("적절/합리적/충분히/reasonable/appropriate") were found via full-text grep of both files (zero matches) — the testability gap is structural (GWT + unmechanized assertions), not lexical. |
| Traceability | 1.0 | 1.0 band (every REQ has ≥1 AC, every AC references a valid REQ, no orphans) | All 18 REQ-AI084-0NN entries have ≥1 corresponding AC: 001→AC-001, 002→AC-002, 003→AC-005, 004→AC-003/004, 005→AC-006, 006→AC-007, 007→AC-008, 008→AC-009, 009→AC-010, 010→AC-010, 011→AC-011, 012→AC-012, 013→AC-013, 014→AC-014, 015→AC-014/015, 016→AC-014, 017→AC-016, 018→AC-009/017. Every AC-084-0NN heading (acceptance.md:L8-112) cites an existing REQ-AI084-0NN — no AC references a nonexistent REQ. Verified individually against a full heading grep of both files, not sampled. |

## Bias-Prevention / Evidence Verification (specifically requested)

The SPEC's root-cause narrative rests on six evidence claims ([E-1]-[E-6], spec.md:L114-156). Since
a fabricated or cherry-picked evidence base would be the clearest sign of a predetermined-solution
SPEC, the highest-leverage claims were independently spot-checked against the live codebase (NOT
merely trusted from the SPEC's own prose):

- **[E-1] verified TRUE**: `backend/app/services/news_crawler.py:48` defines `_classify_urgency(...,
  recent_topic_counts: dict[str, int] | None = None)`; the co-mention path exists at L61-62; the
  collection call site at L577 is literally `_classify_urgency(ad["title"])` — confirmed the
  `recent_topic_counts` parameter is never supplied at the real call site, exactly as claimed.
- **[E-3] verified TRUE**: `backend/app/models/stock.py:18` — `keywords: Mapped[list[str] | None] =
  mapped_column(ARRAY(Text), nullable=True)` — column exists exactly as described.
- **[E-2]/[E-6] verified TRUE (existence)**: `detect_theme_group_carry_forward` and
  `_is_same_day_event_horizon_signal` both exist in `backend/app/services/surge_detector.py` /
  `surge_evaluation_service.py` respectively (grep-confirmed), so the "reuse this existing pattern"
  premise is not fabricated.

**Conclusion**: no evidence of the SPEC being retrofitted to justify a predetermined solution — the
causal chain is grounded in specific, independently-verifiable code citations, and the three
directions (A/B/C) are explicitly the outcome of the root-cause analysis rather than a solution
presented first and rationalized after. This check PASSES.

## Verification Item 1 (specifically requested) — does AC-084-016 smuggle back a testable
first-mover AC?

**Finding: NO — genuinely excluded, not smuggled back.** AC-084-016 (acceptance.md:L102-106) and its
governing REQ-AI084-017 (spec.md:L314-318, `[HARD]`) both state the first-mover's *predictive
performance* is explicitly **not** a measurement target ("그 first-mover의 사전예측 성능은 본 SPEC의
인수 기준/성능 측정 대상이 **아니다**"). Cross-checked against the Definition of Done
(acceptance.md:L132-140) and Quality Gates (acceptance.md:L124-131) — neither section contains any
first-mover recall/precision figure, threshold, or count. No AC, quality gate, or DoD checklist item
anywhere in the document reintroduces a first-mover prediction performance target under a different
name. The exclusion is genuine.

**However** (secondary, softer finding): AC-084-016 as *written* is itself not mechanically
testable — "성능 측정 대상이 아니다" is a scope/documentation assertion with no named code artifact
(e.g., no config flag, no evaluation-function branch, no `excluded_first_mover_codes` list analogous
to the existing `excluded_near_limit_up_carry_codes` / `excluded_same_day_event_codes` pattern
already used in `surge_evaluation_service.py:602-607`) that a tester could assert against. This is
recorded as Defect D2 below — it does not smuggle first-mover prediction back in, but it also does
not give a concrete PASS/FAIL test for "this SPEC does not measure first-mover performance."

## Verification Item 2 (specifically requested) — is REQ-013/AC-084-013 same-day horizon
attribution concretely testable, or merely asserted?

**Finding: Merely asserted — a genuine, non-trivial testability gap on the SPEC's own designated
top-priority (R-4, "최상위") P0-HARD requirement.**

- The reused mechanism `_is_same_day_event_horizon_signal` (verified real,
  `surge_evaluation_service.py:506-524`) is a one-line predicate: `metadata.get("horizon") ==
  "same_day"`. The `horizon` key and its `"same_day"` string value are the **entire concrete contract**
  a new detector must satisfy to be recognized by this evaluation path.
- **Neither spec.md, plan.md, nor acceptance.md ever names this field or value** (grep-confirmed —
  zero occurrences of the literal token `horizon` anywhere in the three SPEC-AI-084 documents; see
  above). REQ-AI084-013 (spec.md:L285-293) and AC-084-013 (acceptance.md:L84-88) both describe the
  *outcome* ("귀속되어... 비교된다", "관찰 가능한 편입 증거가 존재한다") and *cite the reused
  function name*, but never state that the new `theme_news_carry` detector's `surge_metadata` payload
  must itself include `"horizon": "same_day"` for that function to actually recognize it — contrast
  with REQ-AI084-009 (spec.md:L249-257), which correctly *does* name the concrete metadata key/value
  the new detector must emit (`surge_metadata.surge_basis=["theme_news_carry"]`).
- Compounding this, `plan.md:L131` explicitly lists **DP-5(=OQ-5): same-day 귀속 트리거 조건(전량 vs
  조건)** as an *open question deferred to Run/annotation* — i.e., even the decision of *which*
  propagated candidates get same-day tagging (all of them, or only some, and by what rule) is
  unresolved at plan-audit time. A P0-HARD, "SPEC 목적이 무효화되므로" (SPEC purpose is invalidated
  if missed) requirement should not leave both (a) the concrete field-level contract AND (b) the
  triggering decision rule open simultaneously — at least one of the two should be pinned at
  plan-phase for R-4 to be genuinely mitigated rather than restated as a risk.
- This is not a hypothetical concern: this exact class of gap is the one SPEC-AI-083's own
  precedent (cited approvingly in spec.md:L152, L165, L291-293 as "REQ-005 최상위 교훈") warns about
  — a detector that emits candidates without a concretely-wired horizon tag produces zero observable
  recall movement, silently. The SPEC correctly identifies the risk pattern by name but does not yet
  close the concrete-contract gap that would make it testable at Run-phase kickoff.

**Conclusion**: REQ-013/AC-084-013 is directionally correct (reusing a real, existing evaluation
path) but is currently an assertion of desired outcome, not a testable specification — a plan-auditor
or engineer cannot today write "PASS when X" for this criterion without first inventing the
`horizon` field-wiring decision that the SPEC itself defers. Recorded as Defect D1 below (major,
independent of the MP-2 GWT-format failure — this is a substance gap, not merely a format gap).

## Defects Found

D1. spec.md:L285-293 (REQ-AI084-013) / acceptance.md:L84-88 (AC-084-013) — The P0-HARD "최상위"
   same-day horizon-attribution requirement never names the concrete `surge_metadata.horizon ==
   "same_day"` field/value contract that the reused `_is_same_day_event_horizon_signal` predicate
   actually checks, and plan.md:L131 (DP-5/OQ-5) defers even the triggering decision rule to Run
   stage — leaving the SPEC's own designated top risk (R-4) asserted rather than concretely
   testable at plan-audit time. — Severity: major.

D2. acceptance.md:L102-106 (AC-084-016) / spec.md:L314-318 (REQ-AI084-017) — Genuinely excludes
   first-mover prediction from scope (verified, not smuggled back — see Verification Item 1), but
   the exclusion itself has no named mechanical test artifact (no config flag / evaluation-code
   branch / excluded-codes list analogous to the existing `excluded_near_limit_up_carry_codes`
   pattern), so a tester cannot write a concrete PASS assertion for this criterion as currently
   worded. — Severity: minor.

D3. spec.md:L1-13 (YAML frontmatter) — Frontmatter uses `created_at`/`labels` (this project's
   established six-field plan-audit convention, PASS under that convention) but is missing
   `title`/`phase`/`module`/`lifecycle` and uses aliases the project's own canonical 12-field schema
   (`.claude/rules/moai/development/spec-frontmatter-schema.md`, enforced by
   `internal/spec/lint.go`) explicitly rejects. Would fail `FrontmatterInvalid` lint findings under
   that stricter schema; does not change this report's MP-3 verdict (six-field precedent applied
   consistently with SPEC-AI-081's audit history) but flags a project-wide schema-convention drift
   worth reconciling. — Severity: minor, informational, out-of-scope-for-this-SPEC-specifically.

D4 (systemic — see MP-2 for full evidence). acceptance.md (entire document, all 17 AC blocks,
   L8-112) — 100% Given-When-Then test-scenario format with zero EARS-pattern bolded SHALL/SHALL
   NOT sentences. This is the primary, must-pass-blocking defect. — Severity: critical.

## Chain-of-Verification Pass

Second-look findings: none — first pass was thorough, verified by re-reading: (1) every one of the
18 REQ-AI084-0NN entries in spec.md end-to-end for EARS-pattern purity and HOW-leakage into SHALL
bodies (none found — implementation detail is consistently confined to "근거"/"[E-N]" footnotes,
matching this project's established acceptable pattern per SPEC-AI-081-review-3.md's treatment of
"구현 참고"/"근거" footnotes); (2) every AC-084-0NN heading and Given/When/Then triplet in
acceptance.md, including the edge cases (EC-1..EC-7), quality gates, and Definition of Done sections
— confirmed no hidden re-introduction of a first-mover performance target anywhere outside AC-016
itself; (3) REQ numbering sequence 001→018 re-confirmed via full-document reading, not spot-check;
(4) all 18 REQ-to-AC traceability links re-checked individually; (5) the Exclusions section
(spec.md:L328-350, [X-1]..[X-8]) re-read for specificity — each entry cites a concrete REQ/rationale,
none is a vague placeholder; (6) checked for contradictions beyond single-requirement scope —
REQ-009 (propagate on anchor activation) vs REQ-011 (require theme-confirmation gate before
propagating) are complementary, not contradictory (011 gates 009); [X-1]/[X-3] exclusions are
consistent with REQ-017/REQ-016 respectively; no contradiction found. (7) Independently
spot-verified three of the six [E-N] evidence citations against the live `backend/` codebase (see
§ Bias-Prevention above) rather than trusting the SPEC's self-reported code citations.

## Recommendation

FAIL — this is iteration 1 of a maximum 3. Fix instructions for manager-spec before resubmission:

1. **Rewrite all 17 acceptance.md criteria from Given-When-Then into EARS-pattern bolded sentences**
   (`**WHEN**/**WHILE**/**IF**...THEN.../**WHERE**`, the system `**SHALL**`/`**SHALL NOT**`
   `[response]`), matching the corrected style SPEC-AI-081's acceptance.md reached by its iteration 2
   (see `.moai/reports/plan-audit/SPEC-AI-081-review-3.md` D3/D5 for the accepted before/after
   pattern: fold the `Given` precondition into either a `WHILE` clause or an unbolded non-normative
   preamble, and convert the `Then` clause into the sole bolded `SHALL`/`SHALL NOT` sentence per
   criterion). This is the single blocking fix for MP-2.

2. **acceptance.md:L84-88 (AC-084-013) / spec.md:L285-293 (REQ-013)**: name the concrete
   `surge_metadata` field/value contract (e.g., state explicitly that the new `theme_news_carry`
   detector's emitted metadata SHALL include `"horizon": "same_day"`, mirroring how REQ-009 already
   names `surge_basis=["theme_news_carry"]`), and resolve OQ-5's "all vs conditional" question (or
   explicitly state the plan-phase default answer with Run-stage override authority) so this P0-HARD
   criterion has an actual field-level PASS/FAIL test at Run kickoff, not just a function-name
   citation.

3. **acceptance.md:L102-106 (AC-084-016)**: add a named mechanical test artifact for the first-mover
   exclusion (e.g., an explicit statement that the evaluation pipeline SHALL NOT include first-mover
   `predicted_set`/`actual_set` membership for candidates lacking a same-day-basket-propagation
   basis, analogous to the existing `excluded_near_limit_up_carry_codes` pattern in
   `surge_evaluation_service.py:602-607`), so the exclusion is testable rather than a documentation-only
   assertion.

4. (Non-blocking, project-wide, not specific to this SPEC) Consider reconciling the six-field
   plan-audit frontmatter convention against the 12-field `spec-frontmatter-schema.md` SSOT so
   future SPECs are not exposed to a latent `FrontmatterInvalid` lint gap.

No changes needed to REQ numbering, Completeness (all sections present), or REQ↔AC traceability —
all independently verified correct in this iteration.
