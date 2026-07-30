# SPEC-AI-092 Progress

## §E.1 Plan-phase Audit-Ready Signal

plan_status: draft
plan_created_at: "2026-07-28"
plan_scope: "급등 예측 재현율 회복을 위한 평가 기록 안정화, 평가 스냅샷, 스캔 유니버스 bridge 후보화, adaptive threshold 연결성, 운영 누락 감시"
plan_sync_note: "2026-07-29: 기존 완료 SPEC-AI-090과 번호 충돌을 피하기 위해 SPEC-AI-092로 재번호화"

## §E.2 Run-phase Evidence

현재 run-phase는 시작하지 않았다. 다만 본 SPEC 작성 직전 운영 P0/P1 긴급 조치로 다음 변경은 이미
작업트리에 존재한다.

### 선행 긴급 조치

1. 운영 DB `2026-07-28` actual/evaluation 수동 복구.
2. `backend/app/routers/surge_trading.py` — `/prediction-history` 평가 완료 row의
   `predicted_count`를 stored metric으로 반환하도록 수정.
3. `backend/tests/test_surge_eval_endpoints.py` — `FundSignal.created_at` drift fixture 회귀 테스트 추가.
4. `backend/docs/spec-ai-092-surge-prediction-recall-recovery.md` — 운영 분석 기반 구현 brief 작성.

### 선행 검증

```text
backend/tests/test_surge_eval_endpoints.py: 10 passed
backend/tests/test_spec_ai_088.py: 34 passed
git diff --check: 통과
```

## §E.2b Run-phase 착수 근거 (2026-07-30 조사)

2026-07-29(T) 급등예측 미스 원인을 프로덕션 DB 직접 조회로 재확인했다.

- 07-29 평가: predicted=6, actual=15, TP=0, precision/recall=0%, coverage=6.67%.
- 실제 급등 15종목 중 14종목이 로봇테마(엔젤로보틱스 +29.87%, 티엑스알로보틱스 +24.62%,
  나우로보틱스 +18.33% 등) 단일 랠리였고 전부 `non_scannable`(T-1 스캔 유니버스 밖).
- T-1(07-28) 표준 예측셋(5~6종목)은 실제 급등주와 전혀 겹치지 않음. near_limit_up_carry가
  로봇 3종목을 포착했으나 생성 시각이 07-29 마감 이후(07-30 예측용)라 07-29 평가엔 무관(SPEC-AI-075
  지평 설계와 일치, 버그 아님).
- Pool B(거래량200%+)는 운영 로그상 07-29 장중 내내 정상 작동(10~42종목)했으나, 평가에 박제된
  `pool_b_count=0`은 프리마켓 스냅샷 값이며 멤버십 미영속화로 사후 재구성 불가(SPEC-AI-086 R-1
  기존 문서화된 한계, 신규 버그 아님).

**SPEC-AI-092 범위와의 관계(정직한 한계 표기)**: TASK-004 bridge 후보화는 "스캔 유니버스에는
있었지만 merged에 승격 안 된 종목"을 구제하는 메커니즘이다. 그러나 07-29 미스의 14/15는 애초에
Pool A/B/C 어디에도 없던(`non_scannable`) 종목이므로, bridge 후보화만으로는 07-29 같은 사례의
recall을 직접 개선하지 못한다. 이번 조사는 TASK-004의 필요성을 부정하지 않지만(Pool C 소속인데
승격 안 된 종목은 여전히 존재할 수 있음), "당일 신규 점화 테마" cold-start 문제는 본 SPEC
Non-Goals에 명시된 대로 범위 밖으로 남는다 — 별도 후속 SPEC 후보로 기록.

## §E.2c Run-phase Evidence — TASK-002~006 (2026-07-30)

TASK-001은 이미 완료 상태였다(위 §E.2 참조). 이번 run-phase에서 TASK-002~006을
구현했다.

### 구현 요약

- **TASK-002**: `surge_prediction_evaluation.predicted_codes_json` 컬럼 추가
  (alembic `069_surge_prediction_evaluation_snapshot.py`). `evaluate_surge_predictions()`가
  평가 당시 공식 predicted set(near-limit carry/same-day horizon 배제 이후)을 JSON
  배열로 스냅샷 저장. `restore_predicted_codes()` 헬퍼로 복원. `/evaluation/{date}`와
  `/prediction-history` 응답에 `predicted_codes` 필드를 추가(기존 필드는 하위호환 유지).
- **TASK-003**: `SurgeDetectionConfig`에 `scan_universe_bridge_candidates_enabled(기본
  False)`, `scan_universe_bridge_max_candidates(기본 20)`,
  `scan_universe_bridge_pool_limits(기본 {"pool_a":10,"pool_c":10})` 3개 필드 추가.
- **TASK-004**: `surge_detector.generate_scan_universe_bridge_candidates()` 신규 함수.
  `build_scan_universe()`가 이미 조회한 pool_a/pool_c 종목 중 `merged`에 없는 종목을
  이미 수집된 DB 자료(Disclosure.impact_score, SurgeActualOutcome.change_rate)만으로
  점수화하여 bridge 후보로 승격. `SurgeCandidate.bridge_score` 필드 추가(앙상블 가중치
  합산에는 미포함). `bypass_composite_score` 경로로 downstream(품질floor 포함)을
  기존 volume_breakout bypass와 동일하게 통과. `gather_surge_candidates()`의 qualified
  합류 지점 한 곳에서만 병합(merged는 절대 변경 안 함).
- **TASK-005**: 조사 결과 적응형 임계값(`compute_adaptive_threshold`/
  `get_today_threshold`)은 이미 매수 실행 gate(`surge_trading_service.execute_buy_orders`)
  전용으로 올바르게 배선되어 있었고, 예측 생성 gate(`gather_surge_candidates`의
  `effective_threshold`)와는 애초에 무관했다(코드에 `surge_threshold_service` import
  자체가 없음). 배선 변경은 하지 않고, 두 게이트가 이미 설정명/로그명이 분리되어
  있음을 양쪽 모듈에 명시 주석으로 교차 참조 추가(AC-092-006 execution-only 분기).
- **TASK-006**: `surge_evaluation_service.detect_missing_evaluation_records()`(순수
  읽기, idempotent) + `check_and_alert_missing_evaluation()`(누락 시 텔레그램 admin
  경보, `TELEGRAM_ADMIN_CHAT_ID` 미설정 시 warning log로 fail-open) 추가. 스케줄러에
  평일 19:15 KST 잡(`surge_missing_evaluation_check`, verify_predictions 18:30 ~
  detector_contribution 19:05 이후) 등록. REQ-AI092-006의 "untracked mover 방어"
  조건은 SPEC-AI-071이 이미 `collect_daily_surge_outcomes()`에서 `stocks` 테이블
  교집합 필터로 구현해 두었음을 확인(신규 코드 불필요).

### TASK-002/TASK-005 설계 판단 근거

- **TASK-002(JSON 컬럼 vs 별도 테이블)**: JSON 컬럼(`predicted_codes_json`)을 선택했다.
  본 SPEC은 첫 스냅샷 메커니즘이라 따를 기존 패턴이 없고, Tier M의 최소 풋프린트
  원칙(신규 외부 fetch 없음, 기존 DB/인메모리 자료만 사용) 및 plan.md §A의 "평가
  스냅샷은 bridge 후보화보다 먼저, API 표시 안정성/디버깅 재현성 목적으로 설계"
  방향과 부합한다. 상세 신호 분석/조인이 필요해지면 후속 SPEC에서 별도 테이블로
  이관 가능(마이그레이션 경로 열려 있음).
- **TASK-005(threshold 연결)**: 위 요약 참조. 강제 배선은 precision/recall 안정성
  리스크(plan.md §D 롤백 기준)에 비해 이득이 불명확했고, 조사 결과 이미 올바르게
  분리되어 있어 "생성 gate에 연결" 변경은 불필요하다고 판단했다.

### 검증 근거

```text
$ uv run pytest tests/test_spec_ai_092.py -q
20 passed

$ uv run pytest tests/test_surge_eval_endpoints.py tests/test_spec_ai_088.py \
    tests/test_spec_ai_089.py tests/test_surge_evaluation_service.py \
    tests/test_spec_ai_092.py -q
128 passed

$ uv run pytest tests/ --tb=short -q -m "not slow"
2226 passed, 4 skipped, 3 xpassed

$ uv run ruff check .
All checks passed!

$ uv run python -c "from app.main import app; print('OK')"
OK
```

### AC PASS/FAIL 매트릭스

| AC | 상태 | 근거 |
|----|------|------|
| AC-092-001 | PASS (기완료) | test_surge_eval_endpoints.py::TestGetPredictionHistory |
| AC-092-002 | PASS | test_spec_ai_092.py::TestPredictedCodesSnapshot (4 tests) |
| AC-092-003 | PASS | test_spec_ai_092.py::TestBridgeFlagOff + 전체회귀 무변화 |
| AC-092-004 | PASS | test_spec_ai_092.py::TestBridgeCandidateGeneration (4 tests, 시나리오 8 포함) |
| AC-092-005 | PASS | test_spec_ai_092.py::test_generate_bridge_candidates_no_new_external_fetch |
| AC-092-006 | PASS | test_spec_ai_092.py::TestAdaptiveThresholdConnectivity (3 tests) |
| AC-092-007 | PASS | test_spec_ai_092.py::TestMissingEvaluationMonitor (4 tests) |
| AC-092-008 | PASS | test_spec_ai_092.py::TestBridgeSameDayExclusion (2 tests) |

### Gaps / Residual-risk

- bridge 후보화는 flag 기본 OFF로 배포되므로, 실제 coverage/precision 개선 효과는
  운영 활성화 후에만 관측 가능하다(plan.md §D 롤백 기준 그대로 유효).
- Pool D(뉴스 언급 기반) bridge scoring은 이번 구현 범위에 포함하지 않았다(plan.md
  §B TASK-004는 "권장"이며 Pool D는 기본적으로 `pool_d_min_slots=0`으로 비활성이라
  bridge 후보 대상 풀에도 거의 등장하지 않는다) — 필요 시 후속 확장 가능.
- `_BRIDGE_MIN_SCORE=0.3` 임계값은 SPEC이 명시적 수치를 요구하지 않아 함수 내부
  상수로 정했다 — 운영 관측 후 조정 필요할 수 있다.

## §F Phase 4 Mode Selection

- **입력**: tier=M, scope=~5 files (surge_settings.py, surge_evaluation_service.py, surge_detector.py, surge_trading.py 라우터, backend/alembic 마이그레이션 1건), domain 수=1(backend Python 서비스 단일 영역), 파일 언어=100% Python, concurrency benefit=LOW(coding-heavy, Anthropic coding-task parallelism caveat 해당).
- **평가**: Mode 1(trivial) 미해당 — 비자명 구현. Mode 2(background) 미해당 — 코드 변경 포함. Mode 3(agent-team) RETIRED. Mode 4(parallel) 미해당 — 단일 도메인 coding-heavy. Mode 6(workflow) 미해당 — 30+ 파일 기계적 변환 아님, 의미론적 신규 구현.
- **Decision: sub-agent** (Mode 5)
- **근거**: Tier M coding-heavy 단일 도메인 작업은 Anthropic 권고에 따라 순차 sub-agent 위임이 기본값. TASK-002~006을 하나의 manager-develop 위임(Section A-E 템플릿)으로 순차 milestone 커밋(각 TASK=1 커밋, Route A main-direct)으로 진행.

## §E.3 Run-phase Audit-Ready Signal

run_status: implemented
run_complete_at: "2026-07-30"
run_commit_sha: 93dafed8bf5ecc0954e6325a743cb171d1728538
ac_pass_count: 8
ac_fail_count: 0

## §E.4 Sync-phase Audit-Ready Signal

sync_status: completed
sync_complete_at: "2026-07-30"
sync_commit_sha: e17d30a

이번 sync에서 CHANGELOG.md 항목 추가, spec.md frontmatter `in-progress → completed` 전환,
progress.md §E.4 갱신을 수행했다. MX 태그(`@MX:NOTE`)는 run-phase에서 이미
`generate_scan_universe_bridge_candidates()`, `detect_missing_evaluation_records()`,
`check_and_alert_missing_evaluation()`에 부여되어 있음을 확인했다 — 추가 태깅 불필요.

DB 스키마 문서(`​.moai/project/db/schema.md` 등) 자동 동기화는 `db.yaml`의
`require_user_approval: true` 설정에 따라 자동 실행하지 않았다. 이번 SPEC은
`backend/alembic/versions/069_surge_prediction_evaluation_snapshot.py`로 nullable
`predicted_codes_json` TEXT 컬럼을 추가했다(순수 additive, non-breaking) — 사용자가
`moai hook db-schema-sync`를 수동 실행하거나 승인하는 것을 권장한다.

- `.moai/specs/SPEC-AI-092/spec.md`
- `.moai/specs/SPEC-AI-092/plan.md`
- `.moai/specs/SPEC-AI-092/acceptance.md`
- `.moai/specs/SPEC-AI-092/research.md`
- `.moai/specs/SPEC-AI-092/progress.md`
- `CHANGELOG.md`
