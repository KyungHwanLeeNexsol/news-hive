# SPEC-AI-095 Acceptance Criteria

> GEARS 정규 문장 형식. 각 AC는 **볼드 WHEN/WHILE/WHERE 트리거 + 볼드 shall/shall not 절**로
> 구성한다.

**범위 안내**: 본 SPEC은 이 세션에서 요청된 두 항목 중 "고가 기반 평가지표 노출" 하나만 다룬다.
"existing_codes 병합 필터" 항목은 SPEC-AI-094와의 설계 상충으로 spec.md §Out of Scope에서
명시적으로 제외되었으므로, 그 항목에 대한 무회귀 기준(Pool A/B/C/D 배분·매매/시그널 생성 무변경)은
이 문서의 범위가 아니다 — SPEC-AI-094 자체의 인라인 Acceptance Criteria
(`.moai/specs/SPEC-AI-094/spec.md` AC-094-003)가 이미 그 기준을 소유한다.

## §A. AC 매트릭스 (REQ ↔ AC 매핑)

| AC ID | 대응 REQ | 심각도 |
|-------|----------|--------|
| AC-095-001 | REQ-AI095-001 | Must-Pass |
| AC-095-002 | REQ-AI095-003 | Must-Pass |
| AC-095-003 | REQ-AI095-003 | Must-Pass |
| AC-095-004 | REQ-AI095-004 | Must-Pass |
| AC-095-005 | REQ-AI095-005 | Should-Pass |
| AC-095-006 | REQ-AI095-003 | Must-Pass |
| AC-095-007 | REQ-AI095-002 | Must-Pass |
| AC-095-008 | REQ-AI095-001 | Should-Pass |
| AC-095-009 | REQ-AI095-001 | Must-Pass |

## §B. 인수 기준 (정규 문장)

### AC-095-001 — 고가 기준 recall/precision이 predicted_set과 교차하여 산출된다

**When** 종목 A/B/C가 `predicted_set`에 있고, T일 `high_change_rate` 기준으로 A/B만 급등
(`COALESCE(high_change_rate, change_rate) >= 10.0`)이며 실제로는 A/B/C 중 D(비예측 종목)도
급등이면, the system **shall** `high_based_true_positive=2`(A,B)를 산출하고
`high_based_false_negative`를 D 포함 여부에 따라 정확히 계산하며
`high_based_recall = 2/(2+high_based_false_negative)`를 산출해야 한다.

- 검증 방법: pytest — `SurgeActualOutcome`/`FundSignal` fixture 주입 후 반환된
  `SurgePredictionEvaluation.high_based_recall`/`high_based_precision` 값 검사

### AC-095-002 — idempotent 재실행 시 양쪽 upsert 분기 모두 값을 보존한다

**When** 동일 `evaluation_date`에 대해 `evaluate_surge_predictions()`를 두 번 연속
호출하면(첫 호출=신규 생성 분기, 두 번째 호출=기존 갱신 분기), the system **shall** 두 호출
모두에서 `high_based_recall`/`high_based_precision`/`high_based_coverage`가 NULL로
되돌아가지 않고 두 번째 계산값으로 갱신되어야 한다.

- 검증 방법: pytest — 동일 fixture로 2회 연속 호출 후 DB 재조회, 값이 NULL이 아님을 확인
  (plan.md TASK-003이 명시한 "한쪽 분기만 수정" 실수를 직접 재현하는 회귀 테스트)

### AC-095-003 — 신규 컬럼이 마이그레이션으로 존재하고 영속화된다

**When** alembic 마이그레이션을 `head`까지 적용하면, the system **shall**
`surge_prediction_evaluation` 테이블에 `high_based_recall`/`high_based_precision`/
`high_based_coverage` 3개 nullable Float 컬럼이 존재해야 하며, `evaluate_surge_predictions()`
호출 이후 DB에서 해당 행을 재조회했을 때 3개 값이 계산 결과와 일치해야 한다(런타임 속성이
아닌 실제 영속값임을 증명).

- 검증 방법: pytest — `db.commit()` 이후 새 세션으로 재조회(또는 `db.expire_all()` + 재조회)해
  값이 유지됨을 확인. `uv run alembic upgrade head; uv run alembic current` 성공.

### AC-095-004 — 계산 실패가 주 평가 결과를 방해하지 않는다

**When** 고가 기준 계산 쿼리가 예외를 발생시키면(mock으로 주입), the system **shall**
`high_based_recall`/`high_based_precision`/`high_based_coverage`를 모두 `None`으로 처리
하고, 기존 `precision`/`recall`/`f1_score`/`true_positive`/`false_positive`/
`false_negative`/`scannable_recall`/`coverage` 8개 필드는 예외 발생 이전과 동일한 계산
결과로 정상 upsert·commit되어야 하며, 함수 전체가 예외를 전파해서는 **shall not**.

- 검증 방법: pytest — 고가 기준 쿼리 지점만 mock으로 예외 주입, 반환된 evaluation 객체의
  나머지 8개 필드가 예외 없는 케이스와 동일함을 확인

### AC-095-005 — 로그에 고가 기준 지표가 노출된다

**When** `evaluate_surge_predictions()`가 완료되면, the system **shall** 로그에
`high_based_recall`/`high_based_precision`/`high_based_coverage` 값(계산 실패 시 `None`
포함)을 남겨야 한다.

- 검증 방법: pytest — `caplog`로 로그 라인에 세 필드명이 포함됨을 확인

### AC-095-006 — 과거 행은 백필되지 않는다

**When** alembic 마이그레이션이 `head`까지 적용되면, the system **shall** 배포 이전에 존재하던
모든 `surge_prediction_evaluation` 행의 `high_based_recall`/`high_based_precision`/
`high_based_coverage`를 NULL로 유지해야 하며, 해당 거래일에 대해
`evaluate_surge_predictions()`가 실행되기 전까지는 이 값들을 채워서는 **shall not**.

- 검증 방법: 마이그레이션 스크립트에 데이터 백필 로직이 없음을 코드 리뷰로 확인 + pytest로
  기존 행 무변경 검증

### AC-095-007 — 기존 주 지표 완전 무회귀

**While** 본 SPEC이 적용된 상태에서, the system **shall** 동일 입력 fixture에 대해 적용 이전과
완전히 동일한 `precision`/`recall`/`f1_score`/`true_positive`/`false_positive`/
`false_negative`/`scannable_recall`/`coverage` 값을 산출해야 하며, `was_surge` 판정 기준
(`change_rate >= 10.0`)을 변경해서는 **shall not**.

- 검증 방법: pytest — `test_surge_evaluation_service.py`의 기존 characterization 테스트 전체
  (적용 전/후 diff 0) + 다음 grep이 0 매치

```bash
git diff --name-only | grep -E 'surge_actual_outcome_service\.py'
```

  (본 SPEC이 `surge_actual_outcome_service.py`를 전혀 건드리지 않음을 증명 — plan.md TASK
  목록에 해당 파일이 없음과 정합)

### AC-095-008 — predicted_count=0일 때 NULL 처리

**When** `predicted_set`이 빈 집합(시그널 미발신일)이면, the system **shall**
`high_based_precision`을 `None`으로 처리해야 하며 `ZeroDivisionError`를 발생시켜서는
**shall not**.

- 검증 방법: pytest — `predicted_set=set()` fixture로 호출, 예외 없이 `None` 반환 확인

### AC-095-009 — TP_high+FN_high=0일 때 recall NULL 처리

**When** 해당 거래일에 `high_actual_set`이 빈 집합(고가 기준 급등 실제 종목이 0건, 즉
`high_based_true_positive + high_based_false_negative == 0`)이면, the system **shall**
`high_based_recall`을 `None`으로 처리해야 하며 `ZeroDivisionError`를 발생시켜서는
**shall not** — REQ-AI095-001의 `predicted_count == 0` → `high_based_precision` NULL
가드와 대칭인 recall 쪽 분모-0 가드다(기존 `scannable_recall`의 동일 패턴,
`surge_evaluation_service.py:832-834` 재사용).

- 검증 방법: pytest — `SurgeActualOutcome` fixture를 `high_change_rate`/`change_rate`
  전부 급등 임계값 미만으로 구성(`high_actual_set=set()`), `predicted_set`은 비어있지
  않은 상태로 호출, 예외 없이 `high_based_recall is None` 반환 확인
  (`high_based_true_positive=0`도 함께 검증)

## §C. Given-When-Then 시나리오 (AC 보강용, AC 정의 아님)

### 시나리오 1 — 종가로는 놓쳤으나 고가로는 맞춘 예측

- **Given** 종목 X가 `predicted_set`에 있고, T일 `change_rate=7.0`(종가 기준
  `was_surge=False`)이나 `high_change_rate=15.0`(장중 고가 기준 급등)이다.
- **When** `evaluate_surge_predictions()`를 실행한다.
- **Then** 기존 `recall`(종가 기준)은 영향받지 않지만(X는 애초에 `actual_set`에서 제외 —
  `was_surge=False`), `high_based_recall` 계산에서는 X가 `high_actual_set`에 포함되어
  예측이 적중한 것으로 집계되어야 한다. (AC-095-001)

### 시나리오 2 — 재실행 시 값 보존

- **Given** 2026-08-01 평가가 이미 1회 실행되어 `high_based_recall=0.5`가 저장되어 있다.
- **When** 동일 날짜에 대해 (예: 스케줄러 재시도로) 평가를 다시 실행한다.
- **Then** 재계산된 값(예: 0.6)으로 갱신되어야 하며, NULL로 되돌아가서는 안 된다.
  (AC-095-002)

### 시나리오 3 — 계산 실패 시 주 지표 보존

- **Given** 고가 기준 쿼리가 DB 연결 문제로 예외를 던진다.
- **When** 평가를 실행한다.
- **Then** `precision=0.667`, `recall=0.5` 등 기존 지표는 정상 저장되고,
  `high_based_recall`/`high_based_precision`/`high_based_coverage`만 NULL이어야 한다.
  (AC-095-004)

### 시나리오 4 — 무회귀 (동일 fixture, 적용 전후 비교)

- **Given** 본 SPEC 적용 전 어떤 거래일의 `precision=0.667`, `recall=0.5`,
  `scannable_recall=0.4`였다.
- **When** 동일 fixture로 본 SPEC 적용 후 재실행한다.
- **Then** 세 값 모두 완전히 동일해야 한다. (AC-095-007)

### 시나리오 5 — predicted_set 공집합

- **Given** 어떤 거래일에 발신된 `surge_candidate` 시그널이 0건이다.
- **When** 평가를 실행한다.
- **Then** `high_based_true_positive=0`, `high_based_precision=None`(0.0이 아님)이어야 한다.
  (AC-095-008)

## §D. Edge Cases

- **`SurgeActualOutcome` 행 자체가 0건인 거래일**: `high_actual_set`이 빈 집합 →
  `high_based_true_positive=0`, `high_based_recall`은 분모(`TP_high+FN_high`)도 0이므로
  NULL(측정 불가) — 기존 `scannable_recall`의 EC-1 관례(분모 0 → NULL)를 재사용한다.
- **`high_change_rate`가 전량 NULL인 배포 직후 거래일**(SPEC-AI-093 D3 전진 적용 여파):
  `COALESCE(high_change_rate, change_rate)`가 자동으로 `change_rate`로 폴백하므로
  `high_actual_set`은 사실상 `actual_set`(주 지표)과 동일해진다 — `high_based_coverage`가
  낮은 값(또는 0)으로 그 사실을 드러낸다. 별도 처리 불필요(spec.md D4 fallback 설계가
  자연스럽게 방어).
- **`predicted_set`과 `high_actual_set`이 완전히 서로소**: `high_based_true_positive=0`,
  `high_based_recall=0.0`(NULL이 아님 — 분모가 0이 아니므로 "측정 불가"와 "0%"를 구분).
- **마이그레이션 재실행(멱등성)**: `alembic upgrade head`를 이미 적용된 상태에서 다시
  실행해도 오류 없이 no-op이어야 한다(표준 alembic 관례, 별도 테스트 불필요).

## §E. Definition of Done

- [ ] AC-095-001 통과 — 고가 기준 recall/precision 산출.
- [ ] AC-095-002 통과 — idempotent 재실행 양쪽 분기 보존.
- [ ] AC-095-003 통과 — 마이그레이션 + 영속화 증명.
- [ ] AC-095-004 통과 — 계산 실패 격리.
- [ ] AC-095-005 통과 — 로그 노출.
- [ ] AC-095-006 통과 — 과거 행 백필 없음.
- [ ] AC-095-007 통과 — 기존 주 지표 완전 무회귀 + `surge_actual_outcome_service.py` diff 0.
- [ ] AC-095-008 통과 — `predicted_count=0` NULL 처리.
- [ ] AC-095-009 통과 — `TP_high+FN_high=0` 시 recall NULL 처리.
- [ ] `ruff check` / `mypy` 통과.
- [ ] `alembic upgrade head` 성공.
- [ ] spec.md §Open Questions 1(신규 alembic 리비전 파일명)이 구현 착수 전 확정됨 —
      `predicted_count=0`일 때 `high_based_precision`을 NULL로 처리하는 정책은
      REQ-AI095-001/AC-095-008에서 이미 확정되어 더 이상 Open Question이 아니므로 별도
      DoD 게이트가 불요하다.
- [ ] existing_codes 항목(spec.md §Open Questions 2 / §Out of Scope)의 해소 방향은 본
      SPEC의 DoD가 아니다 — 별도 오케스트레이터/사용자 결정 대상.
