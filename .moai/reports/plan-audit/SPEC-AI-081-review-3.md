# SPEC Review Report: SPEC-AI-081
Iteration: 3/3 (FINAL ALLOWED ITERATION)
Verdict: FAIL
Overall Score: 0.85 (category average; verdict forced to FAIL by M5 Must-Pass Firewall regardless of this number)

Reasoning context ignored per M1 Context Isolation. This audit is based solely on
`.moai/specs/SPEC-AI-081/spec.md` and `.moai/specs/SPEC-AI-081/acceptance.md`, cross-checked
against `.moai/reports/plan-audit/SPEC-AI-081-review-2.md` strictly for the mandatory
iteration-2+ regression check. The invocation prompt's claim that "manager-spec has since made
targeted fixes... addressing exactly these points" was treated as an unverified assertion, not a
conclusion — every AC bullet in acceptance.md and every REQ in spec.md was independently
re-read end-to-end for EARS conformance, not just the specific lines cited as fixed in iteration 2.

## Must-Pass Results

- [PASS] MP-1 REQ number consistency: spec.md:L151,164,188,199,210,220,238,249 —
  REQ-AI081-001 through REQ-AI081-008, sequential, zero-padded 3-digit, no gaps, no duplicates.
  Re-verified via a fresh grep scan of `^### REQ-AI081-` across spec.md (end-to-end, not
  spot-checked).

- [FAIL] MP-2 EARS format compliance: The three defect categories cited in iteration 2
  (D1 WHILE+WHEN hybrid sentences, D2 bare-prose non-normative bullet, D3 MAY-instead-of-SHALL)
  are genuinely and correctly resolved. However, an independent full re-scan of every AC bullet
  (per M6 Chain-of-Verification) found two NEW, previously-unflagged instances of the same
  underlying defect class — a single AC bullet containing two independent normative
  (SHALL/SHALL NOT) assertions, where the second assertion lacks its own EARS trigger keyword
  and/or uses informal Korean modal phrasing instead of a bolded SHALL/SHALL NOT. Evidence:
  - acceptance.md:L62-66 (AC-081-003) — `"...the system **SHALL** \`score == 20.0\`(...)을
    반환한다 — 신호가 없는 공시는 the system **SHALL NOT** 인위적으로 상향한다."` This bullet
    contains one WHEN-triggered positive SHALL clause, then an em-dash-separated second clause
    ("신호가 없는 공시는 the system SHALL NOT...") that has its own independent subject and modal
    verb but no trigger keyword of its own (no WHEN/IF/WHILE/WHERE) — a compound two-assertion
    sentence, not a single EARS pattern instance.
  - acceptance.md:L145-148 (AC-081-009, second bullet) — `"the system **SHALL NOT** \`ai_summary\`
    필드의 값 존재 자체를 ... 사용한다 — \`ai_summary\`가 채워진 경우 ... 그 매칭은 텍스트 내용
    자체(...)에 기인해야 하며 필드의 None 여부 자체가 분기 조건이 되어서는 안 된다."` The first
    clause is a clean Ubiquitous "the system SHALL NOT X" sentence. The second clause, joined by
    an em-dash, uses unbolded informal Korean modal constructions ("~에 기인해야 하며", "~안
    된다" — "must be attributable to", "must not become") instead of the canonical bolded
    SHALL/SHALL NOT keyword, and introduces a second independent normative assertion within the
    same bullet.
  Per MP-2's own literal text (unchanged from iteration 2's citation) — "mixed informal/formal
  within a single criterion = FAIL" — both bullets above are a direct match for this failure
  condition. This is a materially different pair of instances than the ones iteration 2 cited
  (which are now correctly fixed), but the underlying defect *category* — an AC bullet asserting
  more than one normative statement, or mixing a bolded EARS clause with an unbolded informal
  modal clause — recurs. Per HARD RULE "when in doubt, FAIL," this is marked FAIL.

- [PASS] MP-3 YAML frontmatter validity: spec.md:L1-13 — `id: SPEC-AI-081` (string, matches
  SPEC-{DOMAIN}-{NUM}), `version: 0.3.0` (string), `status: draft` (string), `created_at:
  "2026-07-15"` (quoted ISO date string), `priority: High` (string), `labels:
  [disclosure-scoring, surge-detection, backend]` (array). All six required fields present with
  correct types. No regression from iteration 2's PASS.

- [N/A] MP-4 Section 22 language neutrality: N/A — single-language (Python/FastAPI backend)
  scoring-logic SPEC, no multi-language tooling surface, no language-specific tool named as
  primary/default.

## Category Scores (0.0-1.0, rubric-anchored)

| Dimension | Score | Rubric Band | Evidence |
|-----------|-------|-------------|----------|
| Clarity | 0.75 | 0.75 band ("minor ambiguity in one or two requirements that a reasonable engineer would resolve consistently") | spec.md:L155-156 and spec.md:L240-241 still place the SHALL keyword mid/end-of-Korean-sentence ("수행 SHALL 한다", "작성·통과되어 있어야 SHALL 한다") — unchanged from iteration 2, previously classified as minor/non-blocking style issue, still unresolved but not elevated. Core §2/§3 content remains otherwise clear and code-cited. |
| Completeness | 1.0 | 1.0 band (all required sections + frontmatter present, at least one exclusion entry) | HISTORY spec.md:L17-43 (now includes v0.3.0 entry documenting the iteration-2 fixes); WHY spec.md:L47-81; REQUIREMENTS spec.md:L149-254 (8 REQs); Exclusions spec.md:L258-287 ([X-1]..[X-9], each with specific rationale, unchanged and re-verified); frontmatter complete. |
| Testability | 0.75 | 0.75 band (one AC not precisely binary-testable, minor interpretation needed) | The prior Testability concern (AC-081-008's MAY substitution) is resolved — acceptance.md:L129 now reads "the system **SHALL**". A new, narrower testability concern replaces it: acceptance.md:L146-148 (AC-081-009 second bullet) asserts an implementation-reasoning constraint ("matching must be attributable to the text content itself") that is not directly black-box observable in the same way as the score-equality assertions elsewhere in the document — it is testable only indirectly via the paired dual-input-equivalence test in the same AC's first bullet (L140-144). All score-literal assertions elsewhere (e.g., L24 `score == 25.0`, L46-47 `score == -10.0`, L76 `score == 5.0`) remain exact and binary-testable; no weasel words ("appropriate"/"reasonable"/"adequate") found anywhere in the document. |
| Traceability | 1.0 | 1.0 band (every REQ has >=1 AC, every AC references a valid REQ, no orphans) | REQ-001->AC-081-001 (acceptance.md:L18), REQ-002->AC-081-002 (L35), REQ-003->AC-081-009 (L138), REQ-004->AC-081-005 (L82), REQ-005->AC-081-003/004 (L60, L72), REQ-006->AC-081-006 (L97), REQ-007->AC-081-007 (L114), REQ-008->AC-081-008 (L127). All 8 REQ-AI081-XXX ids in spec.md have at least one corresponding AC-081-XXX heading citing them; no AC references a nonexistent REQ number. Re-verified individually against a fresh heading grep of both files, not sampled. |

## Defects Found

D1 (NEW in iteration 3). acceptance.md:L62-66 (AC-081-003) — The bullet combines a WHEN-triggered
   positive `the system SHALL score == 20.0` clause with a second, untriggered
   `the system SHALL NOT` clause joined by an em-dash, forming a compound two-assertion sentence
   rather than a single EARS pattern instance — Severity: critical (blocks MP-2). This is the
   same underlying defect class flagged in iteration 2 (multiple normative clauses combined in one
   criterion), recurring in a location iteration 2 did not cite.

D2 (NEW in iteration 3). acceptance.md:L145-148 (AC-081-009, second bullet) — The bullet opens with
   a clean bolded `the system SHALL NOT` clause, then continues past an em-dash with a second
   normative assertion phrased in unbolded, informal Korean modal language ("~에 기인해야 하며",
   "~안 된다") rather than the canonical bolded SHALL/SHALL NOT construction — a direct instance of
   "mixed informal/formal within a single criterion" per MP-2's own text — Severity: critical
   (blocks MP-2).

D3 (carried, RESOLVED, listed for completeness). acceptance.md:L22-26, L39-44, L84-89, L99-102 —
   The five WHILE+WHEN hybrid sentences flagged in iteration 2 are now each single-pattern: the
   RED bullets (AC-081-001, AC-081-002) fold the WHILE precondition into an unbolded, non-EARS
   prose preamble ("테스트 전제: ...") followed by a pure WHEN...SHALL sentence; the AC-081-005
   bullets keep WHILE as the sole pattern with the WHEN-content restated as unbolded descriptive
   continuation ("...호출될 때마다"); the AC-081-006 bullet 1 drops WHILE entirely and is now pure
   WHEN...SHALL. Verified — Severity: N/A (resolved).

D4 (carried, RESOLVED, listed for completeness). acceptance.md:L54-56 — The former "(명시 비검증)"
   bare-prose bullet is now explicitly labeled `**참고 (비검증 범위, 비-EARS 서술 — 통과 기준
   아님)**` and is textually separated from the numbered SHALL/SHALL NOT criterion bullets above it
   — clearly marked as non-normative narrative rather than presented as a testable AC entry.
   Verified — Severity: N/A (resolved).

D5 (carried, RESOLVED, listed for completeness). acceptance.md:L129, spec.md:L251 — `MAY` has been
   replaced with `SHALL` in both the AC-081-008 bullet 1 and REQ-AI081-008, consistent with the
   canonical Optional EARS pattern ("Where [feature exists], the system shall [response]").
   Verified — Severity: N/A (resolved). Note: a new companion bullet was added at
   acceptance.md:L133-134 using `WHERE ..., the system SHALL NOT ...` for the negative case — this
   is accepted as a valid Optional-pattern instantiation with a negated response, consistent with
   this document's own established treatment of `IF...THEN...SHALL NOT` as a valid Unwanted-pattern
   instantiation elsewhere (e.g., acceptance.md:L103-107, L108-110) — not flagged as a new defect.

D6 (carried, unresolved by design, minor, non-blocking). spec.md:L155-156, L240-241 — SHALL keyword
   still placed mid/end-of-Korean-sentence rather than as the clause's normative verb head
   ("수행 SHALL 한다", "작성·통과되어 있어야 SHALL 한다"). This is in spec.md §3 REQUIREMENTS
   (Group 3 scope), not acceptance.md, and was explicitly classified as "optional, non-blocking
   polish" in iteration 2's recommendation — remains unresolved but does not block MP-2 (which is
   scoped to acceptance criteria) — Severity: minor/style.

D7 (carried, unresolved by design, informational). spec.md:L9 — `priority: High` retains
   capitalized casing rather than lowercase. spec.md:L31-33/L34 HISTORY documents this as a
   deliberate, reasoned decision (consistency with the rest of the SPEC-AI-* series), consistent
   with iteration 2's "informational only" classification — Severity: minor/informational.

## Chain-of-Verification Pass

Second-look findings: Two additional critical defects (D1, D2 above) were found only after a
full line-by-line re-read of every AC-081-00X bullet in acceptance.md — not just the specific
lines iteration 2 cited as needing repair. Initial pass (checking only the previously-cited
lines: L22-26, L39-44, L53-54, L82-87, L97-100, L127-129) would have concluded PASS on MP-2. The
second pass re-read: (1) every REQ-AI081-00X entry in spec.md end-to-end for EARS-pattern purity
and residual HOW-leakage — none of the "구현 참고"/"근거" footnotes leaked implementation detail
into SHALL clause bodies (unchanged, still resolved from iteration 2); (2) every AC-081-00X
heading and every sub-bullet within each AC block in acceptance.md, including AC-081-003,
AC-081-004, AC-081-007, and AC-081-009 which were not individually cited as defective in
iteration 2's report — this is where D1 and D2 above were discovered; (3) REQ numbering sequence
001->008 re-confirmed via a fresh grep, checked as a continuous scan; (4) all 8 REQ-to-AC
traceability links re-checked individually against acceptance.md headings, including the new
AC-081-009 (REQ-003) and dual-AC REQ-005 (AC-081-003 + AC-081-004) mapping; (5) the Exclusions
section (spec.md §4, [X-1]..[X-9]) re-read for specificity — unchanged, still confirmed
non-vague; (6) the frontmatter re-verified field-by-field against FC-1 through FC-6 for type and
presence.

Stagnation check: MP-2 has now failed in iteration 1, iteration 2, and iteration 3. The specific
failure mode has changed each time (GWT mislabeling -> WHILE+WHEN hybrid/bare-prose/MAY-modal ->
compound-clause/informal-modal mixing), which on its face looks like incremental progress rather
than a frozen unaddressed defect. However, the *pattern of the fix* across iterations 2 and 3 is
itself concerning: manager-spec has, in both iterations, corrected exactly and only the specific
lines cited in the prior audit report, without performing a comprehensive sweep of the entire
acceptance.md document for the same underlying defect class (a bullet asserting more than one
independent normative clause, or mixing bolded-formal with unbolded-informal modal language).
This is flagged as a blocking process defect — not a "no progress" stagnation in the strict sense
(three concrete iteration-2 items are verifiably fixed), but a "narrow patch, not systemic fix"
pattern that has now produced a third consecutive MP-2 failure. Per the Retry Loop Contract, since
this is iteration 3 (final allowed iteration) and the verdict is FAIL, this report is escalated
per the "final escalation report" clause below.

## Regression Check (Iteration 2+)

Defects from iteration 2's report:

- D1 (iteration 2): Five WHILE+WHEN hybrid AC sentences — **RESOLVED**: acceptance.md:L22-26,
  L39-44, L84-86, L87-89, L99-102 each now use a single EARS trigger keyword per bolded sentence.
  Verified individually.

- D2 (iteration 2): acceptance.md's "(명시 비검증)" bare-prose bullet — **RESOLVED**:
  acceptance.md:L54-56 is now explicitly labeled as non-EARS reference narrative, separated from
  the numbered criterion bullets, and explicitly states it is not a pass condition.

- D3 (iteration 2): AC-081-008 / REQ-AI081-008 `MAY` instead of `SHALL` — **RESOLVED**:
  acceptance.md:L129 and spec.md:L251 both now use `SHALL`.

- D4 (iteration 2): spec.md:L143-146, L230-231 SHALL keyword mid/end-of-sentence placement —
  **UNRESOLVED, but non-blocking by iteration 2's own classification** ("optional, non-blocking
  polish"). Current locations: spec.md:L155-156, L240-241. Text is materially unchanged.

- D5 (iteration 2, informational): spec.md:L9 `priority: High` capitalization — **UNRESOLVED BY
  DESIGN**, unchanged, still documented as an intentional decision in HISTORY. Not blocking,
  consistent with prior classification.

Overall regression verdict: 3 of 3 blocking (MP-2-relevant) defects from iteration 2 are
genuinely resolved with no regression. However, the independent iteration-3 re-audit (required by
M6 Chain-of-Verification, which is not satisfied merely by re-checking previously-cited lines)
surfaced two new MP-2-blocking defects (D1/D2 in this report) in AC bullets that iteration 2 did
not individually flag. Per the Retry Loop Contract's stagnation rule, this does not meet the
"identical defect unchanged across all three iterations" bar (the specific defects differ each
time), so it is not declared a strict "blocking defect" in the technical sense — but it is
escalated below as a final-iteration FAIL requiring user intervention.

## Recommendation

FAIL — this is iteration 3, the final allowed iteration. Per the Retry Loop Contract, this
constitutes a final escalation. Full defect history across all three iterations:

- Iteration 1: MP-2 FAIL (Given/When/Then labels used instead of EARS sentences); other
  unspecified defects per iteration 1 context (no iteration-1 report file exists on disk;
  iteration 2's report notes this and treated iteration 1 findings as supplied via invocation
  context only).
- Iteration 2: MP-2 FAIL (WHILE+WHEN hybrid sentences x5, bare-prose non-EARS bullet x1, MAY
  instead of SHALL x1). All other must-pass criteria (MP-1, MP-3, MP-4) PASS/N/A.
- Iteration 3 (this report): MP-2 FAIL (two new compound-clause / informal-modal-mixing
  instances in AC-081-003 and AC-081-009, previously unflagged). All other must-pass criteria
  (MP-1, MP-3, MP-4) PASS/N/A, no regression.

Recommendation: Escalate to user for manual intervention per the Retry Loop Contract (iteration 3
FAIL exhausts the automatic retry budget). Before re-attempting a 4th cycle (if the user
authorizes one), manager-spec should be instructed to perform a full-document EARS-purity sweep
of acceptance.md rather than a line-targeted patch of only the previously-cited defects:

1. acceptance.md:L62-66 (AC-081-003) — Split into two separate bullets, or restructure as a single
   EARS sentence. The cleanest fix: keep only `"**WHEN** ..., the system **SHALL** \`score ==
   20.0\` ..."` as the sole normative sentence, and move `"신호가 없는 공시는 인위적으로
   상향되지 않는다"` into a non-bolded, non-normative parenthetical explanation (matching the
   style already used correctly elsewhere in this same document, e.g., acceptance.md:L29-31's
   parenthetical calculation note) rather than a second independent SHALL NOT clause.

2. acceptance.md:L145-148 (AC-081-009, second bullet) — Either (a) remove the trailing informal
   clause entirely, since AC-081-009's first bullet (L140-144) already fully covers the
   dual-input-equivalence behavior being described, or (b) if the clause must be retained as a
   distinct testable assertion, rewrite it as its own separate bulleted EARS sentence with a
   proper bolded trigger and SHALL/SHALL NOT (e.g., a new `"**IF** \`ai_summary\` 필드가 채워진
   상태에서 신규 키워드가 매칭되면, **THEN** the system **SHALL** 그 매칭 근거를
   \`report_name\`+\`ai_summary\` 텍스트 매칭으로만 성립시킨다"` -style Unwanted/Event-Driven
   sentence) rather than continuing the prior bolded sentence with unbolded informal modals.

3. Process recommendation (not a line-level fix): before the next resubmission, manager-spec
   should re-read acceptance.md in full, bullet by bullet, specifically checking each bullet for
   (a) exactly one bolded EARS trigger keyword (or zero, for pure Ubiquitous), and (b) exactly one
   normative SHALL/SHALL NOT clause per bullet — rather than fixing only the exact lines a prior
   audit report cited. This would have caught D1/D2 in this report before resubmission, since
   AC-081-003 and AC-081-009 both predate this iteration's edits (they were not modified by the
   v0.2.0->v0.3.0 diff per spec.md HISTORY L34-43, which only lists changes to AC-081-001/002 RED
   bullets, AC-081-002's note, AC-081-005/006, and AC-081-008/REQ-008 — AC-081-003 and AC-081-009
   were left untouched and their pre-existing compound-clause issues were never caught in any of
   the three iterations to date).

No changes are needed to REQ numbering, YAML frontmatter, REQ-to-AC traceability, the Exclusions
section, or any of the score literals (25.0, 20.0, -10.0, 5.0, >=30.0) — all independently
re-verified correct and unchanged from iteration 2's PASS findings.
