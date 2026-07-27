## SPEC-AI-087 Progress

- Created: 2026-07-27 (plan phase)

## §E.1 Plan-phase Audit-Ready Signal

plan_status: audit-ready
plan_complete_at: "2026-07-27"

spec.md/plan.md/acceptance.md 3개 아티팩트 작성 완료. REQ-001~008 전량 AC 커버리지 확보
(8/8). plan-auditor 검토 대기 중.

## §E.2 Run-phase Evidence

DDD ANALYZE-PRESERVE-IMPROVE, M1~M5 완료(M4는 M1/M2에 이미 포함된 회귀 assert로
별도 커밋 없이 충족). 신규 테스트 파일 `backend/tests/test_spec_ai_087.py`(17개
테스트) 전량 GREEN.

| AC | REQ | Status | Actual Output |
|----|-----|--------|----------------|
| AC-087-001 | REQ-001 | PASS | `test_constant_is_60` / `test_ac087_001_page_11_data_reflected_in_cap_map` / `test_ac087_001_safety_cap_stops_exactly_at_60_pages` 전부 PASS. 페이지 11 데이터가 cap_map에 반영됨을 확인, 안전 상한(60페이지) 경계 고정. |
| AC-087-002 [HARD] | REQ-002 | PASS | `test_ac087_002_top500_stock_value_and_calc_method_unchanged` / `test_ac087_002_update_scope_stays_within_stocks_table_intersection` PASS. 계산 방식·갱신 범위(stocks 테이블 교집합) 불변, `db.add` 미호출 확인. |
| AC-087-003 [HARD] | REQ-003 | PASS | `test_ac087_003_default_zero_excludes_null_market_cap` PASS. `null_cap_min_slots=0`(기본값)에서 NULL 시총 종목 미포함, 레거시 단일 조건 조회와 동등. |
| AC-087-004 | REQ-003 | PASS | `test_ac087_004_floor_quota_includes_null_stocks_up_to_slots` / `test_ac087_004_rotation_across_dates` PASS. `null_cap_min_slots=5`에서 NULL 10개 중 정확히 5개 편입, 날짜별 로테이션 서브셋 상이함 확인. |
| AC-087-005 | REQ-004 | PASS | `test_characterize_default_off_excludes_null_market_cap` / `test_ac087_005_null_included_within_existing_cap_lower_priority` PASS. `cascade_include_null_market_cap=True`에서 non-null 2개 우선 포함 + NULL 최대 1개, 총 3개(`max_cascade_per_flagship`) 이내. |
| AC-087-006 | REQ-005 | PASS | `test_characterize_default_off_excludes_null_market_cap` / `test_ac087_006_null_included_within_existing_limits_lower_priority` PASS. `runner_include_null_market_cap=True`에서 non-null 피어 항상 포함, 런너 2개([:2]) 상한 불변. |
| AC-087-007 [HARD] | REQ-006 | PASS | `test_ac087_007_flagship_exclusion_unaffected` / `test_ac087_007_bollinger_squeeze_top_n_query_unaffected` PASS. REQ-003~005 opt-in 활성화 상태에서도 flagship NULL 배제 로직과 bollinger_squeeze 상위 N 쿼리 무변경 확인. |
| AC-087-008 | REQ-007 | PASS | `test_ac087_008_backfill_job_registered_in_start_scheduler` / `test_ac087_008_backfill_scans_null_and_preserves_existing` PASS. `keyword_backfill` 잡 ID로 `start_scheduler()`에 등록됨, 기존 keywords 값 종목 불변 확인. |
| AC-087-009 [HARD] | REQ-008 | PASS | 신규 필드 3개 기본값 backward-compat 확인(`test_new_config_fields_default_to_backward_compat_values`) + 전체 백엔드 스위트 무회귀(2094→2111 passed, 정확히 +17건, 0 회귀) + `ruff check .` 통과. |

**전체 스위트**: `uv run pytest tests/ --tb=short -q -m "not slow"` → 2111 passed, 4 skipped,
3 xpassed (baseline 2094 passed 대비 정확히 +17 = 신규 테스트 파일 전량, 0 회귀).
**Lint**: `uv run ruff check .` → All checks passed.
**mypy**: 이 환경에 mypy 미설치(`ModuleNotFoundError`, pyproject.toml에도 미선언) —
본 SPEC이 도입한 사전 조건이 아닌 기존 환경 갭이며, 본 SPEC 범위에서 해결하지 않음(Gap로 기록).

## §E.3 Run-phase Audit-Ready Signal

run_status: complete
run_complete_at: "2026-07-27"
run_commit_sha: "5ee07733a9ad8eb5221d5c806f6202005541d98f"
ac_pass_count: 9
ac_fail_count: 0
preserve_list_post_run_count: 4
new_warnings_or_lints_introduced: 0
total_run_phase_files: 4
m1_to_mN_commit_strategy: "milestone별 개별 커밋(M1/M2/M3/M5, M4는 M1/M2에 포함), 각 커밋 직후 push"

## §E.4 Sync-phase Audit-Ready Signal

sync_status: complete
sync_complete_at: "2026-07-27"
sync_commit_sha: "092c62a"

CHANGELOG.md `[Unreleased]` 섹션에 SPEC-AI-087 항목 추가(중복 방지 사전 grep 0건 확인),
spec.md frontmatter `status: in-progress → completed` 전이(단일 sync 커밋으로 3-phase close
병합). 진행상황 아티팩트 4종 중 spec.md(frontmatter만)/progress.md/CHANGELOG.md 3종만 이번
커밋 범위. plan.md/acceptance.md 본문은 무변경(소유권 경계 준수).

mypy 미설치 갭은 §E.2에서 이미 기록됨(기존 환경 갭, 본 SPEC 범위 아님) — CHANGELOG에도 정직하게
반영.
