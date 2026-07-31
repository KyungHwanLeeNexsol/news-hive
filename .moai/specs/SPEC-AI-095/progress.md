# SPEC-AI-095 Progress

## §E.1 Plan-phase Audit-Ready Signal

_<pending plan-auditor review>_

## §E.2 Run-phase Evidence

| AC ID | 대응 REQ | 검증 방법 | Actual Output | Status |
|-------|----------|-----------|----------------|--------|
| AC-095-001 | REQ-AI095-001 | `pytest -k test_high_based_recall_precision_intersect_with_predicted_set` | high_actual_set={A1,A2,D1}, predicted_set={A1,A2,A3} → TP_high=2, FN_high=1 → recall=precision=2/3 (assert 통과) | PASS |
| AC-095-002 | REQ-AI095-003 | `pytest -k test_idempotent_rerun_preserves_high_based_values_both_branches` | 1차(insert)/2차(update) 및 DB 재조회(db.expire_all) 모두 3값 non-null 확인 | PASS |
| AC-095-003 | REQ-AI095-003 | `pytest -k "test_persisted_values_match_after_requery or test_high_based_coverage_matches"` + `alembic heads`/`alembic history -r 069:070` | db.expire_all() 후 재조회 값이 계산값과 정확히 일치. coverage=0.5(2/4 high_change_rate NOT NULL) 확인. alembic heads → `070_surge_pred_eval_high_based (head)`, 069→070 체인 확인(정적 검증) | PASS-WITH-DEBT (아래 Gap 참고 — `alembic upgrade head`는 로컬 PostgreSQL 미기동으로 실제 DB 적용 미검증) |
| AC-095-004 | REQ-AI095-004 | `pytest -k test_exception_during_high_based_calc_nulls_metrics_but_preserves_primary_result` | `sqlfunc.coalesce` mock 예외 주입 → 3값 모두 None, 기존 8개 필드(TP=1,FP=1,FN=1,precision=0.5,recall=0.5,f1_score not None,scannable_recall=None,coverage=None) 정상 저장, 함수 예외 미전파 | PASS |
| AC-095-005 | REQ-AI095-005 | `pytest -k test_log_contains_high_based_field_names` | caplog에 "high_based_recall"/"high_based_precision"/"high_based_coverage" 3개 필드명 모두 노출 확인 | PASS |
| AC-095-006 | REQ-AI095-003 | `pytest -k test_new_columns_default_null_for_directly_inserted_row` + 마이그레이션 스크립트 코드 리뷰 | 직접 삽입 행의 3개 신규 컬럼 모두 None(백필 로직 없음, upgrade()는 add_column만 수행) | PASS |
| AC-095-007 | REQ-AI095-002 | `pytest -k test_existing_primary_metrics_completely_unchanged` + 기존 characterization 스위트 전체 재실행 + `git diff --name-only -- backend/ \| grep -E 'surge_actual_outcome_service\.py'` | 기존 8개 필드 값 완전 동일 확인. `test_surge_evaluation_service.py`+`test_surge_actual_outcome_service.py`+`test_spec_ai_092.py` 111 passed(무회귀). grep 매치 0건(exit=1) — `surge_actual_outcome_service.py` 전혀 미수정 확인 | PASS |
| AC-095-008 | REQ-AI095-001 | `pytest -k test_predicted_count_zero_yields_precision_none` | predicted_count=0 → high_based_precision=None(ZeroDivisionError 미발생), high_based_recall=0.0(분모>0이므로 정상 계산) | PASS |
| AC-095-009 | REQ-AI095-001 | `pytest -k test_high_actual_set_empty_yields_recall_none` | high_actual_set=∅(TP_high+FN_high=0) → high_based_recall=None(ZeroDivisionError 미발생), high_based_precision=0.0(TP_high=0, predicted_count=1>0이므로 정상 계산 — 간접 검증) | PASS |

불변식(REQ-AI095-002 동결 대상): `precision`/`recall`/`f1_score`/`true_positive`/`false_positive`/`false_negative`/`scannable_recall`/`coverage` 산출식, `SurgeActualOutcome.was_surge`(`change_rate >= 10.0`) 판정 기준 — 전체 코드 무변경(diff로 확인, `surge_actual_outcome_service.py` 0건 수정) 및 전체 회귀 스위트(2259 passed, 4 skipped, 3 xpassed, 0 failed) 통과로 검증.

## §E.3 Run-phase Audit-Ready Signal

```yaml
run_complete_at: "2026-07-31"
run_commit_sha: "pending-backfill-m1"
run_status: "audit-ready-with-debt"
ac_pass_count: 9
ac_fail_count: 0
preserve_list_post_run_count: 5  # plan.md §A.5 PRESERVE 목록 5개 항목 전체 무수정 확인
l44_pre_commit_fetch: "0 0"  # git fetch origin main; git rev-list --count --left-right origin/main...HEAD
l44_post_push_fetch: "pending"  # push 이후 갱신 예정
new_warnings_or_lints_introduced: false  # ruff check . → All checks passed (프로젝트 전체)
cross_platform_build:
  note: "Python 프로젝트 — Go 스타일 GOOS/GOARCH 크로스빌드 해당 없음. import sanity(`from app.main import app`) 통과로 대체"
  import_sanity: "OK"
total_run_phase_files: 5  # migration(신규 1) + model(수정 1) + service(수정 1) + test(수정 1) + spec.md frontmatter(수정 1)
m1_to_mN_commit_strategy: "single-commit"  # Tier M이나 변경 규모가 작아(384 insertions, 3파일) 단일 M1 커밋으로 처리
```

**Gap (미검증)**: `alembic upgrade head`를 실제 PostgreSQL에 적용해 성공을 확인하지 못했다 — 이 세션 환경에 로컬 PostgreSQL 서버가 기동되어 있지 않고(`localhost:5432` connection refused) Docker도 사용 불가능했다. 대신 `alembic heads`/`alembic history -r 069:070`로 리비전 체인의 정적 정합성(down_revision 체인, head 갱신)만 확인했고, pytest 전체 스위트는 SQLite `Base.metadata.create_all()` 경로(모델 정의에서 직접 스키마 생성, alembic 미경유)로 3개 신규 컬럼의 구조적 정합성을 간접 검증했다. 배포 파이프라인 또는 실제 PostgreSQL 접근 가능한 환경에서 `uv run alembic upgrade head; uv run alembic current` 최종 확인이 필요하다.

**Residual-risk (잔여 위험)**: (1) 위 alembic 실제 DB 적용 미검증 갭. (2) 운영 배치(18:30 KST) 소요 시간에 대한 신규 쿼리 2건(high_actual_rows + coverage 집계)의 실측 영향은 plan.md §E 리스크에 명시된 대로 배포 후 관찰 대상이며 이 세션에서는 측정하지 않았다. (3) mypy 미설치(프로젝트 의존성에 부재, CLAUDE.local.md 권장 명령이나 pyproject.toml/uv.lock에 없음) — 타입 체크는 미실행.

## §E.4 Sync-phase Audit-Ready Signal

_<pending sync-phase>_
