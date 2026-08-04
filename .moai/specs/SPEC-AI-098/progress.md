# SPEC-AI-098 Progress

## §E.1 Plan-phase Audit-Ready Signal

```yaml
plan_status: audit-ready
plan_complete_at: 2026-08-04
plan_auditor_verdict: PASS
plan_auditor_score: 0.92
plan_auditor_iteration: 2
plan_auditor_report: .moai/reports/plan-audit/SPEC-AI-098-review-2.md
```

## §E.2 Run-phase Evidence

**Open Question 1 결정 (spec.md §Open Questions 1, 구현 착수 전 확정 요구)**: plan.md
TASK-005의 잠정 설계(일 1회 24시간 주기 스케줄러 잡, `keyword_backfill`과 동일 패턴)를
그대로 채택했다 — 스캔 사이클마다 실행하는 대안은 REQ-AI098-004/005가 "관측"(재발
감지, 실시간 대응 아님) 목적임을 고려할 때 과도한 빈도이며, `theme_news_carry`가 오늘
막 재활성화되어 아직 "정상" 기준선 관측이 없는 상태에서는 낮은 빈도로 시작해 필요 시
빈도를 올리는 편이 리스크가 낮다고 판단했다. `scheduler.py`에
`id="theme_carry_observability"`, `hours=24`로 등록.

| AC | Status | Verification | Actual Output |
|----|--------|--------------|----------------|
| AC-098-001 | PASS | `pytest tests/test_spec_ai_098.py::TestBoundaryGuardMatching -q` | 3 passed — 조사 활용형 별칭 매칭 + `detect_theme_news_cluster()` 통합 승격(섹터 전용→60/40 블렌딩) 확인 |
| AC-098-002 | PASS | `pytest tests/test_spec_ai_098.py::TestBoundaryGuardMatching::test_ac098_002_short_alias_no_false_positive_and_case_insensitive -q` | 오탐 방지 + 영문 대소문자 무관 매칭 두 조건 모두 PASS(conjunctive) |
| AC-098-003 | PASS | `pytest tests/test_spec_ai_098.py::TestSectorOnlyScoringConfig::test_ac098_003_default_byte_equivalent_to_legacy_hardcoded_value -q` | 기본값(0.5, None)에서 `theme_cluster_score`가 레거시 하드코딩 `best_theme_base*0.5`와 `pytest.approx` 일치 |
| AC-098-004 | PASS | `pytest tests/test_spec_ai_098.py::TestSectorOnlyScoringConfig::test_ac098_004_custom_penalty_applies_only_to_sector_only_candidates -q` | `sector_only_penalty=0.3` 적용 시 섹터 전용 점수만 반영, 직접 언급 종목 무변경 |
| AC-098-005 | PASS(Should) | `pytest tests/test_spec_ai_098.py::TestSectorOnlyScoringConfig::test_ac098_005_max_candidates_truncates_sector_only_but_not_direct_mention -q` | 섹터 전용 10개+직접 언급 5개 fixture에 상한=3 → 섹터 전용 3개+직접 언급 5개(총 8개) 두 조건 모두 확인 |
| AC-098-006 | PASS | `pytest tests/test_spec_ai_098.py::TestSuggestStockNameAliasesScript -q` | 2 passed — 음역 후보 정확 식별("에스케이"→"SK") + `_STOCK_NAME_ALIASES` 무수정(JSON dump 전/후 동일) + 기등록 별칭 제외 |
| AC-098-007 | PASS | `pytest tests/test_spec_ai_098.py::TestThemeNewsCarryObservability::test_ac098_007_keyword_distribution_metrics_logged -q` | AC-AI091-009 정의 동일: full_cap_pct=50.00%, median=6.0(2건 중 [2,10]) 로그 포함 확인(`caplog`) |
| AC-098-008 | PASS | `pytest tests/test_spec_ai_098.py::TestThemeNewsCarryObservability::test_ac098_008_daily_contribution_ratio_logged -q` | `_extract_combo_key` 재사용 기여비율=50.00%(2건 중 1건) 로그 포함 확인 + 분모 0 엣지케이스 `None` 반환(ZeroDivisionError 없음) 확인 |
| AC-098-009 | PASS(Should) | `pytest tests/test_spec_ai_098.py::TestThemeNewsCarryObservability -k ac098_009 -q` | 3 passed — 임계값 초과+`TELEGRAM_ADMIN_CHAT_ID` 설정 시 `send_telegram_message` 1회 호출 확인(mock), 미설정 시 fail-open(`alert_sent=False`, 예외 없음), config=None 시 완전 스킵 |
| AC-098-010 | PASS | `git diff` 리뷰 (아래 PRESERVE 검증 참고) | `detect_theme_news_carry()`(surge_detector.py) diff 0줄, `ai_classifier.py` 미수정, `extract_theme_keywords()`/`backfill_stock_keywords()` 함수 시그니처/본문 무변경 |

**PRESERVE 목록 grep 검증 (plan.md §A.5, REQ-AI098-006)**:
```
git diff --name-only | grep ai_classifier.py   → (매치 없음, 미수정 확인)
git diff app/services/surge_detector.py | grep -c "detect_theme_news_carry" → 0 (diff hunk 내 미등장, 전파 로직 무변경)
```
코드 리뷰(plan.md §C 주의사항에 따라 자동 grep만으로 불충분 — 리뷰 병행): `detect_theme_news_carry()`(surge_detector.py:3508~), `extract_theme_keywords()`/`backfill_stock_keywords()`(keyword_tagging_service.py), `_count_keyword_matches()`(ai_classifier.py) 4개 함수 본문 라인 변경 없음 확인.

**신규 관측 함수 배치 위치 확정**: `keyword_tagging_service.py` 인접(plan.md §A.1 제안대로 — 관측 대상이 `stocks.keywords`이므로 응집도가 더 높음). `_compute_keyword_distribution_metrics`/`_compute_theme_news_carry_contribution_ratio`/`run_theme_news_carry_observability_check`/`_send_theme_news_carry_alert` 4개 함수를 파일 끝에 추가(기존 `extract_theme_keywords`/`backfill_stock_keywords`/`refresh_stock_keywords` 본문은 무수정).

**설계 정정 (Section A 자유 재량 범위 내)**: plan.md는 관측 함수가 `SurgeDetectionConfig`를 통해 임계값 설정을 받는 것으로 암묵 가정했으나, 실제로 `ThemeNewsCarryConfig`는 `SurgeDetectionConfig`의 필드가 아니라 `fund_manager.py`(L4128)가 매 호출마다 `ThemeNewsCarryConfig()`로 직접 인스턴스화하는 독립 config 클래스임을 코드 대조로 확인했다. `observability_alert_threshold` 필드를 `ThemeNewsCarryConfig`에 직접 추가하고, `run_theme_news_carry_observability_check(db, config: ThemeNewsCarryConfig | None)`으로 배선해 이 기존 관례를 따랐다(scheduler.py의 `_run_theme_news_carry_observability`도 동일하게 `ThemeNewsCarryConfig()` 인스턴스화).

**Gap (자체 발견·즉시 수정)**: Edit 도구 호출 경계 문제로 `refresh_stock_keywords()`의 `return updated` 문이 파일 끝(신규 함수들 뒤)으로 잘못 이동되어 일시적으로 무반환 상태가 된 사고가 있었다 — `test_ac005_refresh_*` 2건 실패로 발견, 원위치로 복구 후 재검증 완료(29/29 pass). PRESERVE 대상 함수의 *본문 로직*은 원래부터 무변경이었으나, 함수 경계 자체가 일시 손상되었던 점을 투명하게 기록한다.

## §E.3 Run-phase Audit-Ready Signal

```yaml
run_status: audit-ready
run_complete_at: 2026-08-04
run_commit_sha: 6f2512342cf6df4cc6f77f767b364c77bfc831da
ac_pass_count: 10
ac_fail_count: 0
preserve_list_post_run_count: 4  # extract_theme_keywords, backfill_stock_keywords, _count_keyword_matches, detect_theme_news_carry propagation
new_warnings_or_lints_introduced: false
cross_platform_build:
  applicable: false  # Python 프로젝트 — syscall/cross-platform build tag 무관
total_run_phase_files: 6  # 4 modified + 2 new (script + test)
m1_to_mN_commit_strategy: single-commit  # TASK-001~006 단일 커밋으로 통합 커밋 예정
mypy_status: unavailable  # 이 venv에 mypy 미설치 — 기존 환경 갭(SPEC-AI-098 무관, 이전 SPEC 세션 노트와 동일)
ruff_status: clean
full_regression: "2319 passed, 4 skipped, 3 xpassed, 0 failed (m -m 'not slow')"
```

## §E.4 Sync-phase Audit-Ready Signal

```yaml
sync_status: audit-ready
sync_complete_at: 2026-08-04
sync_commit_sha: b1023ab
sync_b12_self_test_a: "grep -c 'SPEC-AI-098' CHANGELOG.md before emission = 0 (no duplicate)"
sync_b12_self_test_b: "AC row count (grep -cE '^\\| AC-098-[0-9]+ \\|' acceptance.md) = 10, CHANGELOG references 10 AC (전량 10개 PASS, AC-098-005/009 Should-Pass)"
sync_b12_self_test_c: "all 6 changed-file paths verified via ls before CHANGELOG emission"
changelog_entry_position: "top of [Unreleased] (newest-first)"
frontmatter_status_transitions:
  spec_md: "in-progress -> completed"
  updated_field: "2026-08-04"
canary_compliance_check:
  applicable: false
```

**독립 재검증 (manager-docs, 오케스트레이터로부터 위임 재확인)**:

| 항목 | 검증 명령 | 결과 |
|------|-----------|------|
| SPEC-AI-098 대상 테스트 | `pytest tests/test_spec_ai_098.py tests/test_keyword_tagging_service.py -q` | 29 passed |
| 전체 회귀 | `pytest tests/ -q -m "not slow"` | 2319 passed, 4 skipped, 3 xpassed, 0 failed(run-phase 기록과 정확히 일치) |
| lint | `ruff check .` | All checks passed! |
| PRESERVE 대상 diff (전파 로직) | `git diff 3d97f4d 6f25123 -- app/services/surge_detector.py \| grep -c "detect_theme_news_carry"` | 0 |
| PRESERVE 대상 diff (ai_classifier.py) | `git diff 3d97f4d 6f25123 --name-only -- app/services/ai_classifier.py \| wc -l` | 0 (파일 자체가 diff에 등장하지 않음) |
| keyword_tagging_service.py 변경 형태 | `git diff 3d97f4d 6f25123 -- app/services/keyword_tagging_service.py` | 신규 import 2줄 + 파일 끝 신규 함수 4종 추가만 확인, 기존 `extract_theme_keywords`/`refresh_stock_keywords` 본문 무변경 |
| 사전 중복 발행 검사 | `grep -c 'SPEC-AI-098' CHANGELOG.md` (발행 전) | 0 |

**Gaps**: mypy는 이 venv에 미설치 상태로 스킵(run-phase §E.3와 동일 환경 갭, SPEC-AI-098 신규 아님). Telegram 경보 임계값(Open Question 2)과 `sector_only_max_candidates` 활성화 여부(Open Question 3)는 의도적으로 미확정 — acceptance.md §E DoD가 이를 non-blocking으로 이미 규정함.

**Residual-risk**: `theme_news_carry` 재발 감지는 재활성화 당일(오늘) 기준선 관측이 아직 없어, 관측 잡이 실제로 재발을 조기에 포착할지는 며칠간의 로그 축적 후에만 확인 가능하다(spec.md §Decisions D4).
