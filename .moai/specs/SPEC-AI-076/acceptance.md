# SPEC-AI-076 Acceptance Criteria — 스캔 유니버스 풀 절단 크라우딩아웃 교정

형식: Given-When-Then. 모든 기준은 관찰 가능한 사실(entry_pool별 카운트, `len(final_universe)`, 반환 dict 키,
로그)로 고정한다. manager-ddd가 이를 그대로 characterization test로 전환할 수 있도록 구체 수치로 기술.

전제: `build_scan_universe(db, config, existing_codes)`는 `(final_universe, entry_pool_map, pool_counts)`를
반환한다. `entry_pool_map[code] ∈ {"pool_a","pool_b","pool_c","existing"}`. 테스트는 Pool A/B/C 소스
(Disclosure/volume leaders/SurgeActualOutcome)를 mock하여 raw 후보 수를 통제한다.

---

## AC-076-001 (REQ-001/003) — 굶주림 교정: 07-08형 replay [P0, 재현 우선]

- **Given** `config.max_scan_universe = 150`, `config.pool_c_min_slots = 30`, `config.pool_b_min_slots = 20`,
  그리고 mock으로 Pool A raw = 232개 코드, Pool B raw = 0개, Pool C raw = 52개(모두 서로소, `existing = 빈
  집합`)일 때
- **When** `build_scan_universe`를 호출하면
- **Then** `final_universe`에서 `entry_pool_map[c]=="pool_c"`인 코드 수가 **>= 30**이어야 하고
  (현행 코드에서는 정확히 0 — 재현 우선 실패 지점),
- **And** `len(final_universe) == 150`,
- **And** `entry_pool_map[c]=="pool_a"`인 코드 수가 **<= 120**(= 150 − reserved_c 30 − reserved_b 0)이어야 한다.
- **재현 우선(Rule 4)**: 수정 전 이 테스트는 "pool_c 카운트 == 0"으로 현행 거동을 포착하며 위 단언(>=30)에서
  실패해야 한다. 수정 후 통과.

## AC-076-002 (REQ-001) — 비굶주림 일반 속성 (파라미터화)

- **Given** `max_scan_universe = 150`, floors `(pool_b_min_slots=F_b, pool_c_min_slots=F_c)`, 그리고 각 풀 raw
  = `(R_a, R_b, R_c)`로 `R_a + R_b + R_c > 150`(절단 압력)이며 `F_b + F_c <= 150`인 여러 조합
  (예: (200,10,40)/(160,0,60)/(300,25,25))일 때
- **When** `build_scan_universe`를 호출하면
- **Then** 각 풀 P ∈ {B, C}에 대해 `final_universe`의 P 대표 수 >= `min(R_p, F_p)`이어야 한다(상위 풀 크기와
  무관).

## AC-076-003 (REQ-002) — 비용 상한 보존

- **Given** 임의의 Pool A/B/C raw 조합(절단 압력 유/무 모두)일 때
- **When** `build_scan_universe`를 호출하면
- **Then** `len(final_universe) <= config.max_scan_universe`가 항상 성립하고,
- **And** 함수는 `config.max_scan_universe`(150)와 Pool B `_min_ratio`(2.0) 상수를 읽기만 하며 수정/상향하지
  않는다(코드 diff로 확인 — 두 상수 리터럴 변경 0).

## AC-076-004 (REQ-004) — 절단 압력 없음: A/B/C 전 후보 포함 + 집합 동등성

**[HARD] 정정 (Human 결정, 2026-07-09)**: 현행 코드(`:4278-4293`)는 `existing_codes`를 먼저 전량
`entry_pool_map`에 등록한 뒤 "미등록 existing만" 병합하는 필터를 돌리므로, 이 필터는 **항상 빈 리스트**를
반환한다 — 즉 `existing_codes`는 현재도 `final_universe`에 실제로는 포함되지 않는 기존(pre-existing) 동작이다.
이는 SPEC-AI-076의 스캔 범위(A/B/C 배분) 밖의 별개 이슈이므로, 본 SPEC은 이 동작을 **그대로 보존**하고 아래
기준도 그에 맞춘다. existing 자체를 포함시키는 교정은 별도 후속 SPEC 후보로 남긴다(Exclusions 참조).

- **Given** Pool A raw = 10, Pool B raw = 8, Pool C raw = 12, `existing` = 5개(중복 없음, A/B/C와도 중복
  없음) → A+B+C 합 30 <= `max_scan_universe = 150`, floors = (20, 30)일 때
- **When** `build_scan_universe`를 호출하면
- **Then** `final_universe`의 종목코드 **집합**이 Pool A/B/C 3개 소스의 합집합(30개 전부)과 동일하고(어떤
  A/B/C 풀도 탈락 없음), **existing 5개는 현행과 동일하게 포함되지 않는다**(집합 크기 정확히 30, 35 아님),
- **And** `entry_pool_map`이 각 A/B/C 코드에 원 소속 풀을 그대로 태깅한다(기존 거동과 집합·태깅 동일).

## AC-076-005 (REQ-004) — floors=0 레거시 동등성 [백워드 호환 탈출구]

- **Given** `pool_b_min_slots = 0` 그리고 `pool_c_min_slots = 0`, 그리고 AC-076-001과 동일한 절단 압력 입력
  (A=232, B=0, C=52, cap=150)일 때
- **When** `build_scan_universe`를 호출하면
- **Then** `final_universe`가 기존 엄격 concat-then-slice(`dedup(pool_a+pool_b+pool_c+existing)[:150]`)와
  **정확히 동일한 종목코드 리스트**(순서 포함)를 반환해야 한다(= Pool C 대표 0, 사실상 `pool_a[:150]`).

## AC-076-006 (REQ-005) — post-truncation 관측성 (스키마 0)

- **Given** AC-076-001 입력(A=232, B=0, C=52, cap=150, F_c=30)일 때
- **When** `build_scan_universe`를 호출하면
- **Then** 반환 `pool_counts`가 **raw 키를 보존**하고(`pool_a==232`, `pool_b==0`, `pool_c==52`),
- **And** 신규 scanned 키를 포함한다(`pool_a_scanned==120`, `pool_b_scanned==0`, `pool_c_scanned==30`,
  합 == `len(final_universe)==150`),
- **And** 최종 로그 라인에 raw 대비 scanned가 함께 출력된다(굶주림이 로그에서 관측 가능).

## AC-076-007 (REQ-005) — SurgeUniversePoolHistory raw 의미 불변 (회귀 가드)

- **Given** `gather_surge_candidates` 경로(`surge_detector.py:1933` 호출부)가 `build_scan_universe` 결과를
  `persist_pool_counts`로 영속할 때
- **When** 스캔이 절단 압력 하에서 실행되면
- **Then** `SurgeUniversePoolHistory.pool_a/b/c_count`에 저장되는 값은 **raw pre-truncation 수**(예: pool_c=52)
  로 유지되고 scanned 값으로 대체되지 않는다,
- **And** `get_pool_counts_for_date`/`evaluate_surge_predictions`의 pool_counts 소비 거동은 diff 0이다
  (기존 065/평가 테스트 무회귀).

## AC-076-008 (REQ-007) — floor 설정 로딩 + 안전 clamp

- **Given** `pool_b_min_slots + pool_c_min_slots > max_scan_universe`인 오설정(예: 100 + 100, cap 150)일 때
- **When** `build_scan_universe`를 호출하면
- **Then** 함수가 예외 없이 완료되고 `len(final_universe) <= 150`을 유지하며(예약 합을 안전 축소),
- **And** 경고 로그가 남는다,
- **And** 정상 설정(합 <= cap)에서는 floor가 설정값 그대로 적용된다(AC-076-001로 확인).

## AC-076-009 (REQ-006) — 회귀 및 품질 게이트

- **Given** 변경 적용 후
- **When** `cd backend && uv run pytest tests/test_spec_ai_065.py tests/test_spec_ai_074.py
  tests/test_surge_universe_members.py tests/test_surge_universe_pool_bugfix.py -q` 및 전체 스위트(`-n 4`
  포함)를 실행하면
- **Then** 기존 테스트 전량 통과, 신규 characterization 통과, 신규/변경 로직 커버리지 85%+, `ruff` 무경고,
  `mypy app/` 무오류.

## AC-076-010 (Exclusions) — 무변경 보장

- **Given** 전체 변경 diff일 때
- **Then** 다음이 모두 성립: (a) 탐지기/`compute_ensemble_score`/신호 발신/임계/가중치 diff 0; (b) Pool A/B/C
  후보 소싱 쿼리(Disclosure/volume leaders+stocks 교집합/SurgeActualOutcome) diff 0; (c) 매수·포트폴리오 로직
  diff 0(AI-043 예측 기록 모드); (d) 신규 DB 테이블/컬럼/마이그레이션 0; (e) `max_scan_universe`/`_min_ratio`
  상수 리터럴 diff 0; (f) 과거 데이터 백필/재계산 0.

---

## Definition of Done

- [ ] AC-076-001 ~ AC-076-010 전부 충족.
- [ ] 재현 우선(Rule 4): 수정 전 실패 테스트(Pool C 대표=0 포착) 작성·확인 → 수정 후 통과.
- [ ] quota 배분이 비굶주림·비용 상한·우선순위 잔여·레거시 동등성(floors=0)을 동시에 만족.
- [ ] post-truncation 관측성(반환/로그) 추가, raw 카운트·영속 의미 불변(스키마 0).
- [ ] `:4183`/`:4217` 불변 주석 갱신(배분=quota SPEC-AI-076 소유, cap/ratio 불변) + `@MX:ANCHOR/NOTE`.
- [ ] 전체 백엔드 스위트(`-n 4` 포함) 회귀 0, 커버리지 85%+, `ruff`/`mypy` 무오류.
