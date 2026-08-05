# SPEC-AI-101 Progress

## §E.1 Plan-phase Audit-Ready Signal

plan_status: audit-ready
plan_complete_at: 2026-08-04
plan_audit_verdict: PASS
plan_audit_score: 0.92
plan_audit_iteration: 1
plan_audit_report: .moai/reports/plan-audit/SPEC-AI-101-review-1.md
plan_audit_tier_threshold: 0.85 (Tier L)

## §E.2 Run-phase Evidence

| AC ID | 대응 REQ | Status | 검증 방법 | Actual Output |
|-------|----------|--------|-----------|---------------|
| AC-101-001 | REQ-AI101-001 | PASS | `pytest tests/test_spec_ai_101.py::TestComputeForwardMaxReturn::test_known_values_match_design_formula` | `day_high_price=1200, forward_max_return_pct≈14.2857` — 설계 수식(design.md §B.1)과 정확히 일치 |
| AC-101-002 | REQ-AI101-001 | PASS | `pytest ...::TestPersistSignalForwardOutcomes::test_upsert_is_idempotent_on_rerun` | 동일 `(trading_date, fund_signal_id)` 2회 실행 후 행 수=1 확인 |
| AC-101-003 | REQ-AI101-001 | PASS | `pytest ...::TestPersistSignalForwardOutcomes::test_price_at_signal_none_persists_null_derived_fields` + `test_t1_close_lookup_failure_persists_null_without_raising` | 두 실패 케이스 모두 예외 없이 완료, 파생값 NULL 확인 |
| AC-101-004 | REQ-AI101-002 | PASS | `pytest ...::TestEvaluateSurgePredictionsForwardIntegration::test_close_based_miss_but_forward_based_hit_reclassified_in_parallel_metric` | 종가기준 FN=0(표준 무변경)이나 forward_based_recall/precision=1.0(TP 재분류) |
| AC-101-005 | REQ-AI101-002 | PASS | `pytest ...::test_standard_tp_fp_fn_unchanged_when_no_price_at_signal` + 전체 회귀(2348 passed) | TP=2/FP=1/FN=1 기존과 동일. `git diff` 확인: predicted_set/actual_set/legacy_recall/scannable_recall/coverage 산출 로직 라인 무변경(신규 컬럼 select 추가만, 필터/조인 무수정) |
| AC-101-006 | REQ-AI101-004 | PASS | `pytest ...::TestShadowComparisonPersistence::test_no_change_cycle_still_persists_one_row` | `merged={}` 무변화 사이클에도 1행 적재, change_pct=0.0 |
| AC-101-007 | REQ-AI101-004 | PASS | `pytest ...::test_persistence_failure_does_not_raise` | `db.commit` 예외 주입해도 함수가 예외를 전파하지 않음 |
| AC-101-008 | REQ-AI101-004 | PASS | `git diff` 확인 | `run_horizon_shadow_comparison` 함수 시그니처(`db` 인자 추가)와 본문 하단(영속화 추가)만 변경, `compute_ensemble_score/compute_horizon_signature/select_effective_threshold` 판정 로직 라인 0건 변경 |
| AC-101-009 | REQ-AI101-003 | PASS | `git diff -- backend/app/surge_config/surge_detection.yaml` | `shadow_mode_enabled: false → true` 1줄만 변경, `enabled:` 라인 무변경 확인 |
| AC-101-010 | REQ-AI101-005 | PASS | `pytest ...::TestCheckHorizonTransitionReadiness::test_aggregates_days_regimes_and_max_change_pct` | BULL 5일/SIDEWAYS 3일/BEAR 2일 fixture → observed_trading_days=10, regimes={BULL,SIDEWAYS,BEAR}, max_change_pct=40.0 정확 집계 |
| AC-101-011 | REQ-AI101-005 | PASS | `pytest ...::TestNoAutoEnabledTransition::test_no_source_file_sets_enabled_to_true` (grep 대체 순수 Python 스캔) | `app/services/`, `app/surge_config/` 전체 스캔 결과 0건 |
| AC-101-012 | REQ-AI101-006 | PASS | 문서 검토 | 본 §E.2/DoD 어디에도 `enabled=true` 전환 항목 없음 — `enabled` 필드는 TASK-005에서 무수정(false 유지) |

### 마이그레이션

- `073_surge_signal_forward_outcome` (down_revision: `072_surge_feature_snapshot`) — `surge_signal_forward_outcome` 테이블 신설 (신규 additive)
- `074_surge_horizon_shadow_observation` (down_revision: `073_surge_signal_forward_outcome`) — `surge_horizon_shadow_observation` 테이블 신설 (신규 additive)

### Open Questions 해소 상태

- **OQ1 (PK/컬럼명)**: `fund_signal_id`를 `fund_signals.id` FK + `(trading_date, fund_signal_id)` UNIQUE로 확정 — `FundSignal.stock_id → stocks.id` FK 관례를 그대로 따름.
- **OQ2 (price_at_signal 실측 채움률)**: **미확인 — 잔여 리스크로 이월**. 프로덕션 DB 도메인 검증을 시도했으나 이 세션에서 SSH 키(`/c/Users/Nexsol/Downloads/news-hive-key.key`)에 접근할 수 없어(파일 부재) 프로덕션 쿼리를 실행하지 못했다. REQ-AI101-001의 NULL-safety 설계(AC-101-003)는 채움률과 무관하게 항상 안전하므로 구현 자체는 채움률에 의존하지 않지만, 신규 지표의 실효 표본 크기는 다음 세션에서 프로덕션 DB로 확인이 필요하다(design.md §H 리스크와 동일).
- **OQ3 (섀도우 테이블 보존 기간)**: 미확정 상태 유지 — 본 SPEC DoD 조건 아님(spec.md 명시).

## §E.3 Run-phase Audit-Ready Signal

run_complete_at: 2026-08-04
run_commit_sha: 3ae28ae1addd35f705beac782e75bb27715dead0
run_status: implemented
ac_pass_count: 12
ac_fail_count: 0
preserve_list_post_run_count: 5
new_warnings_or_lints_introduced: 0
cross_platform_build:
  ruff_check: PASS (0 findings, 8 files)
  mypy: UNAVAILABLE (venv 환경 갭, 이 세션 이전 SPEC들과 동일한 기존 갭 — 잔여 리스크)
total_run_phase_files: 10
m1_to_mN_commit_strategy: single-commit (Tier L이나 TASK 간 강한 순서 의존성 — M1 단일 커밋으로 통합)

## §E.4 Sync-phase Audit-Ready Signal

sync_complete_at: 2026-08-05
sync_status: completed
sync_commit_sha: pending-backfill-3ae28ae1
changelog_entry_position: top of [Unreleased] (SPEC-AI-101 entry precedes SPEC-AI-103)
frontmatter_status_transitions:
  spec.md: in-progress -> completed (updated: 2026-08-05)
  plan.md: no frontmatter block (unaffected — matches SPEC-AI-103 sibling precedent)
  acceptance.md: no frontmatter block (unaffected)
  design.md: no frontmatter block (unaffected)
  research.md: no frontmatter block (unaffected)

### 잔여 리스크 이월 — OQ2 (production price_at_signal 채움률)

OQ2(§Open Questions 해소 상태, 위 §E.2)는 sync-phase에서도 **미확인 상태로 이월**된다.
GATE 2에서 사용자가 `status: completed` 전환을 승인하며 함께 검토·수용한 판단 근거:
REQ-AI101-001의 NULL-safety 설계(AC-101-003)는 채움률과 무관하게 항상 안전하므로 이
갭은 코드 결함이 아니라 향후 프로덕션 데이터로 확인이 필요한 모니터링 항목이다
(mypy 미가용을 잔여 위험으로 수용한 이 프로젝트의 기존 선례와 동일한 패턴). SSH 키
(`news-hive-key.key`) 파일이 확보되는 다음 세션에서 도메인 쿼리로 확인할 것.

### DB 스키마 문서 동기화 스킵 근거

`.moai/config/sections/db.yaml`의 `db.enabled: false`(opt-in 미설정)에 따라
`.moai/project/db/{schema.md,erd.mmd,migrations.md}` 동기화를 이번 sync에서 명시적으로
스킵했다 — 신규 테이블 2개(`surge_signal_forward_outcome`, `surge_horizon_shadow_observation`)
가 이 문서들에 반영되지 않은 상태로 남는다. 침묵 누락이 아니라 GATE 2에서 사용자에게
명시적으로 플래그한 config 갭이며, `db.enabled`가 향후 `true`로 전환되면 이 SPEC을
포함한 과거 마이그레이션 일괄 반영이 필요하다.

### B12 CHANGELOG 방출 자가검증 (사전 체크 3종)

1. 방출 전 grep: `grep -c 'SPEC-AI-101' CHANGELOG.md` → 0 (사전) → 1 (방출 후, 본 섹션
   작성 시점 재확인 예정)
2. AC 개수 일치: `acceptance.md` SSOT AC 행 수 12개(`grep -cE '^### AC-101-[0-9]+'`)
   = CHANGELOG 엔트리의 "AC-101-001~012 전량 12개 PASS" 명시 개수 일치
3. 파일 경로 검증: CHANGELOG 엔트리에 언급된 9개 변경 파일 전부 `git show --stat 3ae28ae`
   출력과 대조 확인 완료(§E.3 run_commit_sha 기준)
