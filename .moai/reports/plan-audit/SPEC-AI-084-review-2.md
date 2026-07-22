# SPEC Review Report: SPEC-AI-084
Iteration: 2/3
Verdict: FAIL
Overall Score: 0.92 (category harmonic mean; verdict forced to FAIL by M5 Must-Pass Firewall regardless of this number)

Reasoning context ignored per M1 Context Isolation. This audit is based solely on the current
`.moai/specs/SPEC-AI-084/spec.md` (v0.2.0), `.moai/specs/SPEC-AI-084/plan.md`, and
`.moai/specs/SPEC-AI-084/acceptance.md`, cross-checked against my own
`.moai/reports/plan-audit/SPEC-AI-084-review-1.md` strictly for the mandatory iteration-2+
regression check, and against this project's own binding precedent
`.moai/reports/plan-audit/SPEC-AI-081-review-3.md` for the exact MP-2 defect-class definition. The
invocation prompt's claim that "manager-spec has since revised all three files... claiming to fix
both, plus a minor D2 fix" was treated as an unverified assertion, not a conclusion — every one of
the 17 AC blocks in acceptance.md was independently re-read end-to-end for EARS conformance
(trigger-keyword count, SHALL/SHALL-NOT-keyword-to-predicate-polarity match), not just the specific
lines the HISTORY entry claims were fixed.

## Pre-Read Failure-Mode Checklist (M2 adversarial stance, re-run for iteration 2)

1. REQ numbers gaps/duplicates — re-checked end-to-end, see MP-1.
2. AC informal language / GWT-mislabeled-as-EARS / mixed informal-formal within one criterion —
   re-checked end-to-end, see MP-2 (this iteration's primary finding — a NEW, isolated instance of
   the defect class iteration 1 found systemically).
3. YAML frontmatter — re-checked, see MP-3.
4. Requirements containing HOW not WHAT/WHY — re-checked, see RQ-3/RQ-4 note below.
5. Broken traceability — re-checked end-to-end, see Traceability.
6. Hardcoded language-specific tool names — N/A, unchanged, see MP-4.
7. Vague/absent Exclusions — re-checked, unchanged from iteration 1, still specific.
8. Contradictory requirements — re-checked, none found, including the new REQ-013 text.
9. Regression against iteration-1 defects (D1-D4) — see Regression Check below.

## Must-Pass Results

- **[PASS] MP-1 REQ number consistency**: spec.md — `#### REQ-AI084-001` through
  `#### REQ-AI084-018` (L201, 211, 219, 227, 235, 245, 253, 261, 268, 278, 286, 296, 304, 324, 329,
  337, 343, 355). Sequential 001→018, zero-padded 3-digit, no gaps, no duplicates. Re-verified via a
  fresh, full end-to-end grep of every `#### REQ-AI084-` heading (not spot-checked). Unchanged from
  iteration 1 — the v0.2.0 revision did not touch REQ numbering.

- **[FAIL] MP-2 EARS format compliance**: The systemic iteration-1 defect (100% Given-When-Then
  prose, zero bolded EARS SHALL sentences) is genuinely and substantially resolved — every one of
  the 17 AC blocks now carries at least one bolded EARS sentence (`**WHEN**/**WHILE**/**IF**` +
  `the system **SHALL**/**SHALL NOT**`), with the prior GWT triplets correctly demoted to an
  explicitly-labeled non-normative `_재현 시나리오(비규범)_` illustration (acceptance.md:L9-11 states
  this demotion explicitly). A full end-to-end re-scan of all 29 individual EARS sentences across
  the 17 ACs (not sampled) found 28 that are cleanly single-trigger + single-SHALL/SHALL-NOT-clause,
  with the bolded keyword's polarity matching the sentence's final governing predicate. However, one
  NEW, previously-unflagged instance of the exact defect class this project's own precedent treats
  as an MP-2 FAIL was found:
  - **acceptance.md:L48 (AC-084-004)** — `"**IF** 키워드 추출이 LLM 경로를 포함하는 구성에서 배치
    백필이 실행되면, **THEN** the system **SHALL** 무료 티어·규칙/사전 추출을 우선하고 예산 상한
    도달 시 규칙 폴백으로 전환하여 무유계 LLM 호출로 예산을 폭발시키지 않아야 한다."` The sentence
    opens with a bolded **SHALL** governing the enabling/positive actions ("우선하고", "전환하여"),
    but its actual final governing predicate — the binding constraint this AC exists to enforce — is
    a negative, unbolded, informal-register Korean modal (`"폭발시키지 않아야 한다"` = "shall not [let
    the budget] explode"). The bolded keyword's polarity (SHALL, positive) does not match the
    sentence's real normative payload (a prohibition). Contrast with the same document's own
    correctly-formed pattern used everywhere else for a prohibition (e.g. L38 `"**SHALL NOT** ...
    덮어써서는 안 된다"`, L58 `"**SHALL NOT** ... 증식시켜서는 안 된다"`, L87 `"**SHALL NOT** ...
    상향해서는 안 된다"` — in every one of those, the bolded SHALL NOT keyword's polarity matches the
    trailing `"...안 된다"`/`"...않아야 한다"` predicate). AC-084-004 is the only one of the 17 ACs
    where this mismatch occurs — verified by re-reading the governing predicate of all 29 EARS
    sentences individually (acceptance.md:L17,28,29,38,39,48,57,58,69,78,87,96,97,108,109,118,119,
    128,137,138,149,150,151,160,161,170,171,180,181).
  - **Direct, binding project precedent**: `.moai/reports/plan-audit/SPEC-AI-081-review-3.md`
    L21-47 ruled this exact defect class — "an AC bullet ... mixing a bolded EARS clause with an
    unbolded informal modal clause" — a direct MP-2 FAIL, explicitly even when the instance was
    newly-introduced and isolated (2 new instances, not systemic, after the prior systemic defect
    had already been fixed): `"Per HARD RULE 'when in doubt, FAIL,' this is marked FAIL."` This is
    the same project, the same evaluation criterion, and the same defect shape.
  - **acceptance.md's own header (L6-8) explicitly names this exact prohibited pattern** — the
    document's own convention note states criteria must avoid "복합 2-절 문장·em-dash 결합 2차
    정규 절·볼드 SHALL과 비형식 한국어 모달 혼용" (compound two-clause sentences / em-dash-joined
    secondary normative clauses / mixing bold SHALL with an informal Korean modal), citing
    SPEC-AI-081-review-3.md's D1/D2 lesson by name. AC-084-004 is a live instance of the third
    named anti-pattern in the SPEC's own list.
  - **Cross-check against REQ-AI084-004 (spec.md:L227-231)**: the governing REQ for this AC is
    correctly formed — `"the system **SHALL NOT** (a) ... 덮어쓰거나 오염시켜서는 안 되며, (b) ...
    폭발시켜서는 안 된다"` — a single bolded SHALL NOT governing two enumerated items, both ending
    in a matching negative predicate. The mismatch was introduced specifically in the AC's
    restatement of the REQ, not present in the REQ itself.
  - Per MP-2's own literal text (identical wording to iteration 1's citation and to the
    SPEC-AI-081-review-3.md precedent) — "mixed informal/formal within a single criterion = FAIL" —
    this is a direct match. Severity: **major** (this is a materially and substantially smaller-scope
    finding than iteration 1's systemic 17/17 GWT-only failure — it is now isolated to 1 of 17 ACs —
    but per M5 Must-Pass Firewall, any single MP-2 violation forces overall FAIL regardless of scope
    reduction).

- **[PASS] MP-3 YAML frontmatter validity**: spec.md:L1-13 — `id: SPEC-AI-084` (string), `version:
  0.2.0` (string, correctly bumped from 0.1.0), `status: draft` (string), `created: 2026-07-22` +
  `created_at: "2026-07-22"` (both present now), `updated: 2026-07-22` (new), `author: Nexsol` (new),
  `priority: High` (string), `issue_number: null`, `lifecycle_level: 1`, `labels: [...]` (array). All
  six fields from this project's established plan-audit convention (id/version/status/
  created_at/priority/labels — per SPEC-AI-081-review-3.md's identical six-field evaluation) are
  present with correct types. **Unchanged non-blocking flag carried from iteration 1 (D3)**: the
  document still does not conform to the stricter 12-field `spec-frontmatter-schema.md` SSOT
  (missing `title`/`phase`/`module`/`lifecycle`; uses `created_at`/`labels` which that schema
  rejects in favor of `created`/`tags`) — though the v0.2.0 revision did add `created`/`updated`/
  `author`, narrowing (not closing) the gap versus the 12-field schema. Does not change the MP-3
  verdict under this project's applied six-field convention.

- **[N/A] MP-4 Section 22 language neutrality**: N/A — unchanged, single-language (Python/FastAPI
  backend) detector/scoring SPEC.

## Category Scores (0.0-1.0, rubric-anchored)

| Dimension | Score | Rubric Band | Evidence |
|-----------|-------|-------------|----------|
| Clarity | 0.80 | 0.75-1.0 band boundary ("minor ambiguity ... a reasonable engineer would resolve consistently") | REQ-AI084-013's firm-vs-deferred split is now explicit and unambiguous (spec.md:L312-318: the `surge_metadata["horizon"]="same_day"` field/value contract is stated as "확정 통과 기준... 열린 질문이 아니다"; only the *trigger threshold* — which candidates get tagged — remains deferred to OQ-5/DP-5). This closes the ambiguity iteration 1 flagged as Defect D1. Residual, legitimate plan-phase deferrals remain (OQ-2 basket granularity, OQ-3 theme-confirmation threshold for REQ-011) but these are numeric-threshold deferrals, not decision-rule gaps, and are explicitly scoped to Run/annotation. |
| Completeness | 1.0 | 1.0 band (all required sections + frontmatter present, ≥1 exclusion entry) | HISTORY spec.md:L17-53 (now documents the v0.2.0 revision rationale against the iteration-1 report explicitly); WHY/Overview spec.md:L56-120; Environment/Assumptions spec.md:L122-190; REQUIREMENTS spec.md:L193-359 (18 REQs, 4 groups); ACCEPTANCE CRITERIA acceptance.md (17 ACs + 7 edge cases + quality gates + DoD); Exclusions spec.md:L363-386 ([X-1]..[X-8], unchanged from iteration 1, still specific). |
| Testability | 0.90 | 0.75-1.0 band ("one AC not precisely binary-testable but measurable with minor interpretation") | The structural GWT-only defect and both substance gaps from iteration 1 (AC-084-013 same-day field/value contract; AC-084-016 first-mover exclusion mechanism) are resolved with named, concrete mechanical tests: AC-084-013 names a DB assertion on `surge_metadata->>'horizon' == 'same_day'` (acceptance.md:L140); AC-084-016 names `test_first_mover_excluded_from_theme_news_carry_scope` consistently across REQ-017 (spec.md:L349-353), AC-084-016 (acceptance.md:L171), Quality Gates (acceptance.md:L206), and DoD (acceptance.md:L214) — not a one-off narration. AC-084-004 (LLM budget guard) remains substantively measurable (three observable behaviors: free-tier/rule priority, fallback at budget cap, no unbounded-LLM-call cost explosion) despite its MP-2 formatting defect — the testability gap here is cosmetic/format, not a genuine judgment-call ambiguity. No weasel words found via full-text grep of both files (적절/합리적/충분히/reasonable/appropriate/adequate — zero matches). |
| Traceability | 1.0 | 1.0 band (every REQ has ≥1 AC, every AC references a valid REQ, no orphans) | Re-verified end-to-end: all 18 REQ-AI084-0NN entries have ≥1 corresponding AC (001→AC001, 002→AC002, 003→AC005, 004→AC003/AC004, 005→AC006, 006→AC007, 007→AC008, 008→AC009, 009→AC010, 010→AC010, 011→AC011, 012→AC012, 013→AC013, 014→AC014, 015→AC014/AC015, 016→AC014, 017→AC016, 018→AC009/AC017). Every AC-084-0NN heading cites an existing REQ-AI084-0NN. No orphans either direction. Unchanged from iteration 1 (the v0.2.0 revision did not alter the REQ/AC set, only their internal phrasing). |

## Verification Item 1 (re-verified per invocation) — is REQ-AI084-013/AC-084-013 now firm and testable, with the trigger threshold clearly scoped as the only open item?

**Finding: YES — fully resolved, cleanly separated.** spec.md:L312-318 states explicitly: *"이 필드/값
계약은 Run 착수 시점에 필드 수준 PASS/FAIL 테스트(전파 fund_signals 행의 surge_metadata.horizon DB
어서션, AC-084-013)를 갖는 확정 통과 기준이다. 단 어떤 전파 후보에 same_day를 부여할지의 트리거 임계
(전량 vs 특정 조건)만 OQ-5/DP-5에 위임한다 — 트리거 임계는 열린 질문이나, 필드/값 계약 자체는 열린
질문이 아니다."* This is an unambiguous firm/deferred split: the field/value contract
(`surge_metadata["horizon"] = "same_day"`) is a firm, testable requirement; only the triggering
condition (which candidates receive the tag) is deferred. acceptance.md:L137-140 mirrors this exactly
and names the concrete DB assertion (`surge_metadata->>'horizon' == 'same_day'`). plan.md:L81-83
independently confirms the same split with no drift across the three documents. This closes iteration
1's Defect D1 (major) completely.

## Verification Item 2 (re-verified per invocation) — are the named mechanical test artifacts real and concrete, not merely narrated?

**Finding: YES.** `test_first_mover_excluded_from_theme_news_carry_scope` is named consistently in
four places (spec.md:L51, L350; acceptance.md:L171, L175, L206, L214) with a concrete mechanism
described each time (exclusion from `predicted_set`/`actual_set` membership, mirroring the existing
`excluded_near_limit_up_carry_codes`/`excluded_same_day_event_codes` pattern with an exact file:line
citation, `surge_evaluation_service.py:602-607`). The `surge_metadata->>'horizon' == 'same_day'` DB
assertion (AC-084-013) is similarly named with a concrete JSON-path expression and an exact
governing-function citation (`surge_evaluation_service.py:506-524`). Both artifacts are consistently
named across every reference (not a single mention followed by drift), closing iteration 1's Defect
D2 (minor) completely.

## Chain-of-Verification Pass

Second-look findings — one new defect surfaced on re-scan (documented under MP-2 above); confirmed
by re-reading:
1. Every one of the 18 REQ-AI084-0NN entries in spec.md end-to-end for numbering/sequencing — no
   gaps, no duplicates, unchanged from iteration 1.
2. Every one of the 17 AC-084-0NN headings and all 29 individual bolded EARS sentences in
   acceptance.md, checking specifically for (a) exactly one trigger keyword, (b) exactly one bolded
   SHALL/SHALL-NOT keyword, and (c) polarity match between the bolded keyword and the sentence's
   final governing predicate — this third check (not performed as granularly in iteration 1, since
   iteration 1's finding was the wholesale absence of any bolded EARS sentence) is what surfaced the
   AC-084-004 defect. This is exactly the kind of second-pass discovery M6 exists to catch.
3. Every REQ-to-AC traceability link re-checked individually — no orphans, no regression.
4. The Exclusions section (spec.md:L363-386) re-read for specificity — unchanged, still specific,
   no vague placeholders.
5. Checked for new contradictions introduced by the v0.2.0 diff specifically (REQ-013's expanded
   text, REQ-017's new named-test sub-bullet) against all other REQs, Exclusions, and Related SPECs
   sections — none found; REQ-013's field/value contract is consistent with [X-4] (no new
   migration, reuses existing `surge_metadata` JSON field).
6. Frontmatter re-read in full against both the project's six-field convention (PASS, unchanged)
   and the stricter 12-field SSOT (still fails that stricter schema, unchanged non-blocking D3).
7. Re-confirmed via full-text grep that no weasel words (적절/합리적/충분히/reasonable/appropriate/
   adequate/정상적으로/제대로/알맞/타당한/충분한/적정) appear anywhere in acceptance.md.

## Regression Check (Iteration 2)

Defects from previous iteration (`.moai/reports/plan-audit/SPEC-AI-084-review-1.md`):

- **D1** (major — REQ-013/AC-084-013 same-day field/value contract never named, trigger rule and
  field contract both left open) — **RESOLVED**: spec.md:L312-318 and acceptance.md:L137-140 now
  name `surge_metadata["horizon"] = "same_day"` as a firm, testable contract with a concrete DB
  assertion, explicitly separating it from the still-open trigger-threshold question (OQ-5/DP-5).
- **D2** (minor — AC-084-016 first-mover exclusion had no named mechanical test artifact) —
  **RESOLVED**: `test_first_mover_excluded_from_theme_news_carry_scope` is now named consistently
  across REQ-017, AC-084-016, Quality Gates, and DoD, with a concrete exclusion mechanism and
  file:line precedent citation.
- **D3** (minor, informational — frontmatter drift vs the 12-field `spec-frontmatter-schema.md`
  SSOT) — **UNRESOLVED but non-blocking, unchanged from iteration 1**: the v0.2.0 revision added
  `created`/`updated`/`author` fields (narrowing the gap) but still lacks `title`/`phase`/`module`/
  `lifecycle` and still uses `created_at`/`labels` rather than `created`/`tags`. This does not
  block the MP-3 verdict under this project's applied six-field convention, matching iteration 1's
  treatment. Not required to be fixed for this SPEC specifically (project-wide reconciliation item).
- **D4** (critical — 100% of acceptance.md was Given-When-Then prose with zero EARS-pattern bolded
  sentences) — **LARGELY RESOLVED, with one NEW isolated recurrence of the same underlying defect
  class**: 16 of 17 ACs are now cleanly EARS-formatted with correctly-polarity-matched bolded
  SHALL/SHALL NOT sentences and the GWT triplets correctly demoted to explicitly non-normative
  illustration. However, AC-084-004 (acceptance.md:L48) introduces a new instance of the "bolded
  SHALL mixed with unbolded informal modal" defect subclass that this project's own precedent
  (SPEC-AI-081-review-3.md) treats as an MP-2-blocking FAIL even in isolated form. This is a
  **stagnation-adjacent but not stagnant** finding — it is not the same specific defect recurring
  unchanged (the systemic GWT-only problem is genuinely fixed), but it is the same *underlying
  defect category* (bold/informal-modal mixing) surfacing in a new location, which is exactly the
  failure mode SPEC-AI-081's iteration 3 also encountered after its iteration 2 "fix." This is
  flagged, not treated as blocking stagnation, since the specific instance (AC-084-004) is new, not
  a repeat of D4's original citations.

No blocking defect has appeared unchanged in both iterations 1 and 2 (D1-D3 are resolved or
non-blocking-carried-over; D4 is substantially fixed with one new, narrower-scope recurrence) — this
does NOT meet the "blocking defect — manager-spec made no progress" stagnation-flag threshold.
Genuine, substantial progress was made this iteration.

## Defects Found

D5 (new this iteration). acceptance.md:L48 (AC-084-004) — Mixes a bolded **SHALL** (governing the
   positive/enabling actions "우선하고"/"전환하여") with an unbolded, informal-register Korean
   negative modal ("폭발시키지 않아야 한다") that expresses the AC's actual binding prohibition. The
   bolded keyword's polarity does not match the sentence's real governing predicate. This is the
   exact defect class this project's own precedent (SPEC-AI-081-review-3.md L21-47) ruled an MP-2
   FAIL even as an isolated new instance, and is explicitly named as prohibited in this very
   document's own header (acceptance.md:L6-8, "볼드 SHALL과 비형식 한국어 모달 혼용을 금지한다").
   Fix is mechanical: split into two EARS sentences (one **SHALL** for the priority/fallback
   behavior, one **SHALL NOT** for the budget-explosion prohibition), mirroring the pattern this
   same document already uses correctly in AC-084-002, AC-084-003, AC-084-005, AC-084-010,
   AC-084-011, AC-084-013, AC-084-014, AC-084-015, AC-084-016, AC-084-017. — Severity: major
   (isolated to 1 of 17 ACs — a large reduction in scope from iteration 1's systemic 17/17 failure —
   but per M5 Must-Pass Firewall, blocks the overall verdict regardless of scope).

D3 (carried over from iteration 1, informational, non-blocking). spec.md:L1-13 (YAML frontmatter) —
   Still missing `title`/`phase`/`module`/`lifecycle` and still uses `created_at`/`labels` rather
   than the canonical `created`/`tags` per the project's 12-field `spec-frontmatter-schema.md` SSOT.
   Narrowed (not closed) by the v0.2.0 revision's addition of `created`/`updated`/`author`. Does not
   change the MP-3 verdict under this project's applied six-field convention. — Severity: minor,
   informational, out-of-scope-for-this-SPEC-specifically (project-wide reconciliation item).

## Recommendation

FAIL — this is iteration 2 of a maximum 3. Fix instructions for manager-spec before resubmission:

1. **acceptance.md:L48 (AC-084-004) — the single blocking fix for MP-2.** Split the sentence into
   two separate EARS sentences, matching the pattern already used correctly elsewhere in this same
   document:
   - Sentence 1 (positive, unchanged polarity): `"**IF** 키워드 추출이 LLM 경로를 포함하는 구성에서
     배치 백필이 실행되면, **THEN** the system **SHALL** 무료 티어·규칙/사전 추출을 우선하고, 예산
     상한 도달 시 규칙 폴백으로 전환해야 한다."`
   - Sentence 2 (the actual prohibition, now correctly bolded as SHALL NOT): `"**WHILE** 배치
     백필이 LLM 경로를 포함하는 구성에서 실행되는 동안, the system **SHALL NOT** 무유계 LLM
     호출로 예산을 폭발시켜서는 안 된다."`
   This is a mechanical, surgical fix — no substance change, only a format split, consistent with
   how AC-084-002/003/005/010/011/013/014/015/016/017 already correctly separate positive and
   negative behavior into distinct EARS sentences within the same AC block.
2. (Non-blocking, carried over, project-wide) Consider reconciling the six-field plan-audit
   frontmatter convention against the 12-field `spec-frontmatter-schema.md` SSOT — not required for
   this SPEC's PASS but flagged again since iteration 1.

No changes needed to REQ numbering (MP-1 PASS), Completeness (all sections present, 1.0), or
REQ↔AC traceability (1.0) — all independently re-verified correct in this iteration. Both
substance-level findings from iteration 1 (D1 same-day field/value contract, D2 first-mover named
test) are genuinely and fully resolved — do not re-touch REQ-AI084-013, AC-084-013, REQ-AI084-017,
or AC-084-016 in the next revision; they are correct as written.
