# SPEC-AI-095 Plan

## A. 구현 전략

Tier M, cycle_type: ddd(ANALYZE-PRESERVE-IMPROVE — `quality.yaml` `constitution.development_mode:
ddd`). 범위는 "평가 리포트에 고가 기반 지표를 병렬 노출"이라는 단일 축에 한정하며, `was_surge`
판정·주 지표 산출식·라우터 응답 스키마 어느 것도 건드리지 않는다.

핵심 판단:

- 이 SPEC의 위험은 새 계산 로직 자체가 아니라 **기존 upsert 두 분기(갱신/생성) 중 하나에만
  필드를 추가해 재실행 시 값이 소실되는 실수**다. 두 분기 모두 수정을 TASK-002/003에서
  명시적으로 요구한다.
- 고가 기반 계산은 기존 Scannable Recall 블록(5단계, `surge_evaluation_service.py:809-856`)과
  구조적으로 동일하다 — 새 패턴을 발명하지 않고 그 블록을 인접 확장한다(spec.md §Decisions D3).
- 데이터 모델(신규 nullable 컬럼 3개)이 가장 되돌리기 어려운 결정이므로 TASK-001로 가장 먼저
  다룬다 — 계산 로직·로깅은 이후 얼마든지 조정 가능하지만, 컬럼 스키마는 마이그레이션이 배포된
  뒤에는 되돌리는 비용이 더 크다.

### A.5 PRESERVE 목록 (수정 금지)

| 대상 | 사유 |
|------|------|
| `surge_actual_outcome_service.py`의 `evaluate_high_based_outcomes()` | REQ-AI095 무관 — 무수정. 본 SPEC은 유사 계산을 인접 배치할 뿐 그 함수를 호출·확장하지 않는다 |
| `surge_evaluation_service.py`의 4단계(TP/FP/FN 계산) 및 5단계(Scannable Recall) | 기존 주 지표 산출 로직 — REQ-AI095-002 |
| `SurgeActualOutcome.was_surge` 및 그 소비자 7개 지점(SPEC-AI-093 PRESERVE 승계) | `was_surge` 동결 |
| `backend/app/routers/surge_trading.py`의 3개 엔드포인트 | 응답 dict 키 목록 — 본 SPEC은 영속화까지만(spec.md §Out of Scope) |
| `SurgePredictionEvaluation`의 기존 컬럼 전체 | 신규 3개 컬럼만 추가, 기존 컬럼 타입/nullable 속성 무변경 |

## B. 작업 분해

### TASK-001: 마이그레이션 — `SurgePredictionEvaluation`에 3개 nullable 컬럼 추가

- 대상: 신규 `backend/alembic/versions/070_surge_pred_eval_high_based.py`(제안 파일명,
  down_revision = `"069_surge_pred_eval_snapshot"`), `backend/app/models/surge_prediction_evaluation.py`
- `high_based_recall: Mapped[Optional[float]]`, `high_based_precision: Mapped[Optional[float]]`,
  `high_based_coverage: Mapped[Optional[float]]` — 전부 `Float, nullable=True`, 서버 기본값 없음.
- 백필 없음(기존 행은 NULL로 남는다).

추적 REQ/AC: REQ-AI095-003 / AC-095-003, AC-095-006

### TASK-002: `evaluate_surge_predictions()`에 고가 기준 계산 블록 추가

- 대상: `backend/app/services/surge_evaluation_service.py` — 5단계(Scannable Recall, 현재
  `:809-856`) 직후에 새 블록을 추가한다.
- `SurgeActualOutcome`에서 `func.coalesce(high_change_rate, change_rate) >= surge_threshold`
  조건으로 `stock_code` 집합을 조회(신규 쿼리 1건, 기존 4단계 `actual_rows` 쿼리와 동일한
  형태로 `trading_date` 필터만 다름).
- `predicted_set`(2단계에서 이미 확정)과 교차해 TP_high/FN_high 산출 → recall_high/
  precision_high 계산.
- 실패 시 `try/except` + `db.rollback()`으로 격리(5단계와 동일 패턴), 3개 값 모두 `None`.
- 로그 라인 1건 추가(REQ-AI095-005).

추적 REQ/AC: REQ-AI095-001, REQ-AI095-004, REQ-AI095-005 / AC-095-001, AC-095-004, AC-095-005, AC-095-008, AC-095-009

### TASK-003: 6단계 upsert 양쪽 분기에 3개 필드 배선

- 대상: `surge_evaluation_service.py`의 `existing.xxx = ...` 갱신 분기와
  `SurgePredictionEvaluation(...)` 생성 분기 **양쪽 모두**.
- 두 분기 중 하나만 수정하면 재실행(같은 `evaluation_date`에 대한 재평가) 시 값이 조용히
  NULL로 되돌아간다 — TASK-005의 idempotency 회귀 테스트가 이를 검증한다.

추적 REQ/AC: REQ-AI095-003 / AC-095-002, AC-095-003

### TASK-004: 기존 주 지표 무회귀 확인

- 대상: 없음(코드 변경 아님) — TASK-002/003이 4단계 이전 로직 및 `surge_actual_outcome_service.py`를
  건드리지 않았는지 diff로 확인.

추적 REQ/AC: REQ-AI095-002 / AC-095-007

### TASK-005: 무회귀·신규 검증

- 대상: `backend/tests/test_surge_evaluation_service.py`(기존 파일 확장)
- 기존 테스트 전체가 무수정으로 통과하는지 확인 — 신규 쿼리가 추가되므로 fixture DB 세션을
  사용하는 기존 테스트는 영향받지 않아야 한다(신규 컬럼은 nullable이므로 기존 INSERT 문에
  영향 없음).
- 신규 테스트: 고가 기반 recall/precision 정상 케이스, 실패 격리(mock으로 예외 주입),
  idempotent 재실행(TASK-003 회귀), `predicted_count=0` 시 NULL 처리,
  `TP_high+FN_high=0` 시 recall NULL 처리(AC-095-009), 로그 노출.

추적 REQ/AC: REQ-AI095-001~005 전체 / AC-095-001~009

## C. 검증 계획

타겟 테스트:

```powershell
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests\test_surge_evaluation_service.py -q
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests\test_surge_actual_outcome_service.py -q
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests\test_spec_ai_092.py -q
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

임포트 sanity:

```powershell
cd backend; uv run python -c "from app.main import app; print('OK')"
```

마이그레이션 적용 확인:

```powershell
cd backend; uv run alembic upgrade head; uv run alembic current
```

## D. 배포/롤백

신규 컬럼 3개는 nullable + 기본값 없음이므로 배포 즉시 기존 소비자에게 관측되지 않는 순수
추가다. 라우터가 이 컬럼들을 아직 응답에 포함하지 않으므로(spec.md §Out of Scope) 프런트엔드
영향도 없다.

롤백 트리거:

- `evaluate_surge_predictions()` 소요 시간이 기존 대비 유의미하게 증가(신규 쿼리 1건 추가분
  이상)
- 신규 쿼리 실패로 인해 주 평가 결과(precision/recall/f1) commit이 실패하는 사례 발생
  (REQ-AI095-004 위반 신호 — 즉시 조사)

롤백 단위: TASK-002/003의 계산·배선 코드만 되돌리면 3개 컬럼은 다시 항상 NULL이 되며 나머지
지표는 영향받지 않는다. 컬럼 자체(TASK-001)는 되돌릴 필요가 없다(존재해도 무해).

## E. 리스크

- **쿼리 추가 비용**: 거래일당 1건의 추가 SQL 집계 쿼리(인덱스: `SurgeActualOutcome.trading_date`
  — 기존 4단계 쿼리와 동일 인덱스 재사용, 추가 인덱스 불필요). 배치 소요 시간 영향은 미미할
  것으로 예상되나 실측하지 않았다 — TASK-005 회귀 테스트가 기능 정확성만 검증하며, 실제 운영
  배치(18:30 KST) 소요 시간 실측은 배포 후 관찰 대상이다.
- **양쪽 upsert 분기 누락 위험**: TASK-003에서 명시적으로 경고했듯, 갱신/생성 분기 중 하나만
  수정하면 재실행 시 조용히 데이터가 소실된다. TASK-005의 idempotency 테스트가 유일한
  방어선이다.
- **existing_codes 항목 제외의 대가**: 본 SPEC은 이 세션에서 요청된 두 항목 중 하나만 다룬다.
  spec.md §Out of Scope 첫 항목의 해소는 별도 오케스트레이터/사용자 결정을 기다린다.
