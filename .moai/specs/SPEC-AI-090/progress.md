# SPEC-AI-090 Progress

## §E.1 Plan-phase Audit-Ready Signal

plan_status: audit-ready
plan_complete_at: 2026-07-28
plan_auditor_verdict: PASS (score 0.95, iteration 2, Tier S threshold 0.75)

## §E.2 Run-phase Evidence

TDD RED-GREEN-REFACTOR. **본 SPEC의 run-phase 실행 범위는 M1(측정 스파이크)으로
한정된다** — M2(결정 게이트)/M3+(조건부 조정)는 spec.md "Run-phase 범위"/plan.md §A
"해소된 결정"에 따라 본 SPEC의 자율 실행 범위 밖이며, M1 완료 + 측정 리포트 제출로 본
SPEC은 유효하게 완료된다.

**M1 구현 내역**:
1. `backend/app/services/continuation_bar_measurement_service.py` (신규 모듈, 읽기
   전용 파생 계산) — `classify_continuation_outcome()`(순수 함수, REQ-002) +
   `measure_continuation_detector_bars()`(REQ-003, 읽기 전용 DB 쿼리). 기존
   `detect_momentum_continuation`/`detect_near_limit_up_carries`/
   `compute_ensemble_score`/`evaluate_detector_contribution`을 임포트·호출·수정하지
   않는다(REQ-AI090-004 [HARD]) — solo attribution 로직만 독립적으로 재현.
2. `backend/tests/test_spec_ai_090.py` (신규, 22개 테스트) — AC-090-002/003 커버,
   신규 모듈 100% 커버리지.
3. `.moai/reports/continuation-detector-eval-bar/2026-07-28.md` — M1 측정 리포트
   (REQ-001 재현 검증 원본 쿼리+출력, REQ-003 4-기준 hit-rate 표, 방법론 잔여위험
   포함, 프로덕션 DB 직접 조회 근거).

**M1 측정 핵심 결과** (상세는 리포트 원본 참고):
- REQ-001 재현: §Context 표의 momentum_continuation emission_count/solo_tp 5/5
  날짜 전부 정확 일치. surge_prediction_evaluation 예시(07-27)도 정확 일치.
  **재현 성공** — SPEC 전제 유효.
- REQ-001 확장 발견: momentum_continuation의 solo_count는 관측 구간(07-20~07-27)
  5일 전부 0 — 단 한 번도 단독 발동하지 않음.
- REQ-003 momentum_continuation: solo 시그널 0건 → **4-기준 재채점 측정 불가**
  (AC-090-003의 "solo_count>0인 날짜 최소 3일" 요건 미달, valid/expected outcome).
- REQ-003 near_limit_up_carry: solo 시그널 35건(4개 표본일). hit-rate — 기존
  was_surge 2.86% → 기준B(미반전) 28.57% → 기준C@3% 17.14% → 기준C@5% 11.43%.
  **완화 기준이 기존 기준보다 유의미하게 높은 성공률을 보임** — 가설 1을 이
  탐지기에 대해 실증 지지.
- 방법론 잔여위험: `FundSignal.created_at` 가변성(재탐지 시 갱신)으로 인해
  near_limit_up_carry 재현 표본이 원본 스냅샷(38건) 대비 3건(7.9%) 결측 — 원인
  규명 완료(fund_manager.py/disclosure_impact_scorer.py 재탐지 UPDATE 경로),
  SPEC-AI-070 attribution 설계의 기존 구조적 한계이며 본 SPEC이 새로 도입한
  결함 아님.

| AC | REQ | Status | Actual Output |
|----|-----|--------|----------------|
| AC-090-001 | REQ-001 | PASS | 리포트 §1 — momentum_continuation emission_count/solo_tp 5/5 `run_date` 완전 일치 + 원본 쿼리/출력 기록. surge_prediction_evaluation 07-27 예시 정확 일치. 재현 여부 명시적 판정("재현 성공"). |
| AC-090-002 | REQ-002 | PASS | `TestClassifyContinuationOutcome`(7개 테스트) 전량 PASS — 순수 함수 결정성(동일 입력 5회 호출 동일 결과), 경계값(threshold와 정확히 같을 때 success), 측정불가 2가지 분기(T당일 관측치 없음/T-1 변화율 비양수) 검증. 임계값 3종 모두 명명된 상수(`BAR_B_FLOOR_THRESHOLD_PCT`/`BAR_C_GAIN_THRESHOLD_LOW_PCT`/`BAR_C_GAIN_THRESHOLD_HIGH_PCT`)로 하드코딩 없이 존재. |
| AC-090-003 | REQ-003 | PASS-WITH-DEBT | near_limit_up_carry: 표본 4일(≥3일 충족)·35건 solo 시그널에 대해 4-기준(was_surge/기준B/기준C@3%/기준C@5%) hit-rate 전부 산출, 측정불가 0건(분모 명시). momentum_continuation: 표본 거래일 5일 전부 solo_count=0으로 최소 3일 요건 미달 — spec.md §G/B11에 따라 유효한 결과로 리포트 §3.1/§5에 명시적 기록(차단 아님). "PASS-WITH-DEBT" 표시 사유: AC 문언상 요구하는 "탐지기별로... 4개 hit-rate 값을 산출"이 momentum_continuation에서는 표본 부족으로 산출 불가능함을 리포트에 정직하게 반영했기 때문(수치를 임의로 채우지 않음). |
| AC-090-004 [HARD] | REQ-004 | PASS | §D 사전 점검 3커맨드 재실행 결과 M1 이전과 100% 동일(아래 회귀 근거). `surge_detection.yaml`/`surge_detector_contribution` upsert 경로 diff 0(코드 미수정 — `git status --porcelain`으로 기존 파일 변경 없음 확인). |
| AC-090-005 | REQ-005 | PASS | M1 완료 시점까지 어떤 탐지기 파라미터·앙상블 가중치·평가 정의 변경 커밋도 생성하지 않음 — 본 M1 커밋은 신규 파일 3종(모듈/테스트/리포트) + progress.md/spec.md frontmatter 전이만 포함. M2 AskUserQuestion 라운드는 오케스트레이터가 별도 진행. |
| AC-090-006 | REQ-006 | PASS | `logger.info("[continuation_bar_measurement] 표본 거래일=%d개, 탐지기=%s 측정 완료", ...)` 단일 로그 라인(measure_continuation_detector_bars 말미) — 표본 수·탐지기 목록 포함. `alembic`/마이그레이션 diff 0(신규 마이그레이션 파일 없음, `git status --porcelain`으로 확인). |
| 기존 회귀 테스트(§D pre-flight) | — | PASS | `uv run pytest tests/test_spec_ai_070.py tests/test_near_limit_up_carry.py tests/test_surge_evaluation_service.py -q -m "not slow"` → **117 passed**(M1 전/후 동일). `uv run pytest tests/test_surge_detector.py -q -m "not slow" -k "ensemble or weight"` → **6 passed**(M1 전/후 동일). |

**신규 테스트 커버리지**: `uv run pytest tests/test_spec_ai_090.py -q -m "not slow" --cov=app.services.continuation_bar_measurement_service --cov-report=term-missing` → **22 passed, 100% coverage**(110/110 statements).

**Lint**: `uv run ruff check app/services/continuation_bar_measurement_service.py tests/test_spec_ai_090.py` → **All checks passed**.
**mypy**: `uv run mypy app/services/continuation_bar_measurement_service.py` → `Failed to spawn: mypy — program not found` — 기존 환경 갭(SPEC-AI-087/088/089 §E.2와 동일, 본 SPEC 도입 아님, 미해결 기록만 유지).

## §E.3 Run-phase Audit-Ready Signal

run_status: complete (M1 범위 한정 — M2/M3+는 본 SPEC 자율 실행 범위 밖)
run_complete_at: "2026-07-28"
run_commit_sha: "22cb6622d1e193a9b0ed37d90a8efd8eef523fb1"
ac_pass_count: 5 (1건 PASS-WITH-DEBT 포함 — AC-090-003, 표본 부족을 정직하게 기록한 것이 사유)
ac_fail_count: 0
preserve_list_post_run_count: 5 (surge_detector.py, surge_settings.py, surge_detection.yaml, surge_contribution_service.py, surge_detector_contribution 테이블 upsert 경로 — 전부 무변경)
l44_pre_commit_fetch: "N/A — Route A Hybrid Trunk main-direct, no PR"
l44_post_push_fetch: "N/A — Route A Hybrid Trunk main-direct, no PR"
new_warnings_or_lints_introduced: 0
cross_platform_build: "N/A — Python backend, no cross-platform build tags applicable"
total_run_phase_files: 5 (신규 모듈 1 + 신규 테스트 1 + 신규 리포트 1 + progress.md 신규 1 + spec.md frontmatter 전이 1)
m1_to_mN_commit_strategy: "M1 단일 통합 커밋(구현+테스트+리포트) + 후속 progress.md run_commit_sha backfill 커밋, Tier S Hybrid Trunk main-direct(spec.md Run-phase 범위/plan.md §A 결정에 따라 M1만 자율 실행 범위 — M2/M3+는 별도 AskUserQuestion 게이트)"

## §E.4 Sync-phase Audit-Ready Signal

_<본 SPEC은 M1 완료로 유효하게 종료된다 — M2(결정 게이트)는 orchestrator가 별도
AskUserQuestion 라운드로 진행하며, M2 승인 범위에 따라 sync-phase 진행 여부가
결정된다(plan.md §A/§C 참고). 현재는 sync-phase 대기 아님 — M1 단독 완료 상태.>_
