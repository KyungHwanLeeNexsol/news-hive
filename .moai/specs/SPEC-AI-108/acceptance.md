# SPEC-AI-108 Acceptance Criteria

> GEARS 정규 문장 형식. 각 AC는 **볼드 WHEN/WHILE/WHERE 트리거 + 볼드 shall/shall not 절**로
> 구성한다.

## §A. AC 매트릭스 (REQ ↔ AC 매핑)

| AC ID | 대응 REQ | 심각도 |
|-------|----------|--------|
| AC-108-001 | REQ-AI108-001 | Must-Pass |
| AC-108-002 | REQ-AI108-001 | Must-Pass |
| AC-108-003 | REQ-AI108-001 | Must-Pass |
| AC-108-004 | REQ-AI108-003 | Must-Pass |
| AC-108-005 | REQ-AI108-003 | Must-Pass |
| AC-108-006 | REQ-AI108-004 | Must-Pass |
| AC-108-007 | REQ-AI108-006 | Must-Pass |
| AC-108-008 | REQ-AI108-007 | Must-Pass |
| AC-108-009 | REQ-AI108-005 | Must-Pass |
| AC-108-010 | REQ-AI108-008 | Should-Pass |

## §B. 인수 기준 (정규 문장)

### AC-108-001 — 빈/None `surge_basis`는 `multi_day_dominant`로 재구성된다

**When** `_reconstruct_horizon_signature_from_basis()`가 `surge_basis=None` 또는
`surge_basis=[]`로 호출되면, the system **shall** `"multi_day_dominant"`를
반환해야 한다 — `compute_horizon_signature()`의 "발화한 탐지기 없음" 분기와
동일한 결과다.

- 검증 방법: 단위 테스트 — 두 입력(`None`, `[]`) 각각에 대해 반환값을 확인.

### AC-108-002 — 단일/다중 라벨 재구성이 `compute_horizon_signature()`와 동등하다

**When** `_reconstruct_horizon_signature_from_basis()`가 앙상블 7개 키 중
단일 키(예: `["volume_breakout"]`)로 호출되면, the system **shall**
`"{horizon_labels[key]}_dominant"`(예: `horizon_labels["volume_breakout"]=
"same_day"`이면 `"same_day_dominant"`)를 반환해야 한다. **When** 서로 다른
라벨을 갖는 2개 이상의 키(예: `["theme_cluster", "volume_breakout"]`,
`horizon_labels`가 각각 `multi_day`/`same_day`)로 호출되면, the system
**shall** `"mixed"`를 반환해야 한다.

- 검증 방법: 단위 테스트 — 6개 케이스(단일 same_day 키/단일 next_day 키/단일
  multi_day 키/2개 이상 서로 다른 라벨 조합/`surge_basis=["immediate_disclosure"]`
  정규화 동등성/`surge_basis=["legacy"]` 정규화 동등성)를 라이브
  `compute_horizon_signature()`가 동일 입력(대응하는 컴포넌트 점수 조합 —
  `immediate_disclosure_score>0` 또는 `legacy_score>0`)으로 산출하는 값과
  대조. 마지막 2개 케이스는 spec.md §Context [E-6]에서 확정한 정규화 매핑
  (`{"immediate_disclosure": "disclosure_pattern", "legacy":
  "legacy_detectors"}`)이 실제로 적용되는지 검증하는 회귀 방지 테스트다.

### AC-108-003 — 앙상블 7개 키 밖의 `surge_basis` 멤버는 무시된다

**When** `surge_basis`에 앙상블 7개 키에 속하지 않는 이름(예:
`"near_limit_up_carry"`, `"weekend_gap_up"`이 `horizon_labels`에 매핑되어
있더라도, 우회/독립 탐지기 이름이 섞여 들어온 경우)이 포함되면, the system
**shall not** 그 이름을 지평 시그니처 계산에 포함해서는 안 된다 — 앙상블
7개 키에 속한 멤버만으로 재구성해야 한다.

- 검증 방법: 단위 테스트 — `surge_basis=["near_limit_up_carry",
  "volume_breakout"]`을 넣었을 때 `near_limit_up_carry`가 결과에 영향을
  주지 않고(예: `["volume_breakout"]`만 있을 때와 동일한
  `"same_day_dominant"` 결과) 검증.

### AC-108-004 — 지평 시그니처별 정밀도가 4개 버킷 모두에 산출된다

**When** `_analyze_precision_by_horizon_signature()`가 각 지평 시그니처를
가진 신호가 최소 1건씩 존재하는 `signal_rows`와 대응하는
`SurgeSignalForwardOutcome` 행들로 호출되면, the system **shall**
`same_day_dominant`/`next_day_dominant`/`multi_day_dominant`/`mixed` 4개
버킷 모두에 대해 `{signal_count, forward_positive_count, precision}`을
반환해야 한다.

- 검증 방법: 단위 테스트 — 4개 버킷에 각각 서로 다른 신호 수와
  `forward_max_return_pct` 분포를 가진 fixture로 정밀도 계산값을 수동
  계산값과 대조.

### AC-108-005 — 재조회는 `signal_rows`의 `fund_signal_id` 집합으로 한정되고 `predicted_set`을 재조회하지 않는다

**When** `_analyze_precision_by_horizon_signature()`가 실행되면, the system
**shall** `SurgeSignalForwardOutcome` 조회를 `trading_date` + 파라미터로
전달된 `signal_rows`의 `fund_signal_id` 집합으로 제한해야 하며, **shall not**
`FundSignal`/`Stock` 테이블을 재조회해 `predicted_set`을 다시 산출해서는
안 된다.

- 검증 방법: 단위 테스트 — SQL 쿼리 mock/spy로 `SurgeSignalForwardOutcome`
  조회 1회만 발생하고 `FundSignal`/`Stock` 추가 조회가 없음을 확인.

### AC-108-006 — 신호 수 0인 버킷의 precision은 None이다

**While** 어느 지평 시그니처 버킷에 속하는 신호가 0건인 동안, the system
**shall** 그 버킷의 `precision` 값을 `None`으로 반환해야 하며, **shall not**
`ZeroDivisionError`를 발생시키거나 `0.0`을 반환해서는 안 된다.

- 검증 방법: 단위 테스트 — 특정 버킷(예: `mixed`)에 해당하는 신호가 전혀
  없는 fixture로 호출해 `precision is None`, `signal_count == 0`을 확인.

### AC-108-007 — 정상 평가 사이클에서 구조화 로그 1줄이 기록된다

**When** `evaluate_surge_predictions()`가 정상 실행되고 REQ-AI101-001의
신호가 기준 EOD 최대수익률 upsert가 완료되면, the system **shall**
`[지평시그니처정밀도]` 태그를 포함하는 INFO 로그 1줄에 4개 버킷 전부의
`{signal_count, forward_positive_count, precision}` 값을 기록해야 한다.

- 검증 방법: 단위 테스트 — `caplog`(pytest)로 로그 캡처, 태그와 4개 버킷
  키가 모두 포함됨을 확인.

### AC-108-008 — 진단 실패가 핵심 평가 결과 및 EOD upsert를 방해하지 않는다

**When** `_reconstruct_horizon_signature_from_basis()` 또는
`_analyze_precision_by_horizon_signature()` 호출이 예외를 발생시키면, the
system **shall** 그 예외를 격리된 `try/except`로 잡아 경고 로그만 남겨야
하며, **shall not** `evaluate_surge_predictions()`의 핵심 평가 결과 저장
(`SurgePredictionEvaluation` upsert/commit) 또는 REQ-AI101-001/002의
`SurgeSignalForwardOutcome` upsert에 영향을 주어서는 안 된다.

- 검증 방법: 단위 테스트 — `_analyze_precision_by_horizon_signature`를
  예외를 던지도록 mock한 뒤 `evaluate_surge_predictions()`를 실행,
  `SurgePredictionEvaluation`과 `SurgeSignalForwardOutcome` 행이 모두
  정상 커밋됨을 확인 + 경고 로그 1줄이 남음을 확인.

### AC-108-009 — 게이팅/신규 테이블/기존 함수 무변경

**When** 본 SPEC이 구현되면, the system **shall**:

- `ensemble.horizon_aware_thresholds.enabled`(`false`)와
  `.shadow_mode_enabled`(`true`) 값을 배포 전과 동일하게 유지해야 한다;
- `backend/alembic/versions/`에 신규 리비전 파일을 추가하지 않아야 한다;
- `compute_horizon_signature()`, `select_effective_threshold()`,
  `run_horizon_shadow_comparison()`, `check_horizon_transition_readiness()`,
  `evaluate_high_based_outcomes()`, `_persist_signal_forward_outcomes()`의
  함수 본체(판정/계산 로직)에 어떤 변경도 없어야 한다.

- 검증 방법: `git diff -- backend/app/surge_config/surge_detection.yaml`이
  빈 결과임을 확인 + `git diff --name-only`에 `backend/alembic/versions/`
  하위 신규 파일이 없음을 확인 + `git diff -- backend/app/services/surge_detector.py
  backend/app/services/surge_horizon_readiness_service.py`에서 위 6개 함수
  본체 라인 변경이 없음을 확인(신규 헬퍼 함수 **추가**는 허용, 기존 함수
  **본체 수정**만 금지).

### AC-108-010 — 증거 활용 절차가 plan.md §C에 문서화된다

**When** plan-phase 산출물이 완성되면, plan.md's §C section **shall**
REQ-AI108-008의 2개 최소 항목(SPEC-AI-100 Open Question 2 판단 참고 방법,
SPEC-AI-100 D1 재검토 참고 방법)을 포함해야 하며, 이 SPEC이 그 결정을
직접 내리지 않는다는 진술을 명시해야 한다.

- 검증 방법: `grep -A 30 "^## C\. 증거 활용 절차" .moai/specs/SPEC-AI-108/plan.md`로
  §C 섹션 헤딩과 "Open Question 2"/"D1"/"재검토" 키워드 포함 여부를
  기계적으로 확인.

## Scenarios (Given-When-Then, 최소 2)

### 시나리오 1 — 정상 평가 사이클에서 4버킷 정밀도가 산출되고 핵심 결과는 불변이다

**Given** 오늘(T-1)에 생성된 `surge_candidate` 신호 6건이 `predicted_set`에
존재하며, 그 중 2건은 `surge_basis=["volume_breakout"]`(same_day_dominant),
2건은 `surge_basis=["momentum_continuation"]`(next_day_dominant), 1건은
`surge_basis=["theme_cluster"]`(multi_day_dominant), 1건은
`surge_basis=["theme_cluster", "volume_breakout"]`(mixed)이고, 각 신호의
`price_at_signal`과 T당일 `high_change_rate`가 모두 유효해 `forward_max_return_pct`
계산이 가능하다.

**When** `evaluate_surge_predictions()`가 평일 18:30 KST에 실행된다.

**Then** `SurgePredictionEvaluation` 행이 기존과 동일하게 precision/recall/f1과
함께 커밋되고(AC-108-008 무영향 확인), `SurgeSignalForwardOutcome`에 6개
신호 전부의 `forward_max_return_pct`가 upsert되며(REQ-AI101-001 무영향),
그 직후 `[지평시그니처정밀도]` 로그 1줄이 4개 버킷
`{same_day_dominant: {signal_count:2,...}, next_day_dominant: {signal_count:2,...},
multi_day_dominant: {signal_count:1,...}, mixed: {signal_count:1,...}}`을
포함해 기록된다(AC-108-004, AC-108-007).

### 시나리오 2 — 진단 함수 예외 발생 시 핵심 결과와 EOD upsert 모두 보존된다

**Given** `_analyze_precision_by_horizon_signature()` 호출이 (예: DB 커넥션
일시 장애로) `SQLAlchemyError`를 발생시키도록 mock되어 있다.

**When** `evaluate_surge_predictions()`가 실행된다.

**Then** `SurgePredictionEvaluation` 행과 `SurgeSignalForwardOutcome` 행
모두 정상적으로 커밋되며(핵심 결과 및 REQ-AI101-001/002 무영향, AC-108-008),
`[지평시그니처정밀도]` INFO 로그는 기록되지 않는 대신 경고 로그 1줄
("진단 실패 (무시)")만 남고, 잡 전체는 예외 없이 정상 종료된다.

### 시나리오 3 — 우회/독립 탐지기만 발화한 신호는 multi_day_dominant로 안전하게 처리된다

**Given** 어떤 신호의 `surge_basis`가 `["near_limit_up_carry"]`뿐이다(앙상블
7개 키에 속하지 않는 독립 탐지기).

**When** 이 신호가 `_reconstruct_horizon_signature_from_basis()`에 전달된다.

**Then** 앙상블 7개 키와의 교집합이 빈 집합이므로 `"multi_day_dominant"`가
반환된다(AC-108-001/003의 조합 케이스) — 예외가 발생하지 않는다.

## Edge Cases

- **`surge_metadata`가 JSON 파싱 불가능한 경우**: `surge_basis` 추출이
  실패하면 그 신호는 `surge_basis=None`으로 취급해 AC-108-001 분기
  (`multi_day_dominant`)로 안전하게 처리한다 — 개별 신호 파싱 실패가 전체
  진단을 중단시키지 않는다(REQ-AI108-007과 별개로, 함수 내부에서도
  신호 단위 방어적 처리를 권장).
- **`SurgeSignalForwardOutcome`에 아직 해당 `fund_signal_id` 행이 없는 경우**
  (예: REQ-AI101-001 upsert가 어떤 이유로 일부 신호를 건너뛴 경우):
  해당 신호는 `forward_max_return_pct=None`으로 취급되어
  `forward_positive_count` 판정에서 False(양성 아님)로 집계되지만
  `signal_count`에는 포함된다 — SPEC-AI-101의 기존 `forward_actual_codes`
  판정과 동일 기준(NULL은 미달성으로 취급, 별도 예외 처리 없음).
- **`predicted_set`이 0건인 날**(예측 자체가 없는 날): 4개 버킷 모두
  `signal_count=0, precision=None`으로 로그가 기록된다 — REQ-AI108-004
  가드가 이 경우를 정상적으로 처리한다.
- **주말/휴장일**: `_run_surge_verify_predictions()`가 조기 return하므로
  `evaluate_surge_predictions()` 자체가 호출되지 않아 본 SPEC의 블록도
  실행되지 않는다 — 별도 처리 불필요.

## Quality Gate Criteria

- `uv run pytest tests/ --tb=short -q -m "not slow"` 전체 통과(CLAUDE.local.md
  검증 명령 계승).
- `uv run ruff check . && uv run mypy app/` 신규 결함 0건(기존 baseline
  결함은 예외).
- 신규 함수 2종(`_reconstruct_horizon_signature_from_basis`,
  `_analyze_precision_by_horizon_signature`) + 로그 통합 블록에 대한 단위
  테스트 커버리지 100%(정상 케이스, 0-신호 가드, 예외 격리 전부 포함).
- `git diff --name-only`에 `backend/app/services/surge_detector.py`,
  `backend/app/services/surge_horizon_readiness_service.py`의 기존 함수
  본체 변경, `backend/alembic/versions/` 신규 파일, `surge_detection.yaml`의
  `horizon_aware_thresholds.enabled`/`.shadow_mode_enabled` 라인 변경이
  포함되지 않음.

## Definition of Done

- [ ] AC-108-001 ~ AC-108-010 전량 PASS
- [ ] 3개 시나리오 전량 재현 검증
- [ ] plan.md §C 증거 활용 절차 최종본 기록(Open Question 2 판단 참고 방법 /
      D1 재검토 참고 방법 / 이 SPEC이 결정을 내리지 않는다는 명시 3항목 포함)
- [ ] CHANGELOG.md `[Unreleased]`에 지평 시그니처별 정밀도 진단 추가 항목
      기재(`enabled`/`shadow_mode_enabled` 무변경임을 명시)
- [ ] `git diff --name-only`가 plan.md §A.1 PRESERVE 목록과 배치되지 않음을
      리뷰로 확인
