# SPEC-AI-101 Plan

## A. 구현 전략

Tier L, cycle_type: ddd(ANALYZE-PRESERVE-IMPROVE — `quality.yaml`
`constitution.development_mode`에 따름). 되돌리기 어려운 결정(신규 테이블 스키마,
`run_horizon_shadow_comparison` 시그니처 확장)을 먼저 확정하고, 기계적 배선(config
플래그 전환, 판정 함수)은 뒤로 미룬다.

핵심 판단:

- 두 서브시스템(라벨 / 섀도우 관측)은 서로 독립이며 병렬로 구현 가능하다 — 단, 섀도우
  관측 내부에서는 영속화(TASK-004)가 config 플래그 전환(TASK-005)보다 반드시 먼저
  적용되어야 한다(design.md §E).
- `SurgeActualOutcome`, `compute_ensemble_score`, `compute_horizon_signature`,
  `select_effective_threshold`, `_is_near_limit_up_carry_signal`,
  `_is_same_day_event_horizon_signal`, 표준 T-1→T recall/precision/coverage 산출 로직은
  **어느 TASK도 수정하지 않는다** — 이 SPEC의 위험은 순수 additive 확장으로 완화된다.

### A.1 PRESERVE 목록 (수정 금지)

| 대상 | 사유 |
|------|------|
| `SurgeActualOutcome` 컬럼/PK | D1 — 파괴적 재정의 기각, 동결 |
| `evaluate_surge_predictions()`의 `predicted_set`/`actual_set`/`legacy_recall`/`scannable_recall`/`coverage` 산출 로직 | REQ-AI101-002 필수 조건 — 무수정 |
| `_is_near_limit_up_carry_signal`, `_is_same_day_event_horizon_signal` | SPEC-AI-075/080 소유, 재구현 금지 |
| `compute_ensemble_score`, `compute_horizon_signature`, `select_effective_threshold`의 판정 로직 본체 | D4 — 순수 관측 채널 확장만 허용 |
| `high_based_recall/precision/coverage`(SPEC-AI-095) 계산 블록 | 무관 — 독립된 병렬 지표, 본 SPEC이 추가하는 신규 지표와 나란히 공존 |

## B. 작업 분해

### TASK-001: 신규 테이블 `SurgeSignalForwardOutcome` + 마이그레이션 (REQ-AI101-001)

- 대상: `backend/app/models/surge_signal_forward_outcome.py`(신규), alembic 마이그레이션 1개
- design.md §C 초안 스키마로 신규 모델 정의. `(trading_date, fund_signal_id)` UNIQUE
  제약, upsert 패턴은 `surge_actual_outcome_service.py`의 기존 upsert 관례를 재사용.
- Open Question 1(정확한 PK/컬럼명)을 `FundSignal.id` 인덱스 관례 확인 후 확정.
- Open Question 2(`price_at_signal` 실측 채움률)을 프로덕션 DB 쿼리로 도메인 검증 —
  채움률이 극단적으로 낮으면(예: <10%) plan-auditor 재감사 전 오케스트레이터에게
  블로커 보고.

추적: REQ-AI101-001 / AC-101-001, AC-101-002

### TASK-002: 신호 단위 forward-return 계산 서비스 함수 (REQ-AI101-001)

- 대상: `backend/app/services/surge_evaluation_service.py`(신규 헬퍼 함수) 또는
  `surge_actual_outcome_service.py`(가격 조회 재사용 위치에 따라 결정)
- design.md §B.1 계산식 구현: `day_high_price`, `forward_max_return_pct`.
  `fetch_stock_price_history_sync`(SPEC-AI-072 날짜 매칭 패턴) 재사용.
- NULL 안전 처리(price_at_signal NULL, T-1 종가 조회 실패) — 예외를 던지지 않고 파생값만
  NULL.

추적: REQ-AI101-001 / AC-101-001, AC-101-003

### TASK-003: `evaluate_surge_predictions()` 병렬 지표 통합 (REQ-AI101-002)

- 대상: `backend/app/services/surge_evaluation_service.py`(`:858` 부근, `high_based_*`
  블록과 나란히 신규 블록 추가)
- design.md §D 통합 지점에 따라 `forward_based_recall/precision`을 산출하고
  `SurgePredictionEvaluation` 반환 객체에 노출(신규 컬럼 또는 SPEC-AI-086
  `scannable_denominator_expanded` 선례처럼 비영속 런타임 속성 — 구현 시 결정).
- try/except + `db.rollback()` 격리(SPEC-AI-095 패턴 재사용).

추적: REQ-AI101-002 / AC-101-004, AC-101-005

### TASK-004: `run_horizon_shadow_comparison` 영속화 확장 (REQ-AI101-004)

- 대상: `backend/app/services/surge_detector.py`(`:1731` 함수 본문 + `:2561` 호출부)
- design.md §F에 따라 `db: Session | None = None` 인자 추가, 무조건(변화 유무 무관) 1행
  적재. 기존 `logger.info` 로그 블록은 그대로 유지.
- 신규 테이블 `SurgeHorizonShadowObservation` 모델 + 마이그레이션(TASK-004a).
- 영속화 실패를 기존 `except Exception as shadow_exc:` 블록에 포함(REQ-AI100-007 재사용).

추적: REQ-AI101-004 / AC-101-006, AC-101-007, AC-101-008

### TASK-005: 섀도우 관측 활성화 (REQ-AI101-003)

- 대상: `backend/app/surge_config/surge_detection.yaml`
- **TASK-004 완료 후에만 적용**(design.md §E 순서 제약). `shadow_mode_enabled: false → true`.
  `enabled`는 무수정.

추적: REQ-AI101-003 / AC-101-009

### TASK-006: 전환 게이트 3요건 판정 함수 (REQ-AI101-005)

- 대상: `backend/app/services/surge_detector.py` 또는 신규
  `surge_horizon_readiness_service.py`
- design.md §G `check_horizon_transition_readiness(db)` 구현. `enabled` 플래그 자동
  전환 코드는 어디에도 두지 않는다(D5, REQ-AI101-005 필수 조건 — grep 검증 대상).

추적: REQ-AI101-005 / AC-101-010, AC-101-011

### TASK-007: 무회귀·신규 검증

- 대상: 신규 `backend/tests/test_spec_ai_101.py`
- 케이스: (a) `price_at_signal`/T-1 종가 조회 성공/실패 각각의 `forward_max_return_pct`
  계산 정확성 및 NULL 안전성, (b) 신규 테이블 upsert 멱등성(평가 잡 재실행),
  (c) `evaluate_surge_predictions()` 표준 경로(legacy/scannable recall) 무변경
  characterization test, (d) `run_horizon_shadow_comparison` 영속화가 변화 없는 날에도
  1행을 적재하는지, (e) 영속화 예외가 기존 섀도우 로깅/시그널 생성 흐름을 막지 않는지,
  (f) `check_horizon_transition_readiness`가 3요건 값을 정확히 집계하는지(레짐 3종
  fixture), (g) `enabled` 플래그 자동 전환 코드가 없음을 grep으로 확인.
- 기존 테스트(`test_spec_ai_095.py`, `test_spec_ai_100.py`, `test_surge_evaluation_service.py`류,
  실제 파일명은 구현 시 `ls backend/tests/`로 재확인) 전체 무수정 통과 확인.

추적: REQ-AI101-001~006 전체 / AC-101-001~012

## C. 검증 계획

타겟 테스트:

```powershell
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests\test_spec_ai_101.py -q
```

전체 회귀:

```powershell
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests -q -m "not slow"
```

정적 검사:

```powershell
.\backend\.venv\Scripts\ruff.exe check .\backend
.\backend\.venv\Scripts\python.exe -m mypy .\backend\app
```

범위 규율 grep (기존 검증된 로직 무변경 확인, REQ-AI101-002/AC-101-005):

```bash
git diff backend/app/services/surge_evaluation_service.py -- :^backend/tests
# 기대: predicted_set/actual_set 확정 로직, legacy_recall/scannable_recall/coverage
# 산출 로직에 라인 변경이 없어야 한다(신규 코드는 이 로직들 "주변"에 삽입되는 순수
# 추가만 허용) — 코드 리뷰 병행.

git diff backend/app/services/surge_detector.py -- :^backend/tests
# 기대: compute_ensemble_score/compute_horizon_signature/select_effective_threshold
# 판정 로직 본체, combo_chase_guard, sector_contagion 게이트에 라인 변경 없음.
# run_horizon_shadow_comparison 함수 시그니처(신규 db 인자 추가)와 본문 하단(영속화
# 추가)만 변경 허용.

grep -rn "horizon_aware_thresholds.enabled\s*=\s*True\|horizon_aware_thresholds\[.enabled.\]\s*=" \
  backend/app/services/ backend/app/surge_config/
# 기대: 0 매치 — 본 SPEC의 어떤 코드도 enabled 플래그를 자동으로 True로 전환하지 않는다.
```

## D. 배포/롤백

TASK-001~003(신규 테이블 + 라벨 계산 + 병렬 지표)은 순수 추가이며 기존 매매/평가
로직에 영향을 주지 않는다 — 배포 자체는 무해하다. TASK-004(섀도우 영속화)는
`shadow_mode_enabled=false`인 동안 조기 반환되므로 배포 시점에는 무해하다. TASK-005
(`shadow_mode_enabled=true` 전환)부터 실제 관측이 시작된다 — 이 시점부터는 매 스코어링
사이클마다 신규 테이블에 1행씩 적재되므로 테이블 증가율을 모니터링한다.

롤백 트리거:

- 신규 라벨 계산이 평가 잡 소요 시간을 유의하게 증가시킴 → TASK-002 계산 로직을
  비동기화하거나 배치화 검토, 필요 시 REQ-AI101-001을 임시 비활성화(신규 테이블 적재만
  중단, 표준 지표는 무영향)
- 섀도우 영속화가 스코어링 사이클 소요 시간을 유의하게 증가시킴 →
  `shadow_mode_enabled`를 즉시 `false`로 되돌림(신규 테이블/함수는 그대로 두어도 무해,
  SPEC-AI-100 D5와 동일 롤백 단위)
- `price_at_signal` 채움률이 예상보다 낮아 신규 지표 표본이 무의미한 수준 → Open
  Question 2 재검토, 신규 지표를 "관측 전용, 의사결정 미사용"으로 격하

롤백 단위: TASK-005(`shadow_mode_enabled` 전환)는 플래그 1줄로 완전 복구. TASK-001~004는
신규 테이블/함수이므로 롤백 시에도 기존 로직에 영향 없이 안전하게 방치 가능(DB 마이그레이션
롤백은 신규 테이블 DROP만 필요, 기존 테이블 스키마 변경 없음).

## E. 리스크

design.md §H와 동일 — `price_at_signal` 채움률 미확인(Open Question 2), `day_high_price`
근사 오차, 섀도우 테이블 무한 증가(Open Question 3, 보존 정책은 후속 작업으로 유예 가능).
