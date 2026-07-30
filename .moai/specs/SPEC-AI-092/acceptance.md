# SPEC-AI-092 Acceptance Criteria

> GEARS 정규 문장(normative sentence) 형식으로 작성한다. 각 AC는 **볼드 WHEN/WHILE/WHERE
> 트리거 + 볼드 shall/shall not 절**로 구성한다 — Given-When-Then 시나리오는 아래 별도
> 섹션에서 각 AC를 구체적 예시로 보강하는 용도로만 사용하며, AC 정의 자체는 아니다.

## §A. AC 매트릭스 (REQ ↔ AC 매핑)

| AC ID | 대응 REQ | 심각도 |
|-------|----------|--------|
| AC-092-001 | REQ-AI092-001 | Must-Pass |
| AC-092-002 | REQ-AI092-002 | Must-Pass |
| AC-092-003 | REQ-AI092-003 | Must-Pass |
| AC-092-004 | REQ-AI092-003, REQ-AI092-004 | Must-Pass |
| AC-092-005 | REQ-AI092-003 | Must-Pass |
| AC-092-006 | REQ-AI092-005 | Should-Pass |
| AC-092-007 | REQ-AI092-006 | Must-Pass |
| AC-092-008 | REQ-AI092-003 (Non-Goals same-day 제외) | Must-Pass |

## §B. 인수 기준 (정규 문장)

### AC-092-001 — prediction-history predicted_count 고정

**When** `/api/surge-trading/prediction-history`가 평가 완료 row를 반환하면, the system
**shall** `predicted_count`를 현재 `FundSignal` 재조회 결과가 아니라
`SurgePredictionEvaluation.predicted_count` 값으로 반환해야 한다.

- 검증 방법: pytest — `/prediction-history` drift fixture

### AC-092-002 — 평가 스냅샷 복원

**When** 평가 저장 이후 해당 신호의 `FundSignal.created_at`이 변경되면, the system
**shall** 평가 당시 공식 predicted set을 변경 이전과 동일하게 복원할 수 있어야 한다.

- 검증 방법: pytest — 평가 후 signal 날짜 이동 fixture

### AC-092-003 — bridge flag OFF 무회귀

**While** `scan_universe_bridge_candidates_enabled=false`인 동안, the system **shall**
`gather_surge_candidates()`의 결과를 bridge 도입 이전과 동일하게 유지해야 한다.

- 검증 방법: pytest — 동일 fixture ON/OFF 비교

### AC-092-004 — Pool C bridge 후보 생성

**Where** `scan_universe_bridge_candidates_enabled=true`이고 어떤 종목이 Pool C universe에는
포함되지만 `merged`에는 없으며 bridge scoring 최소 조건(TASK-004 pool별 점수 산정 기준)을
만족하면, the system **shall** 그 종목을 `surge_metadata.surge_basis`에
`scan_universe_bridge`와 `pool_c` 근거를 기록한 `surge_candidate` bridge 후보로 생성해야
한다.

- 검증 방법: pytest — Pool C fixture

### AC-092-005 — 신규 외부 fetch 금지

**When** bridge 후보화가 실행되면, the system **shall not** 신규 외부 fetch 호출
(Naver/DART 등)을 추가해서는 안 된다.

- 검증 방법: pytest — Naver/DART fetch mock call count

### AC-092-006 — adaptive threshold 연결성

**When** adaptive threshold를 0.30과 0.70으로 각각 고정한 fixture에서 예측 생성 gate를
실행하면, the system **shall** 저장 후보 수 차이를 관찰 가능하게 하거나, 예측 생성과
무관한 execution-only threshold임을 설정명과 로그에 명시해야 한다.

- 검증 방법: pytest + 로그/설정 검증

### AC-092-007 — 운영 평가 누락 감지

**When** 장마감 이후 지정 시각이 지나고 당일 `surge_actual_outcome` 또는
`surge_prediction_evaluation` row가 없으면, the system **shall** 그 누락 상태와 누락
테이블명을 감지해 반환해야 한다.

- 검증 방법: pytest — health helper fixture

### AC-092-008 — same-day 후보 predicted set 배제

The system **shall not** `horizon="same_day"`인 후보(기존 near-limit-up-carry 계열 포함,
bridge 후보 포함)를 표준 T-1 -> T predicted set에 포함해서는 안 된다.

- 검증 방법: 기존 SPEC-AI-088/평가 서비스 회귀 테스트 + bridge 후보 생성 시 same-day
  horizon 필터링 단위 테스트

## §C. Given-When-Then 시나리오 (AC 보강용, AC 정의 아님)

### 시나리오 1 — prediction-history 카운트 불변

- **Given** `SurgePredictionEvaluation.predicted_count=7`인 평가 완료 row가 있고, 당시 T-1 신호의
  `FundSignal.created_at`이 후일로 이동한 상태다.
- **When** `/api/surge-trading/prediction-history`를 호출한다.
- **Then** 응답 row의 `predicted_count`는 7이어야 한다. (AC-092-001)

### 시나리오 2 — 평가 스냅샷 복원

- **Given** 평가 당시 공식 predicted set에 A/B/C 세 종목이 포함됐다.
- **When** 평가 저장 후 B 종목의 `FundSignal.created_at`이 다음 날로 이동한다.
- **Then** snapshot 기반 predicted set 복원 결과는 여전히 A/B/C 세 종목이어야 한다. (AC-092-002)

### 시나리오 3 — bridge flag OFF 무회귀

- **Given** `scan_universe_bridge_candidates_enabled=false` 기본 설정이다.
- **When** 기존 fixture로 `gather_surge_candidates()`를 실행한다.
- **Then** bridge 도입 전과 동일한 후보 목록과 시그널 수가 반환되어야 한다. (AC-092-003)

### 시나리오 4 — Pool C bridge 후보 생성

- **Given** Pool C universe에는 포함됐지만 기존 `merged`에는 없는 종목 X가 있고, X는 bridge
  scoring 최소 조건을 만족한다.
- **When** `scan_universe_bridge_candidates_enabled=true`로 `gather_surge_candidates()`를 실행한다.
- **Then** X는 `surge_basis`에 `scan_universe_bridge`와 `pool_c` 근거를 가진 `surge_candidate`
  후보로 생성되어야 한다. (AC-092-004)

### 시나리오 5 — 비용 예산 불변

- **Given** Naver/DART fetch 함수가 mock 처리된 fixture다.
- **When** bridge flag OFF/ON으로 각각 실행한다.
- **Then** flag ON 실행의 외부 fetch 호출 수는 flag OFF 대비 증가하지 않아야 한다. (AC-092-005)

### 시나리오 6 — adaptive threshold 연결성

- **Given** 동일 후보 fixture에서 threshold만 0.30과 0.70으로 다르게 고정한다.
- **When** 예측 생성 gate를 실행한다.
- **Then** 저장 후보 수가 달라져야 한다. 만약 정책상 threshold가 매수 실행 전용이면, 생성 후보 수가
  같아도 되지만 설정명과 로그가 execution-only임을 명시해야 한다. (AC-092-006)

### 시나리오 7 — 운영 누락 감시

- **Given** 장마감 이후인데 당일 `surge_actual_outcome` 또는 `surge_prediction_evaluation` row가 없다.
- **When** health helper를 실행한다.
- **Then** 누락 상태와 누락 테이블명을 반환해야 한다. (AC-092-007)

### 시나리오 8 — bridge 후보 수 상한 적용

- **Given** `scan_universe_bridge_max_candidates=20`, `scan_universe_bridge_pool_limits={"pool_c": 10}`로
  설정되어 있고, Pool C bridge scoring 최소 조건을 만족하는 후보가 15개 존재한다.
- **When** `scan_universe_bridge_candidates_enabled=true`로 bridge 후보 생성 함수를 실행한다.
- **Then** 반환되는 Pool C bridge 후보 수는 `scan_universe_bridge_pool_limits["pool_c"]`(10)를
  초과하지 않아야 하며, 전체 bridge 후보 수는 `scan_universe_bridge_max_candidates`(20)를
  초과하지 않아야 한다. (AC-092-004, REQ-AI092-004 상한 조건)

### 시나리오 9 — same-day 후보는 bridge 경로에서도 배제된다

- **Given** universe에만 있고 `merged`에는 없는 종목 Y가 있고, Y는 같은 날 이미 상한가 근접으로
  이동한 near-limit-up-carry 계열 same-day 후보로 판별된다.
- **When** bridge 후보 생성 함수가 실행된다.
- **Then** Y는 bridge 후보로 생성되더라도 표준 T-1 -> T predicted set에는 포함되지 않아야
  한다. (AC-092-008)

## §D. Edge Cases

- universe가 비어있는 날: bridge 후보 생성은 빈 목록으로 끝나야 한다.
- `entry_pool_map`에 없는 universe code: bridge 후보 대상에서 제외하거나 `existing`으로 기록해야 한다.
- `surge_metadata`가 손상된 기존 signal: 공식 평가 제외/포함 규칙은 기존 fail-safe를 유지해야 한다.
- snapshot migration 전 과거 평가 row: API는 기존 방식으로 fail-open해야 한다.

## §E. Definition of Done

- [ ] AC-092-001 통과.
- [ ] 평가 스냅샷 구현 및 AC-092-002 통과.
- [ ] bridge config 기본 OFF 및 AC-092-003 통과.
- [ ] bridge 후보화 구현 및 AC-092-004/005 통과.
- [ ] adaptive threshold 정책 확정 및 AC-092-006 통과.
- [ ] 운영 누락 감시 helper와 AC-092-007 통과.
- [ ] AC-092-008 통과.
- [ ] 기존 관련 회귀 테스트 통과.
- [ ] 배포 전 rollback 기준과 feature flag 기본값 확인.
