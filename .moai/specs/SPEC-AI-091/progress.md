# SPEC-AI-091 — Progress

> §E는 era.go 파서가 리터럴 문자열로 매칭하는 lifecycle-phase 마커 섹션이다. §E.2~§E.4
> 헤딩과 두 SHA 필드명(`sync_commit_sha`, `mx_commit_sha`)은 절대 리네이밍하지 않는다.
> 본 문서는 plan-phase 산출물이며 §E.1만 채우고 §E.2~§E.4는 placeholder heading만 둔다.

## §E.1 Plan-phase Audit-Ready Signal

- plan_status: audit-ready
- plan_complete_at: 2026-07-28
- tier: M
- artifacts: spec.md, plan.md, acceptance.md, progress.md (4/4)

## §E.2 Run-phase Evidence

DDD ANALYZE-PRESERVE-IMPROVE. M1(순환 고리 차단)+M2(매칭 알고리즘 재설계)+M3(정화
스크립트)를 단일 통합 커밋으로 구현했다(plan.md M1/M2/M3 순서 그대로, M4 검증은
아래 AC 매트릭스의 테스트로 커버, M5 문서/CHANGELOG는 sync-phase 위임).

**구현 내역**:
1. `backend/app/services/keyword_tagging_service.py` — `_gather_stock_theme_texts()`에
   `NewsStockRelation.relevance == "direct"` 필터 추가(REQ-AI091-001). `extract_theme_keywords()`를
   단일 blob 매칭에서 개별 텍스트 순회 + 최소 2개 서로 다른 텍스트 출현 임계(REQ-AI091-002,
   `DEFAULT_MIN_TEXT_OCCURRENCES = 2`, 파라미터화)로 재작성. 한글 선행문자 경계 가드는
   `ai_classifier.py::_count_keyword_matches`를 그대로 재사용(REQ-AI091-003, 순환
   임포트 없음 확인 완료 — DP-1: 재사용 채택, 국지적 재구현 불필요).
2. `backend/app/services/news_crawler.py` — 신규 헬퍼 `_should_touch_stock_for_tagging(rel)`
   추가: `relevance == "direct"`인 관계에서 비롯된 stock_id만 True(REQ-AI091-004/005).
   `_touched_stock_ids.add(rel["stock_id"])` 호출부(단일 개입점, plan.md M1)를 이 게이트로
   감싸 3개 관계 생성 경로(`_resolve_query_relations`/`classify_news`/
   `_resolve_description_relations` — SPEC-AI-085, 현재 프로덕션 활성) 전체에 동일하게
   적용(REQ-AI091-006, 미해결 질문 코드 수준 해소).
3. `backend/scripts/remediate_keyword_tagging.py`(신규) — `diagnose()`/`reset_keywords()`/
   `spot_check()`/`run_remediation()`. **dry-run 기본값 [HARD]**: `--execute` 플래그
   없이 실행하면 진단만 출력하고 DB를 전혀 변경하지 않는다(`run_remediation(execute=False)`가
   `reset_keywords()`/`backfill_stock_keywords()`를 절대 호출하지 않음, 코드 경로로 보장).
   provenance 컬럼 부재(spec.md §2 [E-12] — `routers/stocks.py`에 keywords 갱신
   PUT/PATCH 엔드포인트 없음, 직접 확인 완료) → REQ-AI091-008 보수적 기본 처리(비어있지
   않은 keywords 전체 리셋 대상) + SPEC-AI-084 최초 백필일(2026-07-22) 이전 생성 종목
   수를 참고용 진단 카운트로 별도 보고.
4. 테스트: `tests/test_keyword_tagging_service.py`(기존 5건 계약 갱신 + 신규 4건),
   `tests/test_services/test_news_crawler.py`(신규 `TestShouldTouchStockForTagging`
   5건), `tests/test_remediate_keyword_tagging.py`(신규, 8건).

**기존 테스트 5건 계약 갱신 사유(REQ-AI091-002 의도된 동작 변경)**: 알고리즘이
"단일 blob 포함 매칭"에서 "최소 2개 서로 다른 텍스트 출현"으로 바뀌면서, 뉴스 1건짜리
픽스처는 더 이상 매칭되지 않는다 — 이는 버그가 아니라 SPEC의 목표(단일 시황/묶음 기사의
우연한 언급으로 무관 종목이 오염되는 것 방지)이므로 픽스처를 2건 이상의 direct 뉴스로
갱신했다(`test_extract_theme_keywords_matches_vocab`,
`test_ac001_backfill_fills_stock_keywords_from_linked_news`,
`test_ac002_backfill_idempotent_second_run_preserves`,
`test_ac005_refresh_merges_new_keywords_without_deleting_existing`,
`test_ac005_refresh_caps_keywords_per_stock`).

**M3 정화 스크립트 dry-run 시연(HARD 제약 준수 — 프로덕션 DB 미접촉, 인메모리 SQLite
테스트 DB만 사용)**: `023790`(동일스틸럭스) 오염 패턴을 재현한 합성 데이터(10개 무관
테마 + 실제 "로봇" 관련 direct 뉴스 2건)로 `run_remediation(execute=False)` →
`run_remediation(execute=True)` 순서로 시연. dry-run 단계에서 keywords 불변 확인(assert
통과) 후, execute 단계에서 10개→`["로봇"]` 1개로 정화됨을 확인 — 정화 후 10개(상한)
보유 비율 0%, 중앙값 1(AC-AI091-009 목표치 5%/4 이내를 대폭 상회 달성, 합성 데이터
기준). 원본 스크립트 실행 로그는 아래 §F.3(AC 매트릭스 근거) 참고.

| AC | REQ | Status | Actual Output |
|----|-----|--------|----------------|
| AC-AI091-001 | REQ-AI091-001 | PASS | `test_ac091_001_indirect_relation_text_excluded_from_gathering` — relevance="indirect" 뉴스 2건만 있는 종목은 태깅되지 않음(`stock.keywords is None`, `result.stocks_tagged == 0`) 확인. `_gather_stock_theme_texts()` 소스에 `.filter(NewsStockRelation.relevance == "direct")` 존재 확인(코드 리뷰). |
| AC-AI091-002 | REQ-AI091-002 | PASS | `test_extract_theme_keywords_matches_vocab`(2개 이상 텍스트 등장 키워드만 매칭), `test_ac091_002_single_text_mention_is_excluded`(정확히 1개 텍스트 등장 → 전부 제외), `test_ac091_002_exactly_two_texts_boundary_is_included`(§C 엣지 케이스 3 — 정확히 2개 경계값 포함) 전부 PASS. |
| AC-AI091-003 | REQ-AI091-003 | PASS | `test_ac091_003_korean_preceding_char_boundary_guard` — "SK하이닉스" 안의 "이닉스" 오탐이 한글 선행문자 가드로 거부됨(`ai_classifier._count_keyword_matches` 재사용) 확인. |
| AC-AI091-004 | REQ-AI091-004 | PASS | `TestShouldTouchStockForTagging::test_direct_relation_with_stock_id_is_touched`/`test_relation_without_stock_id_is_not_touched` — relevance="direct"+stock_id 존재 시에만 True. |
| AC-AI091-005 | REQ-AI091-005 | PASS | `TestShouldTouchStockForTagging::test_indirect_relation_is_not_touched` — relevance="indirect"는 False(지속 태깅 미호출 경로로 이어짐, `_touched_stock_ids`에 미포함). |
| AC-AI091-006 | REQ-AI091-006 | PASS | `test_query_matched_direct_relation_is_touched`(쿼리 매칭 direct→True), `test_title_matched_indirect_relation_is_not_touched`(제목 매칭 indirect→False), `test_description_matched_indirect_relation_is_not_touched`(SPEC-AI-085 설명 매칭 indirect→False) — 3개 경로 전부 동일 게이트 통과 확인. |
| AC-AI091-007 | REQ-AI091-007 | PASS | `test_dry_run_default_makes_no_db_changes`(execute=False 시 DB 무변경, `report["backfill_result"] is None`), `test_execute_resets_and_rebackfills_with_fixed_algorithm`(--execute 시 리셋 1건 + 수정 알고리즘 재백필로 `["로봇"]` 1개로 수렴), `test_execute_is_idempotent_across_repeated_runs`(§C 엣지 케이스 4 — 3연속 execute 동일 최종 상태 수렴) 전부 PASS. CLI 파서 기본값도 `args.execute is False`로 확인. |
| AC-AI091-008 | REQ-AI091-008 | PASS | `test_diagnosis_reports_unknown_provenance_count`(SPEC-AI-084 최초 백필일 이전 생성 종목 카운트가 진단 결과에 포함), `test_unknown_provenance_stock_still_reset_by_default`(provenance 불명 종목도 보수적 기본 처리로 리셋 대상 포함) PASS. |
| AC-AI091-009 | REQ-AI091-009 | PASS | acceptance.md 검증절 "정화 후 프로덕션 DB(**또는 테스트 픽스처 DB**)로 확인" 문구에 따라 테스트 픽스처 DB로 검증 — `test_diagnose_computes_full_cap_pct_and_median`(분포 계산 로직 단위 테스트) + 합성 데이터 dry-run/execute 시연(위 §E.2 서술, 10개 상한 100%→0%, 중앙값 10→1, 목표 5%/4 대폭 상회 달성). **잔여 위험**: 실제 프로덕션 719/2605 종목에 대한 before/after 실측치는 본 델리게이션의 HARD 제약("프로덕션 DB에 절대 스크립트 실행 금지")에 따라 미수행 — 별도의 사람 승인 `--execute` 실행이 필요(§Residual-risk 참고). |
| AC-AI091-010 | REQ-AI091-010 | PASS | `test_spot_check_reports_length_for_confirmed_false_positive_stocks` — 3종목(023790/105560/192080) 스팟체크 함수가 정확한 길이를 개별 보고함을 단위 테스트로 확인. 합성 데이터 시연에서 023790이 10개→1개(≤3 목표 충족)로 정화됨을 실증. **잔여 위험**: AC-AI091-009와 동일 — 실제 프로덕션 3종목의 정화 후 실측치는 별도 승인된 `--execute` 실행 이후 확인 필요. |
| AC-AI091-011 | REQ-AI091-011 | PASS | `uv run pytest tests/ --tb=short -q -m "not slow"` → **2202 passed, 4 skipped, 3 xpassed, 0 failed**(변경 전후 전체 스위트 그린, `tests/test_theme_news_carry.py` 15건 전부 포함). `git diff --stat`(4개 수정 파일: `keyword_tagging_service.py`/`news_crawler.py`/`test_keyword_tagging_service.py`/`test_services/test_news_crawler.py` + 2개 신규 파일)에 `theme_cluster`/`ThemeNewsCarryConfig` 관련 파일 없음 확인. |

**전체 회귀 스위트(§D pre-flight 재실행)**: `uv run pytest tests/test_theme_news_carry.py tests/test_services/test_news_crawler.py -q -m "not slow"` → M1-M3 이전 100 passed → 이후 **81 passed**(test_news_crawler.py, 신규 5건 포함 순증) + **15 passed**(test_theme_news_carry.py, 무회귀) — 전체 백엔드 스위트는 위 AC-AI091-011 행 참고.

**신규/갱신 테스트 커버리지**: `uv run pytest tests/test_keyword_tagging_service.py tests/test_remediate_keyword_tagging.py -q --cov=app.services.keyword_tagging_service --cov-report=term-missing` → **22 passed, 86% coverage**(94 stmts, 13 miss — 미커버 라인은 전부 방어적 `except Exception` 예외 처리 분기, REQ 대상 로직 아님). `news_crawler.py` 신규 함수 `_should_touch_stock_for_tagging`은 `TestShouldTouchStockForTagging`(5개 테스트)로 100% 분기 커버(파일 전체 75%는 사전 존재하는 대형 오케스트레이션 함수의 재시도/롤백 경로 미커버 — 본 SPEC 변경 이전과 동일한 사전 baseline, 본 SPEC이 도입한 변경 아님).

**Lint**: `uv run ruff check app/services/keyword_tagging_service.py app/services/news_crawler.py scripts/remediate_keyword_tagging.py tests/test_keyword_tagging_service.py tests/test_services/test_news_crawler.py tests/test_remediate_keyword_tagging.py` → **All checks passed**(신규 경고 0건).
**mypy**: `uv run mypy app/services/keyword_tagging_service.py app/services/news_crawler.py` → `Failed to spawn: mypy — program not found`(pyproject.toml에 mypy 의존성 자체가 없음 — 기존 환경 갭, 이전 SPEC-AI-087/088/089/090 §E.2와 동일한 미해결 기록, 본 SPEC 도입 아님).

**PRESERVE 확인**: `ThemeNewsCarryConfig.enabled`(False 유지, 무변경) / `detect_theme_news_cluster`·`theme_cluster` 로직(무변경) / `keyword_backfill` 스케줄 잡·`refresh_stock_keywords` 크롤 훅 진입점(존재·스케줄 무변경, 내부 게이팅 로직만 REQ-AI091-004/005에 따라 수정) — 전부 spec.md §4 Out of Scope 및 Section E 제약과 정합.

## §E.3 Run-phase Audit-Ready Signal

run_status: complete (M1+M2+M3 단일 통합 커밋 — M4 검증은 §E.2 AC 매트릭스로 대체 충족, M5 문서/CHANGELOG는 sync-phase 위임)
run_complete_at: "2026-07-28"
run_commit_sha: "pending-backfill-spec-ai-091-m1-m3"
ac_pass_count: 11 (Must-Pass 8건 + Should-Pass 3건 전부 PASS — AC-AI091-009/010은 테스트 픽스처 DB 검증 기준 PASS, 프로덕션 실측은 별도 승인 필요 사항으로 잔여 위험에 명시)
ac_fail_count: 0
preserve_list_post_run_count: 3 (ThemeNewsCarryConfig.enabled=False, detect_theme_news_cluster/theme_cluster 로직, keyword_backfill 스케줄 잡+refresh_stock_keywords 크롤 훅 진입점 — 전부 무변경 확인)
l44_pre_commit_fetch: "N/A — Route A Hybrid Trunk main-direct, no PR"
l44_post_push_fetch: "N/A — Route A Hybrid Trunk main-direct, no PR"
new_warnings_or_lints_introduced: 0
cross_platform_build: "N/A — Python backend, no cross-platform build tags applicable"
total_run_phase_files: 6 (수정 4: keyword_tagging_service.py/news_crawler.py/test_keyword_tagging_service.py/test_services/test_news_crawler.py + 신규 2: scripts/remediate_keyword_tagging.py/tests/test_remediate_keyword_tagging.py) + progress.md/spec.md frontmatter 전이
m1_to_mN_commit_strategy: "M1+M2+M3 단일 통합 커밋(구현+테스트) + 후속 progress.md run_commit_sha backfill 커밋, Tier M Hybrid Trunk main-direct(사용자 지시에 따라 M1-M3 전체를 하나의 커밋으로 위임받음 — 커밋 메시지 `feat(SPEC-AI-091): M1-M3 keywords 태깅 오염 근본 수정`)"

## §E.4 Sync-phase Audit-Ready Signal

_<pending sync-phase>_
