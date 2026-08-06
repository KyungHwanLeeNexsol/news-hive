# SPEC-AI-105 Acceptance Criteria

> GEARS 정규 문장 형식. 각 AC는 **볼드 WHEN/WHILE/WHERE 트리거 + 볼드 shall/shall not 절**로
> 구성한다.

## §A. AC 매트릭스 (REQ ↔ AC 매핑)

| AC ID | 대응 REQ | 심각도 |
|-------|----------|--------|
| AC-105-001 | REQ-AI105-002 | Must-Pass |
| AC-105-002 | REQ-AI105-002 | Must-Pass |
| AC-105-003 | REQ-AI105-001 | Must-Pass |
| AC-105-004 | REQ-AI105-001, REQ-AI105-006 | Must-Pass |
| AC-105-005 | REQ-AI105-003 | Must-Pass |
| AC-105-006 | REQ-AI105-003 | Must-Pass |
| AC-105-007 | REQ-AI105-005 | Must-Pass |
| AC-105-008 | REQ-AI105-006 | Must-Pass |
| AC-105-009 | REQ-AI105-006 | Must-Pass |
| AC-105-010 | REQ-AI105-004, REQ-AI105-007 | Should-Pass |

## §B. 인수 기준 (정규 문장)

### AC-105-001 — `surge_bridge_shadow_candidates`가 일자당 replace semantics로 저장된다

**When** `persist_bridge_shadow_candidates(db, trading_date, shadow_candidates)`가
동일 `trading_date`에 대해 두 번 연속 호출되면(예: 10:00 스캔 후 15:20 스캔), the
system **shall** 첫 호출의 레코드를 전량 삭제한 뒤 두 번째 호출의 결과만 남겨야 한다
(`SurgeUniverseMember.persist_universe_members()` 관례 계승).

- 검증 방법: 단위 테스트 — 동일 `trading_date`로 서로 다른 종목 집합을 두 번 저장한
  뒤, 최종 조회 결과가 두 번째 호출분과 정확히 일치함을 확인.

### AC-105-002 — 신규 테이블 스키마가 composite PK `(trading_date, stock_code)`를 사용한다

**When** `SurgeBridgeShadowCandidate` 모델이 정의되면, the system **shall**
`trading_date`와 `stock_code`를 composite primary key로, `entry_pool`(String)과
`bridge_score`(Float, not null)를 데이터 컬럼으로 선언해야 한다.

- 검증 방법: `grep -A 15 "class SurgeBridgeShadowCandidate" backend/app/models/surge_bridge_shadow_candidate.py`로
  PK 선언과 컬럼 타입을 확인.

### AC-105-003 — shadow 계측이 마스터 스위치를 override한 config 사본으로만 기존 함수를 재호출한다

**When** `scan_universe_bridge_shadow_enabled=true`이고 실제 마스터 스위치가
`false`인 상태로 `gather_surge_candidates()`가 실행되면, the system **shall**
`generate_scan_universe_bridge_candidates()`를 마스터 스위치만 `true`로 override한
config 사본으로 호출해 shadow 후보를 계산해야 하며, **shall not** 이 함수의 내부
스코어링 로직(`_BRIDGE_MIN_SCORE`, pool_a/pool_c 산식)을 재구현하거나 복제해서는
안 된다.

- 검증 방법: 단위 테스트 — 실제 함수 호출을 mock/spy로 감시해 동일 함수 참조가
  shadow 경로에서도 사용됨을 확인(별도 복제 함수 부재 확인).

### AC-105-004 — shadow 계측이 `qualified`/`merged`/실제 마스터 스위치 값에 영향을 주지 않는다

**While** `scan_universe_bridge_shadow_enabled=true`인 동안, the system **shall not**
shadow 후보를 `qualified`나 `merged`에 합류시켜서는 안 되며, **shall not** 원본
`config.scan_universe_bridge_candidates_enabled` 값을 변경해서는 안 된다.

- 검증 방법: 단위 테스트 — `scan_universe_bridge_shadow_enabled=true`로 전체
  `gather_surge_candidates()` 실행 경로를 호출한 뒤, `qualified`/`merged`의 코드
  집합이 shadow_enabled=false일 때와 바이트 동등함을 확인 + 실행 후
  `config.scan_universe_bridge_candidates_enabled == False`를 재확인.

### AC-105-005 — `analyze_bridge_shadow_precision_by_date()`가 pool_a/pool_c를 분리 반환한다

**When** `analyze_bridge_shadow_precision_by_date(db, trading_date)`가 고정
fixture(known `surge_bridge_shadow_candidates` + `SurgeActualOutcome` 행)로
호출되면, the system **shall** `pool_a`와 `pool_c` 각각에 대해 독립된
`{total: int, surge_count: int, precision: float | None}` 딕셔너리를 반환해야 하며,
**shall not** 두 pool을 합산한 blended 키를 반환 값에 포함해서는 안 된다.

- 검증 방법: 단위 테스트 — 고정 fixture에 대해 pool_a/pool_c 각각의 계산값이 수동
  산출값과 일치하는지 검증 + 반환 딕셔너리 키 집합이 정확히 `{"pool_a", "pool_c"}`임을
  확인(추가 키 없음).

### AC-105-006 — 특정 거래일 특정 pool의 `total==0`이면 `precision`이 `None`이다

**When** 특정 거래일 특정 pool에 소속된 shadow 후보 행이 0건이면, the system
**shall** 해당 pool의 `precision`을 `None`으로 반환해야 한다. **While** 이 조건이
성립하는 동안, the system **shall not** 0으로 나누기 예외를 발생시켜서는 안 된다.

- 검증 방법: 단위 테스트 — 빈 pool fixture 주입, 예외 없이 `precision is None` 확인
  (pool_a/pool_c 각각 독립적으로 테스트).

### AC-105-007 — 리포트에 pool별 shadow 정밀도가 blended 없이 병기된다

**When** `scripts/measure_universe_detection_gap_report.py`가 실행되어 마크다운
리포트를 생성하면, the report script **shall** "Bridge Shadow 정밀도" 섹션에
`pool_a`/`pool_c` 정밀도를 별도 행으로 표시해야 하며, **shall not** 두 pool을 합산한
단일 수치만 표시해서는 안 된다.

- 검증 방법: 리포트 실행 후 생성된 마크다운을 파싱해 `pool_a`/`pool_c` 두 행이 모두
  존재함을 확인(테스트).

### AC-105-008 — pool_b는 shadow 계측 대상에서 하드코딩으로 배제된다

**When** `scan_universe_bridge_pool_b_enabled=true`(SPEC-AI-102 하위 플래그가 이미
켜진 상태)이고 `scan_universe_bridge_shadow_enabled=true`이면, the system **shall
not** shadow 계측 결과에 `entry_pool == "pool_b"`인 후보를 포함해서는 안 되며,
**shall not** shadow 경로가 `fetch_stock_price_history_batch_sync`(pool_b bridge의
가격이력 배치 조회)를 호출해서는 안 된다.

- 검증 방법: 단위 테스트 — `scan_universe_bridge_pool_b_enabled=True`로 설정한
  fixture에서 shadow 계측을 실행하고, (a) 반환/영속화된 shadow 후보에 `pool_b`
  entry가 없음, (b) `fetch_stock_price_history_batch_sync`가 호출되지 않았음을
  mock 호출 카운트로 확인.

### AC-105-009 — 기존 회귀 테스트 스위트(3개 파일)가 shadow 계측 배포 후에도 전량 통과한다

**While** 본 SPEC의 shadow 계측 배포(REQ-AI105-001/002)가 적용되는 동안, the system
**shall** 기존 bridge/quota/pool_b 관련 테스트 스위트(`test_spec_ai_092.py`,
`test_spec_ai_096.py`, `test_spec_ai_102.py`) 3개 파일 전량을 통과시켜야 한다.

- 검증 방법: `uv run pytest tests/test_spec_ai_092.py tests/test_spec_ai_096.py
  tests/test_spec_ai_102.py -q`

### AC-105-010 — Pool D 무관성 정정과 활성화 게이트 절차가 문서화되고 CHANGELOG에 경고가 기록된다

**When** plan-phase 산출물이 완성되면, plan.md's §C section **shall** REQ-AI105-004
(Pool D 무관성 정정)와 REQ-AI105-007(관측기간 + 기준선 비교 + 좁은 범위 우선
활성화)의 복합 절차를 문서화해야 하며, CHANGELOG.md의 `[Unreleased]` 섹션 **shall**
bridge shadow 전환 경고 항목을 포함해야 한다.

- 검증 방법: `grep -A 25 "^## C\. 활성화 게이트 절차" .moai/specs/SPEC-AI-105/plan.md`로
  §C 섹션 헤딩과 "pool_a"/"pool_c"/기준선 키워드 포함 여부를 기계적으로 확인 +
  `grep "scan_universe_bridge_shadow" CHANGELOG.md`로 경고 존재를 확인. 절차 서술의
  논리적 완결성은 육안 리뷰를 보조 수단으로만 사용한다.

## Scenarios (Given-When-Then, 최소 2)

### 시나리오 1 — shadow 계측이 정상 관측일에 pool별로 분리 저장·분석된다

**Given** `scan_universe_bridge_shadow_enabled=true`, 실제 마스터 스위치는 `false`로
배포되었고, 오늘 `_universe_codes`에 pool_a 소속 2종목(`005930`, `000660`)과 pool_c
소속 2종목(`035420`, `068270`)이 `merged`에 없는 상태로 존재하며, `005930`(impact_score=45)과
`035420`(어제 change_rate=8.0%)만 bridge 최소점수(0.3)를 넘는다.

**When** `gather_surge_candidates()`가 실행된다.

**Then** `surge_bridge_shadow_candidates` 테이블에 `005930`(pool_a)과 `035420`(pool_c)
2행만 저장되며, `qualified`/`merged`에는 이 2종목이 순수 shadow 사유만으로는
등장하지 않는다(AC-105-004). 이후 `005930`이 오늘 실제 급등했다면
`analyze_bridge_shadow_precision_by_date()`는 `{"pool_a": {"total": 1, "surge_count": 1,
"precision": 1.0}, "pool_c": {"total": 1, "surge_count": 0, "precision": 0.0}}`을
반환한다(AC-105-005).

### 시나리오 2 — pool_a/pool_c 모두 shadow 후보가 0건인 날 (division-by-zero guard)

**Given** `scan_universe_bridge_shadow_enabled=true`이지만 오늘 pool_a/pool_c 소속
종목 중 `merged`에 없는 종목이 하나도 없다(모두 이미 1차 탐지기가 잡았거나 유니버스
자체가 비었다).

**When** `analyze_bridge_shadow_precision_by_date(db, today)`를 호출한다.

**Then** 반환값이 `{"pool_a": {"total": 0, "surge_count": 0, "precision": None},
"pool_c": {"total": 0, "surge_count": 0, "precision": None}}`이다 — 0으로 나누기
예외가 발생하지 않는다(AC-105-006).

### 시나리오 3 — pool_b 하위 플래그가 켜져 있어도 shadow는 pool_b를 배제한다

**Given** `scan_universe_bridge_pool_b_enabled=true`(SPEC-AI-102가 이미 프로덕션에서
켜진 상태를 가정)이고 `scan_universe_bridge_shadow_enabled=true`이며, 오늘
`_entry_pool_map`에 pool_b 소속 종목이 3개 존재한다.

**When** `gather_surge_candidates()`가 실행된다.

**Then** `surge_bridge_shadow_candidates`에는 pool_b 소속 종목이 단 하나도 저장되지
않으며, `fetch_stock_price_history_batch_sync`는 shadow 경로에서 호출되지 않는다
(AC-105-008) — 실제(non-shadow) bridge 경로가 이미 pool_b를 처리 중이더라도 그
호출과는 독립적으로 shadow 경로는 하드코딩된 배제를 유지한다.

### 시나리오 4 — shadow 계측 배포가 기존 회귀 스위트에 영향을 주지 않음

**Given** SPEC-AI-105 배포 전 `test_spec_ai_092.py`/`test_spec_ai_096.py`/
`test_spec_ai_102.py`가 전량 통과하고 있었다.

**When** `scan_universe_bridge_shadow_enabled`를 `false`에서 `true`로 전환한 뒤
동일 테스트 스위트를 재실행한다.

**Then** 3개 기존 회귀 테스트 파일이 전량 통과한다(AC-105-009) — bridge 마스터
스위치·스코어링 산식·quota 배분은 이 SPEC이 건드리지 않으므로 기존 테스트가 가정한
전제와 무관하게 통과해야 한다.

## Edge Cases

- **`generate_scan_universe_bridge_candidates()`(shadow 호출)가 예외를 던지는 날**:
  기존 non-shadow bridge 호출부와 동일하게 `try/except` fail-open으로 로그만 남기고
  무시한다 — `gather_surge_candidates()` 전체를 중단시키지 않는다(TASK-002 5항).
- **shadow 후보 코드가 같은 사이클에서 실제(non-shadow) bridge에 의해서도 선택되는
  경우**(마스터 스위치가 어느 시점에 이미 켜져 있는 전환기 상태): shadow 저장은
  `qualified`/`merged`와 완전히 독립적인 별도 테이블이므로 이중 계상 위험이 없다 —
  shadow 테이블은 실제 채택 여부와 무관하게 "채택되었다면 이랬을 것"만 기록한다.
- **`_universe_codes`/`entry_pool_map`이 빈 상태인 날**(유니버스 빌드 실패):
  `generate_scan_universe_bridge_candidates()`가 이미 빈 리스트를 반환하는 기존
  동작(candidate_codes가 비면 조기 반환, `:5820-5821`)을 shadow 경로도 그대로
  상속한다 — 별도 처리 불필요.

## Quality Gate Criteria

- `uv run pytest tests/ --tb=short -q -m "not slow"` 전체 통과(CLAUDE.local.md 검증
  명령 계승).
- `uv run ruff check . && uv run mypy app/` 신규 결함 0건(기존 baseline 결함은 예외).
- 신규 함수 `persist_bridge_shadow_candidates()`, `analyze_bridge_shadow_precision_by_date()`에
  대한 단위 테스트 커버리지 100%(division-by-zero guard, pool_b 배제 분기 포함).
- `git diff --name-only`에 `surge_trading_service.py`, 8개 탐지기 스코어링 함수,
  `compute_ensemble_score()`, `generate_scan_universe_bridge_candidates()` 함수 본체가
  포함되지 않음(호출부 wiring 추가만 허용).

## Definition of Done

- [ ] AC-105-001 ~ AC-105-010 전량 PASS
- [ ] 4개 시나리오 전량 재현 검증
- [ ] plan.md §C 활성화 게이트 절차 최종본 기록(Pool D 무관성 정정 포함)
- [ ] CHANGELOG.md `[Unreleased]`에 shadow 계측 전환 경고 항목 추가
- [ ] `git diff --name-only`가 plan.md §A.1 PRESERVE 목록과 배치되지 않음을 리뷰로 확인
