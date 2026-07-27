## SPEC-AI-088 Progress

- Created: 2026-07-27 (plan phase)

## §E.1 Plan-phase Audit-Ready Signal

plan_status: audit-ready
plan_complete_at: "2026-07-27"

spec.md/plan.md/acceptance.md 3개 아티팩트 작성 완료. REQ-001~005 전량 AC 커버리지 확보
(5/5). Tier S(측정 전용, 신규 fetch 비용 0, 마이그레이션 없음, 4개 프로덕션 파일 + 신규
테스트 1개). plan-auditor 검토 대기 중.

## §E.2 Run-phase Evidence

DDD ANALYZE-PRESERVE-IMPROVE(재현-우선). M1 특성화 테스트 선행: `backend/tests/test_spec_ai_088.py`
(34개 테스트) 작성 후 구현 전 실행 결과 34개 중 20개 FAIL(RED, 신규 AC 동작 미구현)
+ 14개 PASS(PRESERVE 백워드 호환 baseline, non-same_day/next_day 경로 키 부재 등)로
gap을 재현. M2(REQ-001~003, `fund_manager.py`/`disclosure_impact_scorer.py`/
`surge_detector.py`)와 M3-M4(REQ-004~005, `surge_trading.py` 헬퍼+API 배선) 구현 후
전량 GREEN(34/34 PASS). REQ-002 함수 교체(`fetch_current_price`→
`fetch_current_price_with_change`)로 실제 코드 경로가 바뀌면서 기존 테스트
`test_disclosure_impact_scorer_immediate_surge.py`의 mock 대상 5곳이 구 함수를 겨냥하고
있어 실네트워크 호출로 이어지던 문제를 발견·수정(REQ-002의 직접적 귀결, 판정 로직 무영향).

| AC | REQ | Status | Actual Output |
|----|-----|--------|----------------|
| AC-088-001 | REQ-001 | PASS | `test_ac088_001_same_day_new_signal_gets_pre_signal_change_pct` PASS. same_day 신규 시그널에 change_rate=5.91이 pre_signal_change_pct로 저장, mock 호출 1회(신규 fetch 없음) 확인. |
| AC-088-002 [HARD] | REQ-001 | PASS | `test_ac088_002_non_same_day_no_pre_signal_change_pct_key` PASS. next_day 지평에서는 change_rate 가용해도 키 미포함(기존 horizon 키 생략 패턴과 동일). |
| AC-088-003 | REQ-002 | PASS | `test_ac088_003_same_day_horizon_stores_pre_signal_change_pct` / `test_ac088_003_fallback_endpoint_delta_documented` PASS. price_at_signal은 기존 경로로(12540), pre_signal_change_pct는 신규(5.91), fetch 1회 유지. 폴백 엔드포인트 델타(/integration 구·폐기 vs /price 신)를 소스로 재확인. |
| AC-088-004 | REQ-002 | PASS | `test_ac088_004_next_day_horizon_no_pre_signal_change_pct_key` PASS. next_day 지평에서 키 미포함. |
| AC-088-005 | REQ-003 | PASS | `test_ac088_005_pre_signal_change_pct_is_always_zero` / `test_ac088_005_zero_value_survives_json_round_trip` PASS. price_at_signal==t1_close 불변식, pre_signal_change_pct==0.0 항상 성립, 이력 조회 1회(신규 fetch 없음), 기존 yesterday_change_pct 키 보존. |
| AC-088-006 [HARD] | REQ-004 | PASS | `TestExtractPreSignalChangePctHelper`(10개) + `TestEvaluationPredicatesUnchangedByNewKey`(9개, parametrize) PASS. None/빈문자열/키부재/손상JSON/비-dict 전부 예외 없이 None 반환. `_is_same_day_event_horizon_signal`/`_is_near_limit_up_carry_signal`이 신규 키 유무와 무관하게 동일 결과(diff 0) 확인. |
| AC-088-007 | REQ-005 | PASS | `test_ac088_007_signal_details_includes_pre_signal_change_pct` / `test_ac088_007_missing_key_returns_null` PASS. `GET /evaluation/{date_str}` 응답의 signal_details에 값/null 정확히 노출. |
| AC-088-008 | REQ-005 | PASS | `test_ac088_008_today_unevaluated_branch_includes_key` / `test_ac088_008_past_evaluated_branch_missing_key_returns_null` PASS. `GET /prediction-history` 양쪽 분기(오늘 미평가/과거 평가완료) 모두 키 노출. |
| AC-088-009 [HARD] | REQ-001~005 (cross-cutting) | PASS | `TestEvaluationPredicatesUnchangedByNewKey` + `TestAdditiveOnlyDesignPrinciple` PASS + 전체 백엔드 스위트 무회귀 + `ruff check .` 통과(아래 실측 참조). `git diff app/services/surge_evaluation_service.py`는 빈 diff(코드 무변경 확인). |

**전체 스위트 실측(2회 관측)**: 1차 실행(REQ-001~005 구현 직후, 기존 테스트 파일 수정 전)
`2144 passed, 1 failed`(`test_disclosure_impact_scorer_immediate_surge.py::TestCreateImmediateSurgeSignal::test_price_fetch_failure_falls_back_to_baseline_price` — REQ-002가 교체한 함수를 겨냥하지 않는 구 mock 대상 문제, 실네트워크 응답으로 인한 값 불일치이지 판정 로직 회귀 아님). 해당 테스트의 mock 대상 5곳을 `fetch_current_price`→`fetch_current_price_with_change`로 갱신 후 2차 실행:
`uv run pytest tests/ --tb=short -q -m "not slow"` → **2145 passed, 4 skipped, 3 xpassed, 0 failed**.
**Lint**: `uv run ruff check .` → All checks passed.
**mypy**: 이 환경에 mypy 미설치(`Failed to spawn: mypy — program not found`, SPEC-AI-087 §E.2와
동일한 기존 환경 갭) — 본 SPEC이 도입한 조건이 아니며 본 SPEC 범위에서 해결하지 않음(Gap로 기록).

## §E.3 Run-phase Audit-Ready Signal

run_status: complete
run_complete_at: "2026-07-27"
run_commit_sha: "d98f8f152bbca72c251cd60c83d3dee50dd6c1c2"
ac_pass_count: 9
ac_fail_count: 0
preserve_list_post_run_count: 1
l44_pre_commit_fetch: "N/A — Route A Hybrid Trunk main-direct, no PR"
l44_post_push_fetch: "N/A — Route A Hybrid Trunk main-direct, no PR"
new_warnings_or_lints_introduced: 0
cross_platform_build: "N/A — Python backend, no cross-platform build tags applicable"
total_run_phase_files: 6
m1_to_mN_commit_strategy: "milestone별 개별 커밋(M1/M2/M3-M4 통합/M5), 각 커밋 직후 push(Tier S Hybrid Trunk main-direct)"

## §E.4 Sync-phase Audit-Ready Signal

sync_status: complete
sync_complete_at: "2026-07-27"
sync_commit_sha: "pending-backfill-sync-spec-ai-088"

**B12 self-test 결과**:
- a) pre-emission grep `grep -c 'SPEC-AI-088' CHANGELOG.md` → 커밋 전 0 (중복 없음 확인)
- b) AC count 일치 — acceptance.md SSOT `grep -cE '^### AC-088-[0-9]+'` → 9, CHANGELOG 본문 REQ-001~005(9 AC 대응) 언급과 일치
- c) 파일 경로 검증 — `ls backend/app/services/fund_manager.py backend/app/services/disclosure_impact_scorer.py backend/app/services/surge_detector.py backend/app/routers/surge_trading.py backend/tests/test_spec_ai_088.py` 전부 존재 확인

**sync-phase 독립 재검증(§E.2 재구현이 아닌 재관측)**:
- `uv run pytest tests/test_spec_ai_088.py -q --tb=short`(backend/) → `34 passed in 2.37s`
- `uv run ruff check .`(backend/) → `All checks passed!`

frontmatter status 전이: spec.md `status: in-progress` → `completed`(단일 sync 커밋, 3-phase close). plan.md/acceptance.md는 frontmatter 없음(Tier S — spec.md만 frontmatter 보유).

CHANGELOG.md `[Unreleased]` 섹션에 SPEC-AI-088 항목 추가(목적/핵심변경/Out of Scope/테스트/신규 fetch 비용/예측기록모드/배포상태 — 기존 SPEC-AI-087 항목과 동일 형식).
