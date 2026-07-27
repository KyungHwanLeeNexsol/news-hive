# SPEC-AI-089 Acceptance Criteria

## AC 매트릭스

| AC | 요구사항 | 검증 방법 |
|---|---|---|
| AC-089-001 | 측정 계측 활성화 시 유니버스↔탐지망 간극이 풀별(A/B/C[/D])로 정량 산출된다 | pytest — `measure_universe_detection_gap()` 단위 테스트 |
| AC-089-002 | 측정 계측 비활성화(기본값) 시 `gather_surge_candidates()` 출력이 M1 이전과 바이트 동등하다 | pytest — 시그널 생성 스냅샷 비교 |
| AC-089-003 | REQ-002 귀속 분석이 표본 거래일에 대해 신규 마이그레이션 없이 산출된다 | pytest — 조인 쿼리 단위 테스트(fixture 데이터) |
| AC-089-004 | (REQ-AI089-004) 측정 계측 활성화 시 `gather_surge_candidates()` 소요 시간이 (a) 비활성 대비 5% 이내 증가하고 (b) `_GATHER_TIMEOUT_S`(1200초)보다 최소 120초 낮은 수준(1080초 이하)을 유지한다 | 수동/스테이징 측정 — 활성/비활성 소요 시간 비교(백분율·절대값 산출), §F 자가검증 |
| AC-089-005 | M2 결정 게이트 없이 M3+ 코드 변경이 병합되지 않는다 | 커밋 이력 검토 — M1 커밋에 탐지기 로직 수정 부재 확인 |
| AC-089-006 | (REQ-AI089-006) 앙상블 가중치 합=1.0 불변식이 M1 범위에서 유지된다 | pytest — `validate_ensemble_weights` 기존 테스트 재실행 |
| AC-089-007 | (REQ-AI089-007) 측정 계측 활성화 시 측정 실행 여부·소요 시간·풀별 간극 요약(raw/미탐지망 커버 개수)이 단일 로그 라인으로 기록되며, 신규 스키마 도입 없이·종목별 상세 로그 없이 기록된다 | pytest — 로그 캡처(caplog) 단위 테스트, 로그 라인 필드 검증 |
| AC-089-008 | (REQ-AI089-003) 측정 계측 활성화(`universe_gap_measurement_enabled=True`) 상태로 `gather_surge_candidates()`를 실행해도, 반환된 탐지 후보 집합(`SurgeCandidate` 목록)·앙상블 점수·발행 시그널 수·병합된 탐지 후보(`merged`) 내용이 계측 비활성화(기본값) 상태의 동일 fixture 실행 결과와 완전히 동일하다 — REQ-AI089-003의 ACTIVE-state 불변식(계측이 ON이어도 탐지 파이프라인은 무영향)을 직접 검증 | pytest — 동일 fixture에 대해 계측 ON/OFF 두 실행을 각각 수행한 뒤 `SurgeCandidate` 목록을 diff 비교(diff 없음을 단언) |
| 기존 회귀 테스트 전체 통과 | `cd backend && uv run pytest tests/ -m "not slow"` |

## Given-When-Then 시나리오

### 시나리오 1 — 계측 활성화 시 간극 측정 정확성

- **Given** `universe_gap_measurement_enabled=True`로 설정된 `SurgeDetectionConfig`와, Pool A에
  3개 종목, Pool B에 2개 종목이 있고 그중 Pool A의 1개 종목만 `merged`(탐지망)에 포함된 고정
  fixture 데이터가 있다.
- **When** `measure_universe_detection_gap(universe_codes, entry_pool_map, merged)`을 호출한다.
- **Then** 반환값은 `pool_a_total=3`, `pool_a_covered=1`(또는 동등 의미의 필드), `pool_b_total=2`,
  `pool_b_covered=0`을 포함하며, 신규 DB 쓰기가 발생하지 않는다(mock 세션으로 검증).

### 시나리오 2 — 계측 비활성화 시 바이트 동등성

- **Given** `universe_gap_measurement_enabled=False`(기본값)로 설정된 config와 기존 SPEC-AI-086/
  087 회귀 테스트 fixture.
- **When** `gather_surge_candidates()`를 실행한다.
- **Then** 반환된 `SurgeCandidate` 목록의 순서·필드값이 본 SPEC 적용 이전 커밋의 동일 fixture
  실행 결과와 정확히 일치한다(diff 없음).

### 시나리오 3 — REQ-002 귀속 분석의 4가지 분류

- **Given** 표본일에 무시그널 실제급등 종목 4개가 있고, 각각 (a) Pool A에만 속함, (b) Pool B에만
  속함, (c) Pool C에만 속함, (d) 어느 풀에도 속하지 않음(소스 부재형) 상태다.
- **When** REQ-002 귀속 분석을 실행한다.
- **Then** 4개 종목 각각이 올바른 풀 카테고리로 분류되고, (d) 케이스는 명시적으로 "소스 부재
  (유니버스 배선으로 해결되지 않음)"으로 표시된다(design.md § 열린 질문 3과 정합).

### 시나리오 4 — 관측성 로그 라인 기록 (REQ-007)

- **Given** `universe_gap_measurement_enabled=True`로 설정된 config와, 측정이 정상적으로
  실행되어 `measure_universe_detection_gap()`의 반환값이 확보된 상태다.
- **When** `gather_surge_candidates()`의 측정 훅이 실행을 완료한다.
- **Then** 측정 실행 여부(실행됨/스킵됨)·소요 시간(초)·풀별 raw/미탐지망 커버 개수 요약을
  포함하는 로그 라인이 정확히 1줄 기록되며, 종목별 상세 로그(개별 종목 코드 나열)는 기록되지
  않고, 신규 DB 스키마에 대한 쓰기도 발생하지 않는다(caplog로 검증).

### 시나리오 5 — 계측 활성화(ACTIVE) 상태에서도 탐지 결과 불변 (REQ-AI089-003 [HARD])

- **Given** SPEC-AI-086/087 회귀 테스트와 동일한 고정 fixture(시나리오 2에서 사용한 fixture)가
  있고, 이 fixture를 두 가지 config로 각각 실행할 준비가 되어 있다: (1)
  `universe_gap_measurement_enabled=False`(기본값, 계측 비활성) (2)
  `universe_gap_measurement_enabled=True`(계측 활성).
- **When** 동일 fixture에 대해 `gather_surge_candidates()`를 두 config 각각으로 1회씩 실행한다.
- **Then** 두 실행에서 반환된 `SurgeCandidate` 목록의 순서·필드값, 앙상블 점수, 발행 시그널 수,
  그리고 병합된 탐지 후보(`merged`) 내용이 정확히 일치한다(diff 없음) — 즉 측정 계측이 ON으로
  전환되어도 기존 1차 탐지기들의 후보 집합·앙상블 점수·발행 시그널 수·병합된 탐지 후보 내용이
  "어떤 방식으로도" 변경되지 않는다는 REQ-AI089-003의 ACTIVE-state 불변식이 실측으로 확인된다.
  이는 계측 비활성 시의 바이트 동등성(시나리오 2)을 검증하는 것과 별개로, 계측이 실제로 켜진
  상태에서도 동일한 불변식이 유지됨을 직접 검증하는 시나리오다.

## 엣지 케이스

- **모든 풀이 비어있는 날** (Pool A/B/C 전부 0건) — `measure_universe_detection_gap`이 0으로
  나누기 없이 안전하게 완료되어야 한다(division-by-zero guard).
- **`merged`이 비어있는 날** (탐지 후보가 하나도 없는 날) — 모든 풀의 `*_covered`가 0으로
  계산되고 예외 없이 완료.
- **DB 조인 대상 테이블에 표본일 데이터가 없는 경우** (REQ-002) — 빈 리포트를 생성하고 "표본
  데이터 없음"을 명시적으로 기록, 조용히 스킵하지 않음.
- **`entry_pool_map`에 없는 코드가 `merged`에 있는 경우** (existing-only 종목) — `existing`
  풀로 분류되며 A/B/C 카운트에 영향 없음(기존 `build_scan_universe` 시맨틱과 일치).

## 품질 게이트 기준

- 신규 함수(`measure_universe_detection_gap`)는 순수 함수 — 단위 테스트에서 실제 DB 세션 없이
  mock/fixture로 검증 가능해야 한다.
- `ruff check` / `mypy` 클린 (backend 표준 게이트, CLAUDE.local.md 참조).
- 신규 코드에 대한 characterization/specification 테스트 존재 — TRUST 5 Tested 원칙.
- 커밋 메시지는 Conventional Commits + `git_commit_messages: ko` 설정에 따라 한국어 본문 허용.

## Definition of Done (M1 범위)

- [ ] `measure_universe_detection_gap()` 구현 + 단위 테스트 통과 (AC-089-001)
- [ ] `gather_surge_candidates()` 훅 추가, 플래그 기본 OFF, 바이트 동등성 확인 (AC-089-002)
- [ ] REQ-002 귀속 분석 스크립트/부가 로직 구현 + 표본 거래일 실행 결과 확보 (AC-089-003)
- [ ] 비용 예산 불변식 실측 증거 확보 (AC-089-004)
- [ ] 관측성 로그 라인 구현 + 단위 테스트 통과 (AC-089-007)
- [ ] 계측 활성화(ACTIVE) 상태에서도 탐지 결과가 계측 비활성 상태와 완전히 동일함을 확인
      (AC-089-008, REQ-AI089-003 [HARD] ACTIVE-state 불변식 검증)
- [ ] M1 리포트 (`.moai/reports/surge-universe-gap/`) 작성, 연구 질문 1-3 실측 답 포함
- [ ] 기존 회귀 테스트 전체 통과: `cd backend && uv run pytest tests/ -m "not slow"`
- [ ] M2 결정 게이트를 위한 Report-Before-Ask 형태의 요약 준비 (orchestrator 책임, M1 커밋 범위
      밖이지만 M1 완료의 필수 후속 단계로 acceptance에 명시)

DoD는 M1 범위에 한정된다. M3+(조건부 배선 구현)의 DoD는 M2 결정 이후 별도로 정의된다(plan.md
§C M3+ 참고 — 사전 확정하지 않음).
