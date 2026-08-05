# SPEC-AI-102 Progress

## §E.1 Plan-phase Audit-Ready Signal

plan_status: audit-ready
plan_complete_at: 2026-08-05
plan_audit_verdict: PASS
plan_audit_score: 0.90
plan_audit_iteration: 3
plan_audit_report: .moai/reports/plan-audit/SPEC-AI-102-review-3.md
plan_audit_tier_threshold: 0.80 (Tier M)

Note: prior audit history (review-1 FAIL, review-2 PASS 0.95) existed on disk from
an earlier session but was never backfilled into this file — recorded retroactively.
Iteration 3 (this session) found new minor/major defects (D5/D6/D7) not caught by
iterations 1-2, netting 0.90. See the review-3 report for the full defect list;
D6 (Non-Goals wording internally inconsistent re: Goal 4/REQ-102-004 touching the
Pool B fetch mechanism) is carried into the run-phase delegation as an explicit
clarification rather than triggering a 4th audit iteration (verdict already PASS).

## §F Phase 4 Mode Selection

**Implementation Kickoff Approval**: obtained 2026-08-05 via orchestrator AskUserQuestion.
Existing uncommitted partial work in `surge_detector.py` (matching REQ-AI102-001,
+78/-7, tagged `@MX:SPEC: SPEC-AI-102 REQ-AI102-001`, presumed WIP from an earlier
interrupted session — never committed) is to be inspected by manager-develop and
reused or superseded at its discretion, per user decision.

**Mode**: sub-agent (Mode 5) — coding-heavy DDD work, sequential milestone
dependency (TASK-001 empirical measurement gates the Option A/B decision for
TASK-004; TASK-002/003/005 are otherwise independent refactors sharing one file).
Single `manager-develop` spawn, cycle_type=ddd.

**Staged delegation**: TASK-001 (measurement, no code change) runs first and
returns to the orchestrator for the Option A/B numeric decision (per plan.md §A
item 1's own design — this decision is deliberately deferred to Kickoff-Approval-
adjacent user confirmation, not delegated blind). TASK-002 through TASK-007 are
delegated in a second round after that decision.

## §E.2 Run-phase Evidence

### AC 매트릭스

| AC | 대응 REQ | Status | 검증 명령 | Actual Output |
|----|---------|--------|-----------|---------------|
| AC-102-001 | REQ-AI102-003 | PASS | 코드 리뷰 — plan.md TASK-001 하위 "실측 결과" 절 + M1 커밋 메시지 | Option B(50 유지) 채택 + N=50/80/100/150 × 1/2/12코어 실측표 기재 |
| AC-102-002 | REQ-AI102-001 | PASS | `pytest tests/test_spec_ai_102.py -k standalone_sourcing` | `TestPoolSourcingSplit::test_standalone_sourcing_matches_full_call PASSED` |
| AC-102-003 | REQ-AI102-001 | PASS | `pytest tests/test_spec_ai_094.py tests/test_spec_ai_096.py` + 시그니처 검사 | 기존 테스트 무수정 통과; `inspect.signature` = `(db, config, existing_codes, now)` 불변 |
| AC-102-004 | REQ-AI102-002 | PASS | `pytest -k sub_flag_off_is_byte_equivalent` (마스터 True/False 2조합) | 2 PASSED — 배치 함수 `assert_not_called()`, pool_b 후보 0 |
| AC-102-005 | REQ-AI102-002 | PASS | `pytest -k sub_flag_on_scores_pool_b_via_batch` | PASSED — 배치 1회 호출, 대상 3종목 전부 bridge 후보 편입 |
| AC-102-006 | REQ-AI102-002 | PASS | `pytest -k "pool_b_limit_is_respected or legacy_config_without_pool_b_key"` | 2 PASSED — 상한 2에 후보 10 주입 시 조회 ≤2; 키 부재 시 `_BRIDGE_POOL_B_DEFAULT_LIMIT`(5) 폴백 |
| AC-102-007 | REQ-AI102-004 | PASS | `pytest -k batch_result_matches_sequential_decision_rule` | PASSED — 짝수 통과/홀수 탈락 fixture로 `pool_b` 판정 집합 완전 일치(diff 0) |
| AC-102-008 | REQ-AI102-004 | PASS | `pytest -k partial_fetch_failure_is_isolated` | PASSED — 20종목 중 2종목 예외 주입, 나머지 18종목 정상 판정, 예외 미전파 |
| AC-102-009 | REQ-AI102-004 | PASS | 코드 리뷰 — plan.md TASK-006 하위 "검토 결과" 절 | 7개 지점 전부 전환/미전환 + 근거 기재(spec.md 표가 누락한 별칭 지점 포함) |
| AC-102-010 | REQ-AI102-005 | PASS | `git diff --name-only \| grep -E 'surge_trading_service\.py'` | 0 matches; `naver_finance.py`도 0 matches; 8개 탐지기 스코어링·`compute_ensemble_score()` 무변경 |

### 불변식 검증

| 불변식 | Status | 근거 |
|--------|--------|------|
| PRESERVE 목록(plan.md §A.2) 8항목 무변경 | PASS | `surge_trading_service.py`/`naver_finance.py` diff 0; Pool A/B/C/D 소싱 쿼리·quota 산술은 `_source_scan_universe_pools`/`_assemble_scan_universe`로 **이관만** 수행(로직 무변경); `_apply_price_fetch_truncation` 면제 로직·상한값 모두 무변경(Option B) |
| 신규 플래그 기본 OFF 무회귀 | PASS | `scan_universe_bridge_pool_b_enabled: bool = False`; AC-102-004가 마스터 스위치 True/False 양쪽에서 검증 |
| 전체 회귀 무손실 | PASS | `2402 passed, 4 skipped, 3 xpassed, 0 failed` (baseline: 2386 passed + 1 failed) |

### 의도된 테스트 불변식 갱신 (사용자 결정)

`tests/test_spec_ai_065.py::TestInvariantConstantLiteralsUnchanged` —
`test_min_ratio_literal_unchanged_in_source` → `test_min_ratio_literal_unchanged_in_pool_sourcing`.
TASK-002 함수 분리로 `_min_ratio = 2.0` 리터럴이 `build_scan_universe()`에서
`_source_scan_universe_pools()`로 이동했으므로 `inspect` 대상만 이동시켰다. 지켜야 할
불변식(값 2.0 불변)은 그대로이며, 같은 클래스의
`test_max_scan_universe_default_updated_by_spec_ai_096`(SPEC-AI-096이 SPEC-AI-065
불변식을 명시적으로 슈퍼시드한 선례)과 동일한 패턴의 **의도된 갱신**이다. 추가로
wrapper가 두 내부 함수를 순서대로 호출하는 얇은 껍데기임을 검증하는 어서션을 보강했다.

## §E.3 Run-phase Audit-Ready Signal

run_complete_at: 2026-08-05
run_commit_sha: 21d563e
run_status: implemented
ac_pass_count: 10
ac_fail_count: 0
preserve_list_post_run_count: 8
new_warnings_or_lints_introduced: 0
cross_platform_build:
  ruff_check: PASS (All checks passed)
  import_smoke: PASS (`from app.main import app` OK)
  mypy: UNAVAILABLE (venv 환경 갭 — `error: Failed to spawn: mypy — program not found`. 이 세션 이전 SPEC들과 동일한 기존 갭, 본 SPEC이 만든 회귀 아님)
total_run_phase_files: 6
m1_to_mN_commit_strategy: single-commit (TASK-002/003/005 전부 동일 파일 `surge_detector.py`를 수정 — 분리 커밋 시 중간 상태가 테스트 불통과 상태가 됨)

### 이월 과제 (본 SPEC 범위 밖, 별도 관측 과제)

- **프로덕션 코어 수 미확인**: SSH 키(`/c/Users/Nexsol/Downloads/news-hive-key.key`) 부재로
  read-only `nproc` 프로브 실패. TASK-005 배치 전환은 characterization 테스트로
  **결과값 동등성만** 보증했고 프로덕션 성능 영향은 미검증이다(1코어에서 배치가 순차보다
  느리다는 실측이 plan.md TASK-001 결과표에 있음). AC-102-007은 산출 동등성만 요구하므로
  프로덕션 성능 저하가 있어도 AC는 통과한다 — 별도 관측 과제로 이월.
- **Option A 재검토 선행 조건**: (a) `_fetch_ph` price_5d_trend 루프 배치 전환,
  (b) 프로덕션 코어 수 확인. 상세는 plan.md TASK-006 "이월 과제".

## §E.4 Sync-phase Audit-Ready Signal

_<pending sync-phase>_
