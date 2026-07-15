# SPEC Review Report: SPEC-AI-081
Iteration: 2/3
Verdict: FAIL
Overall Score: 0.85 (category average; verdict forced to FAIL by M5 Must-Pass Firewall regardless of this number)

Reasoning context ignored per M1 Context Isolation. This audit is based solely on
`.moai/specs/SPEC-AI-081/spec.md`, `acceptance.md`, and `plan.md`, cross-checked against
`backend/app/services/disclosure_impact_scorer.py` for factual accuracy of cited literal values.
The defect list supplied in the invocation prompt was used only as the iteration-2 regression
checklist (per the Retry Loop Contract for iteration 2+), not as an author-reasoning shortcut.

## Must-Pass Results

- [PASS] MP-1 REQ number consistency: spec.md:L141-244 — REQ-AI081-001 through REQ-AI081-008,
  sequential, zero-padded 3-digit, no gaps, no duplicates. Verified end-to-end (not spot-checked).

- [FAIL] MP-2 EARS format compliance: acceptance.md contains multiple AC clauses that do not match
  exactly one of the five canonical EARS patterns (Ubiquitous / Event-Driven / State-Driven /
  Optional / Unwanted) as anchored in M3. Evidence:
  - acceptance.md:L22-26 (AC-081-001, RED bullet) — `"**WHILE** 코드베이스가 ... 인 동안, **WHEN**
    score_disclosure_impact()가 ... 호출되면, the system **SHALL** ..."` — combines a State-Driven
    trigger (WHILE) and an Event-Driven trigger (WHEN) inside a single criterion sentence. This is
    not one of the five listed patterns.
  - acceptance.md:L39-44 (AC-081-002, RED bullet) — identical WHILE+WHEN hybrid construction.
  - acceptance.md:L82-84 and L85-87 (AC-081-005, bullets 1-2) — identical WHILE+WHEN hybrid,
    repeated twice.
  - acceptance.md:L97-100 (AC-081-006, bullet 1) — identical WHILE+WHEN hybrid.
  - acceptance.md:L53-54 (AC-081-002, "(명시 비검증)" bullet) — `"본 AC의 통과 기준은 score > 20.0
    (상향)을 요구 조건으로 포함하지 않는다..."` — plain prose scope-note with no "the system SHALL"
    clause at all; it is presented as a numbered bullet of the AC (i.e., part of the testable
    criterion set) but matches none of the five patterns.
  - acceptance.md:L127-129 (AC-081-008, bullet 1) — `"**WHERE** ... the system **MAY** ... 로그를
    방출한다"` — the Optional EARS pattern per M3 requires the modal verb "shall" ("Where [feature
    exists], the system shall [response]"); substituting "MAY" is a non-canonical deviation. The
    same MAY substitution recurs at spec.md:L242 (REQ-AI081-008).
  Per MP-2's literal text — "Every acceptance criterion must match one of the five EARS patterns...
  mixed informal/formal within a single criterion = FAIL" — five distinct AC sub-clauses combine two
  formal trigger keywords in one sentence and one AC sub-clause has no EARS structure at all. This is
  a materially different manifestation of the original defect (raw Given/When/Then labels are indeed
  gone), but the criterion as strictly written in this audit's own rubric is still not satisfied
  end-to-end. Per HARD RULE "when in doubt, FAIL," this is marked FAIL.

- [PASS] MP-3 YAML frontmatter validity: spec.md:L1-13 — `id: SPEC-AI-081` (string, matches
  SPEC-{DOMAIN}-{NUM}), `version: 0.2.0` (string), `status: draft` (string), `created_at: "2026-07-15"`
  (quoted ISO date string), `priority: High` (string), `labels: [disclosure-scoring,
  surge-detection, backend]` (array). All six required fields present with correct types. The two
  previously-missing fields (`created_at`, `labels`) are now present and correctly typed.

- [N/A] MP-4 Section 22 language neutrality: N/A — this SPEC is a single-language (Python/FastAPI
  backend) scoring-logic change with no multi-language tooling surface. No language-specific tool
  names are hardcoded as primary/default.

## Category Scores (0.0-1.0, rubric-anchored)

| Dimension | Score | Rubric Band | Evidence |
|-----------|-------|-------------|----------|
| Clarity | 0.75 | 0.75 band ("minor ambiguity in one or two requirements that a reasonable engineer would resolve consistently") | spec.md:L143-146 ("이 인식은 공백·특수문자 표기 변형을 정규화한 후 수행 **SHALL** 한다") and spec.md:L230-231 ("...작성·통과되어 있어야 **SHALL** 한다") place the SHALL keyword in mid/end-of-sentence Korean-grammar positions rather than as the sentence's normative verb head; semantically resolvable but stylistically awkward. Core content (§2 E-1..E-6 code-line-cited evidence, §3 requirements) is otherwise unambiguous. |
| Completeness | 1.0 | 1.0 band (all required sections + frontmatter present, at least one exclusion entry) | HISTORY spec.md:L17-33; WHY/Context spec.md:L37-70 (§1); WHAT/REQUIREMENTS spec.md:L139-244 (§3, 8 REQs); Exclusions spec.md:L247-276 (§4, [X-1]..[X-9], each with specific rationale); frontmatter spec.md:L1-13 complete; ACCEPTANCE CRITERIA in acceptance.md (project convention: spec.md/acceptance.md/plan.md triad, cross-referenced consistently via REQ-XXX ids). |
| Testability | 0.75 | 0.75 band (one AC not precisely binary-testable, minor interpretation needed) | Score literals throughout acceptance.md are exact and binary-testable (e.g., acceptance.md:L24 `score == 25.0`, L46-47 `score == -10.0`, L74 `score == 5.0`) with no weasel words ("appropriate"/"reasonable"/"adequate") found anywhere in the document. AC-081-008 (acceptance.md:L127-129) uses "MAY" for the positive case, which is inherently non-binary-testable in isolation (a missing log is not a failure) — mitigated by an explicit paired SHALL NOT negative-case test (acceptance.md:L130-131), and the criterion is explicitly marked P2/optional in the Definition of Done (acceptance.md:L151). |
| Traceability | 1.0 | 1.0 band (every REQ has >=1 AC, every AC references a valid REQ, no orphans) | REQ-001→AC-081-001 (acceptance.md:L18), REQ-002→AC-081-002 (L35), REQ-003→AC-081-009 (L135), REQ-004→AC-081-005 (L80), REQ-005→AC-081-003/004 (L58, L70), REQ-006→AC-081-006 (L95), REQ-007→AC-081-007 (L112), REQ-008→AC-081-008 (L125). All 8 REQ-AI081-XXX ids in spec.md have at least one corresponding AC-081-XXX heading citing them; no AC references a nonexistent REQ number. |

## Defects Found

D1. acceptance.md:L22-26, L39-44, L82-87, L97-100 — Five AC sub-clauses combine State-Driven (WHILE)
    and Event-Driven (WHEN) triggers inside a single sentence, which does not match exactly one of
    the five EARS patterns defined in this audit's M3 rubric — Severity: critical (blocks MP-2).

D2. acceptance.md:L53-54 — The "(명시 비검증)" bullet under AC-081-002 is plain prose with no
    "the system SHALL/SHALL NOT" clause and no EARS trigger keyword; it functions as a scope
    disclaimer but is formatted as a numbered criterion bullet — Severity: major (blocks MP-2).

D3. acceptance.md:L127-129 (and spec.md:L242, REQ-AI081-008) — Optional-pattern clause uses "MAY"
    instead of the canonical "SHALL" modal verb required by the Optional EARS pattern
    ("Where [feature exists], the system shall [response]") — Severity: minor (P2/optional
    criterion only, does not affect must-pass REQs 001-007, but still contributes to the MP-2
    finding since AC-081-008 is a numbered acceptance criterion in the document).

D4. spec.md:L143-146, L230-231 — SHALL keyword placed mid/end-of-Korean-sentence rather than as the
    clear normative verb head of the clause ("정규화한 후 수행 SHALL 한다", "작성·통과되어 있어야
    SHALL 한다") — Severity: minor (style/clarity only; semantic meaning is still recoverable and
    consistent with the surrounding evidence footnotes).

D5 (carried, informational, unresolved by design). spec.md:L9 — `priority: High` uses capitalized
    casing rather than the lowercase convention implied by FC-5 ("critical, high, medium, low").
    HISTORY (spec.md:L31-33) explicitly documents this as a deliberate decision to match the rest of
    the SPEC-AI-* series. Not treated as a blocking defect (informational only, consistent with the
    prior iteration's classification) — Severity: minor/informational.

## Chain-of-Verification Pass

Second-look findings: One additional issue found beyond the initial pass — the AC-081-002
"(명시 비검증)" bullet (D2) was not caught until a full line-by-line re-read of every AC sub-bullet
(not just the RED/GREEN pairs). Re-verified by re-reading: (1) every REQ-AI081-00X entry in spec.md
end-to-end including all "구현 참고"/"근거" footnotes for residual HOW-leakage, (2) every AC-081-00X
heading and every sub-bullet within each AC block in acceptance.md for EARS-pattern conformance
(not just the first bullet of each AC), (3) REQ numbering sequence 001→008 checked as a continuous
scan rather than sampling, (4) all 8 REQ-to-AC traceability links checked individually against
acceptance.md headings, (5) the Exclusions section (§4, [X-1]..[X-9]) re-read for specificity —
confirmed each item cites a concrete rationale, not vague boilerplate, (6) cross-checked the three
numeric literals central to the prior D6 contradiction (25.0, 20.0, -10.0, 5.0, 50.0-derived >=30.0)
directly against `backend/app/services/disclosure_impact_scorer.py:41-49` (`_BASE_IMPACT_BY_TYPE`)
and `:89-109` (`_KEYWORD_TIER1`/`_get_keyword_tier_multiplier`) — all values are factually accurate,
not just internally consistent. No contradictions found between REQ-001/002/005 (matched-keyword vs
unmatched-keyword cases are mutually exclusive by construction, no overlap).

## Regression Check (Iteration 2+)

Defects from previous iteration (as supplied in this invocation's task context — no prior report
file was found on disk at `.moai/reports/plan-audit/SPEC-AI-081-review-1.md`):

- MP-2 (ACs were Given/When/Then instead of EARS sentences) — **PARTIALLY RESOLVED /
  RECLASSIFIED AS UNRESOLVED**: The literal Given/When/Then labeling is gone; all AC clauses now use
  bolded EARS trigger keywords (WHILE/WHEN/IF...THEN/WHERE). However, the must-pass criterion as
  written in this audit's own rubric ("every AC must match one of the five patterns... mixed
  informal/formal within a single criterion = FAIL") is still not satisfied — see D1/D2/D3 above.
  This is a different manifestation of the same underlying gap (full EARS conformance), not a fully
  new defect, so it is tracked as UNRESOLVED rather than a fresh finding for stagnation-detection
  purposes.

- MP-3 (missing labels/created_at frontmatter fields) — **RESOLVED**: spec.md:L6 `created_at:
  "2026-07-15"` and spec.md:L12 `labels: [disclosure-scoring, surge-detection, backend]` are both
  present with correct types.

- D3 (REQ-003 had zero AC coverage) — **RESOLVED**: acceptance.md:L135-146, AC-081-009 explicitly
  headed "(REQ-003, ai_summary 비의존성 검증)" and plan.md:L99-106 (§4) implements the corresponding
  technical approach with a milestone entry (plan.md:L147-149, milestone 5).

- D4/D5 (HOW-in-WHAT leakage — code literals/function names embedded in SHALL clauses) —
  **RESOLVED**: Re-read every REQ-AI081-00X SHALL/SHALL NOT clause body in spec.md (§3). Function
  names, config keys, and internal variable names (`score_disclosure_impact()`,
  `_get_keyword_tier_multiplier`, `disclosure_content_aware_scoring.enabled`,
  `dart_crawler._classify_report_type()`, etc.) now appear only inside clearly separated "근거"
  (rationale) or "구현 참고" (implementation note) footnote bullets — e.g., spec.md:L149-152 (REQ-001),
  spec.md:L196-198 (REQ-004), spec.md:L222-226 (REQ-006), spec.md:L236-237 (REQ-007) — not inside the
  primary SHALL clause sentence. Domain data-field references retained inline (`report_type`,
  `report_name`, `ai_summary`) are legitimate business vocabulary, not code-internal HOW detail.

- D6 (contradiction between OQ-1 and AC-081-002 on the -10.0 score value) — **RESOLVED**: spec.md:L172-176
  (REQ-AI081-002 "설계 결정") and spec.md:L326-329 (§7, "참고 (舊 OQ-1 해소)") both state the reclassified
  disclosure inherits the "발행공시" flat base of -10 with no separate floor logic. acceptance.md:L45-49
  (AC-081-002 GREEN) asserts `score == -10.0`. Verified against source:
  `backend/app/services/disclosure_impact_scorer.py:46` confirms `"발행공시": -10` in
  `_BASE_IMPACT_BY_TYPE`. All three artifacts (spec, acceptance, code) now agree.

- D7 (priority casing, informational only) — **UNRESOLVED BY DESIGN, still informational**:
  spec.md:L9 `priority: High` remains capitalized. spec.md:L31-33 documents this as an explicit,
  reasoned decision (consistency with the rest of the SPEC-AI-* series) rather than an oversight.
  Consistent with the prior iteration's "informational only" classification — not elevated to a
  blocking defect in this iteration either.

Stagnation check: MP-2 has now failed in both iteration 1 and iteration 2, but the specific failure
mode changed materially (GWT mislabeling → hybrid-pattern/MAY-modal issues), which reflects genuine
(if incomplete) progress rather than the agent repeating the identical unaddressed defect. This does
NOT meet the "blocking defect — no progress" bar, since the underlying text was substantively
rewritten and three of the four prior findings (MP-3, D3, D4/D5, D6) are fully and verifiably
resolved. This should be flagged to manager-spec as "close but not yet conformant" rather than
"stuck," with the fix now narrowly scoped to specific citable lines rather than a systemic rewrite.

## Recommendation

FAIL — one must-pass criterion (MP-2) remains unsatisfied. The fix is narrow and mechanical; the SPEC
does not need to be substantially rewritten again. Specific, actionable instructions for
manager-spec:

1. Split every "WHILE ..., WHEN ..., the system SHALL ..." hybrid sentence into a pure single-pattern
   EARS sentence. Two concrete options:
   - (a) Fold the WHILE precondition into a plain-prose test-setup preamble outside the bolded EARS
     sentence (e.g., "Test setup: `disclosure_content_aware_scoring.enabled=true`." as a non-EARS
     scaffolding line, followed by a pure "**WHEN** `score_disclosure_impact()`가 ... 호출되면, the
     system **SHALL** ..." sentence), or
   - (b) Keep WHILE as the sole pattern and restate the WHEN-trigger content as the precondition's
     descriptive continuation without a second bolded WHEN keyword (pure State-Driven form).
   Apply this to: acceptance.md:L22-26 (AC-081-001 RED), L39-44 (AC-081-002 RED), L82-84 and L85-87
   (AC-081-005 bullets 1-2), L97-100 (AC-081-006 bullet 1).

2. Rewrite acceptance.md:L53-54 (the "(명시 비검증)" bullet in AC-081-002) as either (a) a proper
   Unwanted-pattern sentence ("**IF** `score` is asserted for the 038880-type input, **THEN** the
   system test **SHALL NOT** require `score > 20.0`" — awkward but formally compliant), or more
   cleanly (b) move this scope clarification out of the numbered AC bullet list entirely and into the
   existing prose "범위 편차 고지" callout box at acceptance.md:L10-14, which is already correctly
   treated as non-normative narrative rather than a testable criterion.

3. Change "MAY" to "SHALL" in acceptance.md:L127-129 (AC-081-008 bullet 1) and spec.md:L242
   (REQ-AI081-008), consistent with the canonical Optional EARS pattern ("Where [feature exists], the
   system shall [response]"). The optionality of the entire requirement is already correctly
   expressed via the P2/"MAY 한다" framing at the requirement level (Definition of Done marks it
   optional) — the AC itself, if written, should still use "shall" for the response given the
   trigger condition holds; if true optionality of the behavior itself must be preserved, phrase it
   as a State-Driven "WHILE this observability feature is enabled, the system SHALL emit..." wrapped
   in a config flag as REQ-004 already does for other optional-flag behavior, rather than using MAY.

4. Optional (non-blocking) polish: reposition the SHALL keyword to the front of the normative clause
   in spec.md:L143-146 and L230-231 for clearer parsing (e.g., "the system SHALL perform this
   recognition only after normalizing whitespace/special-character variants" rather than appending
   "수행 SHALL 한다" at the sentence tail).

No changes are needed to spec.md's REQ numbering, frontmatter, REQ-003/AC-081-009 traceability, or
the -10.0/25.0/20.0/5.0 score literals — all of these are independently verified correct against
`backend/app/services/disclosure_impact_scorer.py` and internally consistent across spec.md,
acceptance.md, and plan.md.
