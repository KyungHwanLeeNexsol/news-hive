# SPEC-AI-089 Progress

## §E.1 Plan-phase Audit-Ready Signal

plan_status: audit-ready
plan_complete_at: 2026-07-27

## §E.2 Run-phase Evidence

DDD ANALYZE-PRESERVE-IMPROVE. **본 SPEC의 run-phase 실행 범위는 M1(측정 스파이크)으로
한정된다** — M2(결정 게이트)/M3+(조건부 배선)는 plan.md §A "해소된 결정"에 따라 본
SPEC의 자율 실행 범위 밖이며, M1 완료 + 측정 리포트 제출로 본 SPEC은 유효하게
완료된다(acceptance.md Definition of Done).

**M1 구현 내역**:
1. `app/surge_config/surge_settings.py` — `SurgeDetectionConfig.universe_gap_measurement_enabled: bool = False` 신규 플래그(기본 비활성).
2. `app/services/surge_universe_gap_service.py` (신규 모듈) — `measure_universe_detection_gap()`(순수 함수, REQ-001) + `analyze_no_signal_pool_attribution()`(REQ-002, 오프라인 분석).
3. `app/services/surge_detector.py` `gather_surge_candidates()` — 플래그 게이팅된 계측 훅 추가(기존 `persist_pool_counts`/`persist_universe_members` try 블록 직후, `merged` 딕셔너리 절대 미변경 — REQ-003 [HARD]). `import time` 추가(소요시간 측정).
4. `backend/tests/test_spec_ai_089.py` (신규, 15개 테스트) — AC-089-001~008 전량 커버.
5. `backend/scripts/measure_universe_detection_gap_report.py` (신규) — REQ-002 리포트 재현 스크립트.
6. `.moai/reports/surge-universe-gap/2026-07-27.md` — M1 측정 리포트(연구 질문 1-3 실측 답 포함, 프로덕션 DB 15개 표본 거래일 read-only 조회 근거).

**M1 측정 핵심 결과** (상세는 리포트 원본 참고):
- 15개 표본 거래일(2026-07-03~2026-07-27) 합산: 실제 급등 885건 중 무시그널 751건(84.9%).
- 무시그널 종목의 T-1 스캔 유니버스 귀속: absent(소스 부재형) 83.1%, pool_a 5.7%,
  pool_b 3.6%, pool_c 7.6% — 유니버스 배선(옵션 A/B/C)의 이론적 상한은 16.9%.
- 연구 질문 1(Pool A 중복도): Pool A raw 1,160건 중 disclosure_impact/preday_disclosure
  시그널과 겹침 36.7% — 63.3% 순미탐지.
- 연구 질문 2(Pool B 중복도): Pool B raw 142건 중 임의 시그널과 겹침 16.2% —
  83.8% 순미탐지(표본 4일, 신뢰도 낮음).
- 연구 질문 3(69% 서술 재검증): 확대 표본에서 83.1%로 재확인(더 나쁨).

| AC | REQ | Status | Actual Output |
|----|-----|--------|----------------|
| AC-089-001 | REQ-001 | PASS | `TestMeasureUniverseDetectionGap`(6개 테스트) PASS — 시나리오1(A=3/covered=1, B=2/covered=0) 정확 산출 + 4개 엣지케이스(전체 풀 공집합/merged 공집합/미매핑 코드/Pool D 포함) 통과. |
| AC-089-002 | REQ-002 | PASS | `test_flag_off_matches_empty_detector_baseline` PASS — 계측 비활성(기본값) 시 `gather_surge_candidates()` 출력이 빈 후보(기존 baseline과 동일, test_spec_ai_086 패턴과 동형). |
| AC-089-003 | REQ-002 | PASS | `TestNoSignalPoolAttribution`(3개 테스트) PASS — 시나리오3(4가지 풀 귀속 a/b/c/absent) 정확 분류 + 시그널 보유 종목 제외 확인 + 표본 데이터 없음 명시적 기록(sample_present=False) 확인. |
| AC-089-004 [HARD, PASS-WITH-DEBT] | REQ-004 | PASS-WITH-DEBT | 코드 구조 증거: `measure_universe_detection_gap`은 Session 인자가 없는 순수 함수(`test_no_new_db_writes`로 시그니처 고정), 기존에 이미 지불하던 `build_scan_universe`/persist 호출 **이후** 인메모리 집합 연산 + 로그 1줄만 추가. **갭**: 활성/비활성 상태의 실제 소요시간 A/B 비교(5% 이내 증가 + 1080초 이하)는 프로덕션 스케줄 잡 실행이 필요해 이번 세션에서 실측하지 못함(M1 리포트 §5에 명시적으로 고지) — M2 이전 프로덕션 1회 실측 권고. |
| AC-089-005 | REQ-005 | PASS | 커밋 이력 검토 — M1 커밋에 8개 1차 탐지기 함수 본체(`detect_theme_news_cluster` 등) 수정 없음. 정적 테스트 `test_measurement_hook_never_mutates_merged`로 훅 코드가 `merged[`/`merged.update`/`merged =` 패턴을 포함하지 않음을 추가 확인(test_spec_ai_086 C4 패턴 계승). |
| AC-089-006 | REQ-006 | PASS | `TestEnsembleWeightInvariantUnchanged`(2개 테스트) PASS — 신규 플래그 추가 후에도 `validate_ensemble_weights`(8개 탐지기 가중치 합=1.0) 불변식 유지, 플래그 기본값 False 확인. |
| AC-089-007 | REQ-007 | PASS | `test_single_log_line_with_pool_summary_no_per_stock_detail` PASS — caplog로 `[유니버스간극측정]` 로그가 정확히 1줄, 실행 상태·소요시간·풀별 raw/covered 포함, 종목코드(005930) 미노출 확인. |
| AC-089-008 [HARD] | REQ-003 | PASS | `test_flag_on_vs_off_produces_identical_qualified_candidates` PASS — 동일 fixture(theme+combo 앙상블 통과 후보 1건)에 대해 계측 ON/OFF 두 실행의 `SurgeCandidate` 목록이 `==`로 완전 일치(diff 없음). REQ-AI089-003 ACTIVE-state 불변식 실측 확인. |
| 기존 회귀 테스트 전체 통과 | — | PASS | `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"` → **2160 passed, 4 skipped, 3 xpassed, 0 failed** (실행 시각 2026-07-27, 104.73s). 신규 테스트 15개(test_spec_ai_089.py) 포함. |

**추가 타겟 회귀(plan.md §D)**:
- `tests/test_surge_universe_members.py tests/test_surge_universe_pool_bugfix.py tests/test_surge_evaluation_service.py -q -m "not slow"` → **64 passed**.
- `tests/test_surge_detector.py -q -m "not slow" -k "universe or scan_universe"` → **0 selected(exit 5)** — 해당 파일에는 이 키워드로 매칭되는 테스트가 pre-existing으로 없음(유니버스 회귀 커버리지는 위 커맨드의 test_spec_ai_086.py/test_surge_universe_members.py가 실질 담당). 본 SPEC이 유발한 변화 아님.

**Lint**: `uv run ruff check .` (전체 backend) → **All checks passed**.
**mypy**: `uv run mypy app/` → `Failed to spawn: mypy — program not found` — SPEC-AI-087/088 §E.2와 동일한 기존 환경 갭(본 SPEC 도입 아님, 미해결 기록만 유지).

## §E.3 Run-phase Audit-Ready Signal

run_status: complete (M1 범위 한정 — M2/M3+는 본 SPEC 자율 실행 범위 밖)
run_complete_at: "2026-07-27"
run_commit_sha: "a57c31abaaad2df7972fe24609d22d481ffa9864"
ac_pass_count: 8
ac_fail_count: 0
preserve_list_post_run_count: 1
l44_pre_commit_fetch: "N/A — Route A Hybrid Trunk main-direct, no PR"
l44_post_push_fetch: "N/A — Route A Hybrid Trunk main-direct, no PR"
new_warnings_or_lints_introduced: 0
cross_platform_build: "N/A — Python backend, no cross-platform build tags applicable"
total_run_phase_files: 6
m1_to_mN_commit_strategy: "M1 단일 통합 커밋(구현+테스트+리포트+스크립트) + 후속 progress.md/status backfill 커밋, Tier L Hybrid Trunk main-direct(§A 결정에 따라 M1만 자율 실행 범위 — M2/M3+는 별도 AskUserQuestion 게이트)"

## §E.4 Sync-phase Audit-Ready Signal

sync_status: complete (M1 범위 한정 — M2 결정 게이트는 본 SPEC의 sync-phase 범위 밖, orchestrator가 별도 AskUserQuestion 라운드로 진행)
sync_complete_at: "2026-07-30"
sync_commit_sha: "f940a47"

M1 완료 + 측정 리포트 제출로 본 SPEC은 유효하게 완료되었다(acceptance.md Definition of
Done). sync-phase는 CHANGELOG 엔트리 추가 + spec.md frontmatter `completed` 전환만
수행한다 — plan.md/acceptance.md는 YAML frontmatter를 보유하지 않아 전환 대상이 아니다.
M2(배선 방식 결정)는 sync-phase 완료 이후 orchestrator가 별도로 진행한다.
