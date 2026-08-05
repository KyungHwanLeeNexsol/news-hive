# Progress — SPEC-AI-103

## §E.1 Plan-phase Audit-Ready Signal

plan_status: audit-ready
plan_complete_at: 2026-08-05
plan_audit_verdict: PASS
plan_audit_score: 0.923
plan_audit_iteration: 3
plan_audit_report: .moai/reports/plan-audit/SPEC-AI-103-review-3.md
plan_audit_tier_threshold: 0.80 (Tier M)

Plan-phase artifacts (spec.md, plan.md, acceptance.md, research.md, progress.md)
created in this session by manager-spec. SPEC ID `SPEC-AI-103` passed the
canonical regex self-check (`decomposition: SPEC ✓ | AI ✓ | 103 ✓ → PASS`) and
was confirmed unused in both `.moai/specs/` and `backend/.moai/specs/` before
write. Tier classified as M (3 files: spec.md + plan.md + acceptance.md, plus
research.md for the DDD deep-code-investigation deliverable). Ready for
plan-auditor review and Implementation Kickoff Approval.

**iteration 2 (2026-08-05)**: plan-auditor iteration 1 verdict was FAIL
(score 0.67, MP-2 blocking — see
`.moai/reports/plan-audit/SPEC-AI-103-review-1.md`). Fixed all 8 defects
(D1-D8): acceptance.md AC-001~005 rewritten as GEARS-primary statements
(GWT retained as subordinate scenario elaboration); AC-006/AC-007 added for
REQ-005/REQ-007 coverage; REQ-004 "should"→"shall" (D2); REQ-007 relabeled
Ubiquitous→State-driven with leading `While` (D8); activation-criteria note
added to spec.md §Decisions D5 (Completeness gap); yaml `enabled` value-scoped
awk+grep check replaces existence-only grep (D4); performance edge case now
states a numeric 20% threshold (D5); `dedup_max_comparison_batch` (default
200) hard cap added to spec.md D4 / plan.md §C / research.md §4-§5 (D6);
`related_specs:` renamed to `depends_on:` (D7). Re-submitted for
plan-auditor iteration 2.

**iteration 3 (2026-08-05, FINAL per Retry Loop Contract)**: plan-auditor
iteration 2 verdict re-verified D1-D8 all RESOLVED, but independent
re-verification surfaced 2 NEW defects (D9, D10) — scoped fix, nothing else
touched:
- **D9 (major)**: the D4/D9 yaml `enabled` value-assertion command used an
  awk range pattern (`/theme_freshness_guard:/,/^[a-zA-Z_]/`) with an
  off-by-one risk (range can close on the same line it opens). Replaced with
  a flag-based awk (`/theme_freshness_guard:/{flag=1; next} flag &&
  /^[a-zA-Z_]/{exit} flag`) in acceptance.md §C. Tested empirically (not just
  asserted): (a) PASS against a synthetic fixture replicating the real
  `combo_chase_guard:` block's exact indentation with `enabled: false` added,
  (b) correctly FAIL against the actual current `surge_detection.yaml` (the
  block does not exist yet — still plan-phase, no false PASS). Honest
  disclosure: since implementation has not started, "PASS on the real file"
  per the auditor's literal wording is not yet obtainable; verified via a
  structurally-faithful synthetic fixture instead, with re-verification
  against the real file deferred to implementation time.
- **D10 (major)**: reverted the D7 fix — `depends_on:` frontmatter field
  reverted back to `related_specs:` in spec.md. Rationale: 4 of the 5 listed
  SPECs would fail the Phase 1 Depends_on Pre-flight Check's strict
  `status: completed` fulfillment test (case-mismatch, `implemented` status,
  or pre-schema legacy frontmatter), which would trigger an unintended
  blocking `AskUserQuestion` at `/moai run SPEC-AI-103`. These are
  cross-reference/context SPECs, not hard run-phase blockers.

This is the final retry iteration per the Retry Loop Contract (max 3) —
no further scope changes anticipated.

## §F Phase 4 Mode Selection

**Implementation Kickoff Approval**: obtained 2026-08-05 via orchestrator AskUserQuestion
(run-phase entry selected; autonomous progression mode selected; M4/REQ-AI103-004
scope-inclusion decision resolved as "포함/include" — spec.md Open Question 2 closed).

**Plan Audit Gate**: SKIPPED per the 4-condition skip contract
(`.claude/rules/moai/workflow/spec-workflow.md` § Phase Transitions) — verdict
PASS, score 0.923 ≥ 0.90, artifact-hash unchanged since the iteration-3 verdict
(no edits after `SPEC-AI-103-review-3.md` was written), within 24h.

**Mode evaluation**:
| Mode | Selected? | Rationale |
|------|-----------|-----------|
| 1 trivial | No | Multi-milestone DDD implementation, not a single-line change |
| 2 background | No | Write-capable, needs foreground sequential milestones |
| 3 agent-team | No | RETIRED |
| 4 parallel | No | Single-domain (backend Python), coding-heavy — Anthropic coding-task caveat applies |
| 5 sub-agent | **Selected** | Coding-heavy DDD work on one primary file (`surge_detector.py`) + config/yaml + one test file; sequential milestone dependency (M1 config schema → M2/M3 helpers → M4 subfeature → M5 characterization tests → M6 wiring) |
| 6 workflow | No | Not high-volume mechanical; single uniform transform rule does not apply |

**Decision: sub-agent**

Single `manager-develop` sequential spawn, cycle_type=ddd, per Tier M Section A-E
delegation template.

## §E.2 Run-phase Evidence

**Implementation status**: M1~M6 코드/테스트 작업 완료, 검증 완료.
**Commit status**: 완료 — 사용자 승인(Option 1, stash 기반 클린 커밋)에 따라 커밋·푸시 수행.

### §E.2.1 AC PASS/FAIL Matrix

| AC | REQ | Status | Verification command | Actual output |
|----|-----|--------|----------------------|---------------|
| AC-AI103-001 | REQ-AI103-001 | **PASS** | `uv run pytest tests/test_spec_ai_103.py -k TestDedupNearDuplicateArticles -q` | 9 passed — 헬퍼 축약/대표=최이른/유사·비유사/창밖 배제/테마 활성 카운트 2(raw 3)/경계 비활성화/종목 귀속 dedup/원본 불변 |
| AC-AI103-002 | REQ-AI103-002 | **PASS** | `uv run pytest tests/test_spec_ai_103.py -k "TestDefaultByteEquivalence or TestCharacterizationPreGuard" -q` | 9 passed — 중복 포함 픽스처 기본값 결과가 §M5 특성화 스냅샷과 동일(0.15), 2단 스위치(enabled=True + 임계 0.0) 무영향 확인 |
| AC-AI103-003 | REQ-AI103-003 | **PASS** | `uv run pytest tests/test_spec_ai_103.py -k TestFreshnessDecay -q` | 4 passed — 진부 테마 baseline×0.5 감쇠 + 후보 잔존(완전 배제 아님), 분모 0 방어 1.0, fresh_window None→cluster/2 파생 |
| AC-AI103-004 | REQ-AI103-003 | **PASS** | (동일 명령, 신선 분기) | 신선 테마(전량 24h 이내) 점수가 가드 비활성 baseline과 동일 — 감쇠 미적용 |
| AC-AI103-005 | REQ-AI103-004 | **PASS** (Should-Pass) | `uv run pytest tests/test_spec_ai_103.py -k TestPriceOverheatGuard -q` | 5 passed — +20% 후보 감쇠 + `fetch_stock_price_history_batch_sync` **call_count == 1**, +5% 무감쇠, `sector_only_max_candidates=None`시 call_count == 0, 배치 실패시 무예외 열화 |
| AC-AI103-006 | REQ-AI103-005 | **PASS** (Must-Pass) | `uv run pytest tests/test_spec_ai_103.py -k TestNoPerStockSyncPriceCall -q` | 3 passed (guard-off / guard-on / guard-on+overheat-on) — 12종목 픽스처에서 `_fetch_price_change_sync` call_count == 0, `fetch_current_price_with_change_sync` call_count == 0, 배치 호출 ≤ 1 |
| AC-AI103-007 | REQ-AI103-007 | **PASS** (Must-Pass) | `uv run pytest tests/test_spec_ai_103.py -k TestObservabilityLogging -q` | 2 passed — `caplog` 자동 단언으로 `raw_articles=3` / `deduped_articles=2` / `freshness_ratio=` 동시 포함 DEBUG 레코드 확인, 가드 비활성 시 로그 미발생 |
| REQ-AI103-006 (프로세스) | — | **PARTIAL (정직 기록)** | `git log` 검증 | 특성화 테스트(`TestCharacterizationPreGuard` 7건)는 **작성·통과 확인 완료**. 다만 §E.2.3 블로커(타 SPEC 미커밋 작업 혼재)로 M5/M6가 **별도 선행 커밋으로 분리되지 못하고 단일 커밋에 포함**되었다. "구현 변경 이전 커밋" 이력 증거는 미확보이며, 사후에 커밋을 인위적으로 쪼개 이력을 만들어내는 것은 검증 무결성 위반이므로 수행하지 않았다 |

### §E.2.2 Edge cases + 하드 캡 (acceptance.md §B)

| 항목 | Status | 근거 |
|------|--------|------|
| 빈 뉴스 창 (가드 활성) | PASS | 빈 목록 반환 |
| 전량 동일 제목 | PASS | 1건 수렴 + `ZeroDivisionError` 없이 ratio=1.0 |
| 발행 시각 차 경계값(정확히 6.0h) | PASS | 포함(중복 판정), 5.99h 설정시 배제 — 양방향 확인 |
| 다중 테마 교차 오염 방지 | PASS | 두 테마 동시 매칭 기사 존재해도 반도체 부분집합 카운트 4 유지 |
| 과열 서브기능 스킵(`max_candidates=None`) | PASS | 배치 호출 0회 |
| 하드 캡 경계(200) / 초과(500) | PASS | `SequenceMatcher.ratio()` 호출 횟수 계측: 캡 초과(500)가 캡 도달(200)보다 **증가하지 않음**, 상한 `cap*(cap-1)/2` 이내. 캡 초과분 300건은 개별 집계로 열화 |

> 성능 경계 판정 방식 주석: acceptance.md §B는 "실행 시간 20% 이내 증가"를 명시한다.
> 벽시계 시간은 환경 의존적이라 1차 판정을 **결정적 비교-횟수 계측**으로 수행하고
> (캡의 구조적 유계성이 D4가 실제로 요구하는 계약이다), 벽시계 20% 기준은 보조
> 지표로 함께 단언했다(`test_over_cap_wallclock_does_not_exceed_at_cap`). 두 지표 모두 PASS.

### §E.2.3 커밋 블로커 및 해소 경위 (RESOLVED)

`backend/app/services/surge_detector.py`(본 SPEC의 주 EXTEND 대상)에 **본 SPEC과
무관한 SPEC-AI-102 run-phase 작업이 미커밋 상태로 존재**한다(75 insertions / 3
deletions, `build_scan_universe()` → `_source_scan_universe_pools()` +
`_assemble_scan_universe()` 추출 리팩터, `@MX:SPEC: SPEC-AI-102 REQ-AI102-001`
태그로 확인). `git log`에 SPEC-AI-102 커밋 없음 — 진행 중인 작업이다.

- 파일 단위 스테이징은 SPEC-AI-102의 미완 작업을 SPEC-AI-103 커밋에 **불가피하게
  포함**시킨다(B10 스코프 규율 / L46 귀속 위반).
- 해당 미커밋 변경은 `test_spec_ai_065.py::test_min_ratio_literal_unchanged_in_source`
  **1건을 실패**시키고 있다(baseline에서 이미 실패, 본 SPEC 무관 — §E.3 참조).
- 부분 스테이징(내 hunk만 커밋)은 기계적으로 가능하나(두 변경군이 약 4,500라인
  떨어져 완전 분리), **테스트된 적 없는 트리 상태**를 커밋하게 된다.

**해소(사용자 승인 Option 1 — stash 기반 클린 커밋)**:

1. `surge_detector.py` 통합 diff(14 hunk)를 hunk old-start 기준으로 분리했다 —
   SPEC-AI-103 10개(old-start 6~535) vs SPEC-AI-102 4개(old-start 5030~5248),
   두 군 사이 약 4,500라인 간극으로 경계가 모호하지 않다. 분리 결과 교차 오염
   0건 검증(`sd_mine.patch`의 SPEC-AI-102 참조 0건, `sd_102.patch`의 SPEC-AI-103
   참조 0건).
2. SPEC-AI-102 hunk + `surge_prediction_evaluation.py` 전체 변경을 단일 패치로
   묶어 `git apply -R`로 워킹트리에서 제거(`--check` 사전 통과).
3. 클린 트리에서 전체 회귀 재실행 → **2387 passed, 0 failed**.
   `test_spec_ai_065.py::test_min_ratio_literal_unchanged_in_source`가 **통과로
   전환**되어, 해당 실패가 SPEC-AI-102의 미완 추출 리팩터 기인이며 본 SPEC과
   무관함이 실증되었다.
4. SPEC-AI-103 파일만 스테이징하여 커밋·푸시, 이후 보관 패치를 재적용해
   SPEC-AI-102 작업을 원상 복원(sha256 대조로 바이트 동일 확인 — §E.3
   `stash_restore_verified`).

`git stash push --patch`는 TTY가 필요한 대화형 명령이라 이 환경에서 사용할 수
없어, 사용자가 허용한 대안("hand-splitting a patch file at the hunk boundary")인
패치 분리 + `git apply -R` / `git apply` 방식을 사용했다. 복원 정확성은 stash보다
강한 기준(패치 파일 sha256 사전/사후 대조)으로 검증했다.

## §E.3 Run-phase Audit-Ready Signal

```yaml
run_complete_at: 2026-08-05
run_commit_sha: 02098cb5d927937d0b364176898994ba082c8472
run_push_result: "ddf1f0f..02098cb  main -> main (origin/main 반영 확인)"
run_status: implemented
ac_pass_count: 7          # AC-AI103-001 ~ AC-AI103-007 전부 PASS
ac_fail_count: 0
ac_partial_count: 1       # REQ-AI103-006 프로세스 게이트 — 선행 커밋 분리 미달(정직 기록)
preserve_list_post_run_count: 0   # plan.md §G PRESERVE 대상에 본 SPEC 기인 diff 0
l44_pre_commit_fetch: done        # git fetch origin main → 0 0 (동기)
l44_post_push_fetch: done         # push 후 origin/main == HEAD 확인
new_warnings_or_lints_introduced: 0   # ruff clean (전체 backend)
cross_platform_build:
  applicable: false       # Python 백엔드 — Go 빌드 태그 해당 없음
  import_sanity: pass     # `from app.main import app` OK
  type_check: not-run     # mypy 미설치 (pyproject.toml 미선언) — 환경 갭, §E.3 note
total_run_phase_files: 4
  # backend/app/surge_config/surge_settings.py       (신규 config 클래스 + 등록)
  # backend/app/surge_config/surge_detection.yaml    (신규 theme_freshness_guard 블록)
  # backend/app/services/surge_detector.py           (헬퍼 4개 + detect_theme_news_cluster 배선)
  # backend/tests/test_spec_ai_103.py                (신규, 39 tests)
m1_to_mN_commit_strategy: single-commit
  # 계획은 M1+M5 → M2/M3 → M4 3커밋이었으나, §E.2.3 블로커로 3커밋 순차 실행 시점을
  # 놓쳤다. 사후에 커밋을 인위적으로 쪼개 "특성화 선행" 이력을 만들어내는 것은 검증
  # 무결성 위반이므로, 실제 작업 순서를 그대로 반영하는 단일 커밋으로 확정했다.
coverage_new_modified_region: 92.4%   # 207/224 statements, 신규 헬퍼 4개 전부 100%
new_tests_added: 39                   # backend/tests/test_spec_ai_103.py
regression_baseline:      "1 failed, 2347 passed, 4 skipped, 3 xpassed (-m 'not slow', 구현 전, SPEC-AI-102 혼재 트리)"
regression_mixed_serial:  "1 failed, 2386 passed, 4 skipped, 3 xpassed (serial, 275s, SPEC-AI-102 혼재 트리)"
regression_mixed_xdist4:  "1 failed, 2386 passed, 4 skipped, 3 xpassed (-n 4, 167s, SPEC-AI-102 혼재 트리)"
regression_clean_final:   "2387 passed, 4 skipped, 3 xpassed, 0 failed (serial, 253s, SPEC-AI-102 제거 후 클린 트리)"
regression_delta: >-
  혼재 트리에서 serial/xdist -n 4 결과가 완전히 동일했고, 유일한 실패는 baseline에도
  있던 test_spec_ai_065.py::test_min_ratio_literal_unchanged_in_source 1건이었다.
  SPEC-AI-102 hunk를 제거한 클린 트리에서 이 테스트가 통과로 전환되어(0 failed),
  해당 실패가 SPEC-AI-102의 build_scan_universe() 추출 리팩터(`_min_ratio = 2.0`이
  inspect.getsource() 슬라이스 밖으로 이동) 기인이며 본 SPEC과 무관함이 실증되었다.
  본 SPEC 기인 신규 실패 0건.
preserve_verification: >-
  plan.md §G PRESERVE 심볼 9종(compute_ensemble_score, _comention_supplement,
  _derive_comention_theme_candidates, detect_theme_group_carry_forward,
  detect_theme_news_carry, ComboChaseGuardConfig, ThemeClusterConfig,
  EnsembleConfig, _keyword_in_text)을 HEAD 원본과 본문 대조 — 전부 동일.
  ComboChaseGuardConfig는 신규 클래스의 @MX 헤더 주석이 인접해 슬라이서상
  차이로 보이나, 필드/로직 라인은 HEAD와 완전 동일함을 별도 확인했다.
flaky_check: "test_spec_ai_103.py 3회 반복 실행 전부 동일 통과 (시각 의존 경계 테스트 결정화 수정 후)"
stash_restore_verified: >-
  PASS — 커밋 직전 상태(ddf1f0f)에 세션 시작 시점의 원본 통합 패치를 독립 재적용해
  복원 기대본을 재구성한 뒤, 현재 워킹트리와 sha256 대조했다.
  surge_detector.py = 47b2c9d2…1f30, surge_prediction_evaluation.py = 616c9553…cb45
  양쪽 모두 일치(LF 정규화 기준 — `core.autocrlf=true` 환경이라 워킹트리는 CRLF,
  git blob은 LF이므로 정규화 후 비교가 정확한 대조다).
  `git status` 델타도 SPEC-AI-103 항목 4건이 커밋되어 사라진 것뿐이고 신규 항목은 0건.
  기능적 충실성도 확인: 복원 후 test_spec_ai_065::test_min_ratio_literal_unchanged_in_source가
  다시 실패(SPEC-AI-102 변경이 복귀했다는 증거)하고, 본 SPEC 39건은 그대로 통과한다.
  SPEC-AI-102 작업은 미커밋 상태 그대로 보존되며 본 세션은 이를 수정/해결하지 않았다.
```

**Note (mypy)**: acceptance.md §C는 `uv run mypy app/`을 품질 게이트로 명시하나,
이 환경에 mypy가 설치되어 있지 않고 `pyproject.toml`에도 선언되어 있지 않다
(`error: Failed to spawn: mypy — program not found`). 검증 미수행 갭으로 명시 기록한다.

## §E.4 Sync-phase Audit-Ready Signal

_<pending sync-phase>_
