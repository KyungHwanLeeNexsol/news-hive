# SPEC-AI-106 Acceptance Criteria

> GEARS 정규 문장 형식. 각 AC는 **볼드 WHEN/WHILE/WHERE 트리거 + 볼드 shall/shall not 절**로
> 구성한다.

## §A. AC 매트릭스 (REQ ↔ AC 매핑)

| AC ID | 대응 REQ | 심각도 |
|-------|----------|--------|
| AC-106-001 | REQ-AI106-001 | Must-Pass |
| AC-106-002 | REQ-AI106-001 | Must-Pass |
| AC-106-003 | REQ-AI106-004 | Must-Pass |
| AC-106-004 | REQ-AI106-002 | Must-Pass |
| AC-106-005 | REQ-AI106-003 | Must-Pass |
| AC-106-006 | REQ-AI106-006 | Must-Pass |
| AC-106-007 | REQ-AI106-005 | Should-Pass |
| AC-106-008 | REQ-AI106-001, REQ-AI106-003 | Must-Pass |

## §B. 인수 기준 (정규 문장)

### AC-106-001 — 일일 평가 잡이 readiness 로그 1줄을 기록한다

**When** `_run_surge_verify_predictions()`가 정상 실행되고 핵심 평가 결과
(precision/recall/f1)가 커밋되면, the system **shall**
`check_horizon_transition_readiness(db)`를 호출해 그 결과를 `[지평임계값전환게이트]`
태그가 포함된 INFO 로그 1줄로 기록해야 한다.

- 검증 방법: 단위 테스트 — `caplog`(pytest)로 로그 출력을 캡처해
  `[지평임계값전환게이트]` 태그와 INFO 레벨을 확인.

### AC-106-002 — 로그에 4개 필드가 모두 포함된다

**When** readiness 로그가 기록되면, the system **shall** 로그 메시지에
`observed_trading_days`, `regimes_observed`, `max_change_pct`, `all_criteria_met`
4개 값을 모두 포함해야 하며, **shall not** 이 중 하나라도 누락해서는 안 된다.

- 검증 방법: 단위 테스트 — 고정 fixture(`SurgeHorizonShadowObservation` 10행,
  BULL/SIDEWAYS/BEAR 혼합)로 `check_horizon_transition_readiness` 결과를 만든 뒤,
  로그 문자열에 4개 필드 값이 모두 포함됨을 확인.

### AC-106-003 — readiness 예외가 핵심 평가 결과 커밋을 방해하지 않는다

**Where** `check_horizon_transition_readiness(db)` 호출이 예외를 발생시키면, the
system **shall** 그 예외를 격리된 `try/except`로 잡아 경고 로그만 남겨야 하며,
**shall not** `_run_surge_verify_predictions()`의 핵심 평가 결과 저장(precision/
recall/f1 `db.commit()`)에 영향을 주어서는 안 된다.

- 검증 방법: 단위 테스트 — `check_horizon_transition_readiness`를 예외를 던지도록
  mock한 뒤 `_run_surge_verify_predictions()`를 실행, `SurgePredictionEvaluation`
  행이 정상 커밋됨을 확인 + 경고 로그 1줄이 남음을 확인.

### AC-106-004 — 배포 전후 `enabled`/`shadow_mode_enabled` 값이 불변이다

**While** 본 SPEC의 변경이 적용되는 동안, the system **shall not**
`ensemble.horizon_aware_thresholds.enabled` 값을 `false`에서 변경해서는 안 되며,
**shall not** `.shadow_mode_enabled` 값을 `true`에서 변경해서는 안 된다.

- 검증 방법: `git diff -- backend/app/surge_config/surge_detection.yaml`로
  `horizon_aware_thresholds` 블록에 `enabled:`/`shadow_mode_enabled:` 라인 변경이
  없음을 확인.

### AC-106-005 — 판정 함수 3종의 판정 로직에 diff 0

**When** 본 SPEC이 구현되면, the system **shall**
`check_horizon_transition_readiness()`, `run_horizon_shadow_comparison()`,
`compute_horizon_signature()`, `select_effective_threshold()`의 함수 본체(판정
로직)에 어떤 변경도 없어야 하며, **shall not** 이 함수들의 시그니처나 반환값 구조를
변경해서는 안 된다.

- 검증 방법: `git diff -- backend/app/services/surge_horizon_readiness_service.py`가
  빈 결과(파일 무변경)임을 확인 + `git diff -- backend/app/services/surge_detector.py`에
  위 3개 함수(`compute_horizon_signature`/`select_effective_threshold`/
  `run_horizon_shadow_comparison`) 본체 라인 변경이 없음을 확인(호출부 wiring이 이
  파일에 있다면 그 라인만 diff 허용).

### AC-106-006 — 신규 마이그레이션이 0개다

**When** 본 SPEC이 구현되면, the system **shall** `backend/alembic/versions/`에
신규 리비전 파일을 추가하지 않아야 하며, **shall not** 기존 `SurgeHorizonShadowObservation`
테이블 스키마를 변경해서는 안 된다.

- 검증 방법: `git diff --name-only` 출력에 `backend/alembic/versions/` 하위 신규
  파일이 없음을 확인 + `alembic heads`가 SPEC-AI-101 배포 head
  (`074_surge_horizon_shadow_observation`)에서 변경되지 않았음을 확인.

### AC-106-007 — 활성화 검토 절차가 plan.md §C에 문서화된다

**When** plan-phase 산출물이 완성되면, plan.md's §C section **shall** REQ-AI106-005의
3개 최소 항목(관측 완료 확인 방법, per-horizon 임계값 튜닝 판단 기준, 전환 승인·롤백
경로)을 포함해야 한다.

- 검증 방법: `grep -A 30 "^## C\. 활성화 검토 절차" .moai/specs/SPEC-AI-106/plan.md`로
  §C 섹션 헤딩과 "관측 완료 확인"/"임계값 재검토"/"롤백" 키워드 포함 여부를 기계적으로
  확인. 절차 서술의 논리적 완결성은 육안 리뷰를 보조 수단으로만 사용한다.

### AC-106-008 — 호출이 잡 사이클당 1회로 제한되고 기존 회귀 스위트가 전량 통과한다

**While** 본 SPEC이 적용되는 동안, the system **shall** 하루 1회
(`_run_surge_verify_predictions` 잡 사이클당 1회)만 `check_horizon_transition_readiness()`를
호출해야 하며, **shall not** 매 스코어링 사이클(`run_horizon_shadow_comparison`
호출 시점)마다 반복 호출해서는 안 된다. 이 배포 이후에도 기존 SPEC-AI-100/101 회귀
테스트 스위트가 전량 통과해야 한다.

- 검증 방법: 단위 테스트 — mock 호출 카운트로 `check_horizon_transition_readiness`가
  `_run_surge_verify_predictions()` 1회 실행당 정확히 1회 호출됨을 확인 +
  `uv run pytest tests/test_spec_ai_100.py tests/test_spec_ai_101.py -q` 전체 통과.

## Scenarios (Given-When-Then, 최소 2)

### 시나리오 1 — 정상 평가 사이클에서 readiness 로그가 기록되고 핵심 결과는 불변이다

**Given** `shadow_mode_enabled=true`이고 `SurgeHorizonShadowObservation`에 최근
5거래일치 관측 행(BULL 3일, SIDEWAYS 2일)이 존재하며, 오늘의 T-1→T 평가 대상
signal이 정상적으로 존재한다.

**When** `_run_surge_verify_predictions()`가 평일 18:30 KST에 실행된다.

**Then** `SurgePredictionEvaluation` 행이 기존과 동일하게 precision/recall/f1과 함께
커밋되고(AC-106-003 무영향 확인), 그 직후 `[지평임계값전환게이트]` 로그 1줄이
`observed_trading_days=5, regimes_observed=['BULL','SIDEWAYS'],
max_change_pct=<값>, all_criteria_met=False`(레짐 3종 중 BEAR 미관측이므로
False)를 포함해 기록된다(AC-106-001, AC-106-002).

### 시나리오 2 — readiness 조회 예외가 발생해도 핵심 평가 결과는 보존된다

**Given** `check_horizon_transition_readiness(db)` 호출이 (예: DB 커넥션 일시
장애로) `SQLAlchemyError`를 발생시키도록 mock되어 있다.

**When** `_run_surge_verify_predictions()`가 실행된다.

**Then** `SurgePredictionEvaluation` 행은 정상적으로 커밋되며(핵심 평가 결과
무영향, AC-106-003), `[지평임계값전환게이트]` INFO 로그는 기록되지 않는 대신
경고 로그 1줄("readiness 조회 실패 (무시)")만 남고, 잡 전체는 예외 없이
정상 종료된다.

### 시나리오 3 — 배포 전후 `enabled`/`shadow_mode_enabled` 값이 그대로다

**Given** 배포 전 `surge_detection.yaml`의 `horizon_aware_thresholds.enabled=false`,
`.shadow_mode_enabled=true`다.

**When** 본 SPEC의 변경(`scheduler.py` 호출부 wiring)이 배포된다.

**Then** `git diff -- backend/app/surge_config/surge_detection.yaml`이 빈 결과를
반환한다 — 이 SPEC은 yaml 파일을 전혀 수정하지 않으므로 두 값 모두 배포 전과
정확히 동일하다(AC-106-004).

## Edge Cases

- **`SurgeHorizonShadowObservation`이 아직 0행인 경우**(잡이 배포 직후 최초 1회
  실행되기 전): `check_horizon_transition_readiness()`는 이미 SPEC-AI-101에서
  `max((row.change_pct for row in rows), default=0.0)`로 빈 결과를 안전하게
  처리하도록 구현되어 있다 — `observed_trading_days=0, regimes_observed=set(),
  max_change_pct=0.0, all_criteria_met=False`가 로그에 그대로 출력된다. 본 SPEC은
  이 경로에 대한 별도 처리를 추가하지 않는다(기존 함수의 안전 처리를 그대로 신뢰).
- **주말/휴장일**: `_run_surge_verify_predictions()`는 `_is_kr_market_open()`
  false 시 조기 return하므로(기존 guard), readiness 로그 통합 블록 자체가 실행되지
  않는다 — 별도 처리 불필요.
- **`db.commit()` 자체가 실패하는 경우**(readiness 블록 진입 전): 이는 이미
  SPEC-AI-061의 기존 커밋 격리 설계 범위이며, readiness 블록은 이 커밋 성공 이후에만
  진입하므로 본 SPEC의 관심사가 아니다.

## Quality Gate Criteria

- `uv run pytest tests/ --tb=short -q -m "not slow"` 전체 통과(CLAUDE.local.md 검증
  명령 계승).
- `uv run ruff check . && uv run mypy app/` 신규 결함 0건(기존 baseline 결함은 예외).
- 신규 로그 통합 블록에 대한 단위 테스트 커버리지 100%(정상 호출, 예외 격리, 호출
  카운트 검증 3종 모두 포함).
- `git diff --name-only`에 `surge_horizon_readiness_service.py`,
  `evaluate_surge_predictions()` 함수 본체, `compute_horizon_signature`/
  `select_effective_threshold`/`run_horizon_shadow_comparison` 함수 본체,
  `backend/alembic/versions/` 신규 파일이 포함되지 않음(호출부 wiring 추가만 허용).

## Definition of Done

- [ ] AC-106-001 ~ AC-106-008 전량 PASS
- [ ] 3개 시나리오 전량 재현 검증
- [ ] plan.md §C 활성화 검토 절차 최종본 기록(관측 확인 방법/임계값 재검토/승인·롤백
      경로 3항목 포함)
- [ ] CHANGELOG.md `[Unreleased]`에 readiness 로그 통합 항목 추가(`enabled`/
      `shadow_mode_enabled` 무변경임을 명시)
- [ ] `git diff --name-only`가 plan.md §A.1 PRESERVE 목록과 배치되지 않음을 리뷰로
      확인
