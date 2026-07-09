# SPEC-AI-077 Acceptance Criteria — near_limit_up NULL 시총 굶주림 교정

형식: Given-When-Then. 모든 기준은 관찰 가능한 사실(`fetch_stock_price_history_sync` 호출 종목코드 집합, 생성
시그널의 stock_id 집합, 총 fetch 수, 로그)로 고정한다. manager-ddd가 이를 그대로 characterization test로 전환할 수
있도록 구체 수치로 기술.

전제: `detect_near_limit_up_carries(db, config)`는 후보 풀 각 종목에 `fetch_stock_price_history_sync(code)`를
호출한다(`max_signals_per_day=None` 기본값이라 후보 SET 전량 fetch). 테스트는 `_make_stock(db, code, name,
market_cap=...)`로 non-null/NULL 종목을 만들고 `fetch_stock_price_history_sync`를 mock해 change_rate와 fetch 대상을
통제한다. **"후보 SET"의 관측 프록시 = mock의 호출 종목코드 집합**(= 실제 fetch된 종목 = 평가된 후보).

명명 규약: floor는 **절대 슬롯 수**(`null_cap_min_slots`), 즉 "NULL 후보가 M개일 때 후보 SET은 `min(M,
null_cap_min_slots)`개 이상의 NULL 종목을 포함"한다(작업 지시의 `floor(reserved_null_pct * C)` 백분율 표현과 동치의
절대-슬롯 형태 — AI-076 `pool_c_min_slots` 관례 계승).

---

## AC-077-001 (REQ-001/003/007) — 굶주림 교정: 라이브형 replay [P0, 재현 우선]

- **Given** `config.max_stocks_to_check = 3`, `config.null_cap_min_slots = 1`, 그리고 non-null 시총 종목 4개
  (`market_cap` 1000/900/800/700억, 모두 T-1 +27% history mock) + NULL 시총 종목 2개(`market_cap=None`, +27% mock),
  `existing`(오늘 기존 시그널) 없음일 때
- **When** `detect_near_limit_up_carries(db, cfg)`를 호출하면
- **Then** `fetch_stock_price_history_sync`가 **NULL 시총 종목 코드에 대해 >= 1회** 호출되고(= NULL 후보 도달 수
  >= `min(2, 1)` = 1), 생성 시그널에 NULL 종목이 >= 1건 포함된다,
- **And** 총 fetch 종목 수 <= 3(비용 상한),
- **재현 우선(Rule 4)**: 수정 **전** 현행 `nullslast`+`limit(3)`는 non-null 4개 중 상위 3개(1000/900/800)만
  반환하고 NULL 종목은 0개 fetch → "NULL 종목 fetch 수 == 0"으로 현행 거동을 포착하며 위 단언(>= 1)에서 **실패**해야
  한다. 수정 후 통과.

## AC-077-002 (REQ-001) — 비굶주림 일반 속성 (파라미터화)

- **Given** `max_stocks_to_check = C`, `null_cap_min_slots = F`, non-null 후보 N개 + NULL 후보 M개(모두 near-limit-up
  mock)로 `N >= C`(절단 압력) 그리고 `F <= C`인 여러 조합(예: `(C,F,N,M)` = (3,1,5,3)/(3,2,4,4)/(4,2,10,5))일 때
- **When** `detect_near_limit_up_carries`를 호출하면
- **Then** NULL 시총 종목의 후보 SET 대표 수(= NULL 코드 fetch 수)가 **>= `min(M, F)`**이어야 한다(non-null 후보
  수 N과 무관).

## AC-077-003 (REQ-002) — 비용 상한 보존

- **Given** 임의의 non-null/NULL 후보 조합(절단 압력 유/무 모두)일 때
- **When** `detect_near_limit_up_carries`를 호출하면
- **Then** 총 fetch 종목 수 <= `config.max_stocks_to_check`가 항상 성립하고,
- **And** 후보 선정은 `max_stocks_to_check`(1200) 상수를 읽기만 하며 상향/제거하지 않는다(코드 diff로 확인 —
  `max_stocks_to_check` 리터럴 변경 0, 후보 풀에 총 상한 `.limit()`(또는 등가 절단) 유지).

## AC-077-004 (REQ-003) — floor 예약 후 non-null 우선 잔여 배분

- **Given** `max_stocks_to_check = 10`, `null_cap_min_slots = 2`, non-null 후보 3개(모두 near-limit-up mock) + NULL
  후보 8개(절단 압력 있음: 3+8 > 10)일 때
- **When** `detect_near_limit_up_carries`를 호출하면
- **Then** non-null 3개 **전부** 후보 SET에 포함되고(미달 non-null이 우선 충당),
- **And** NULL 후보 대표 수 = `min(8, 10−3)` = 7(>= 예약 `min(8,2)`=2, 남은 슬롯 환원),
- **And** 총 fetch = 10.

## AC-077-005 (REQ-005) — 절단 압력 없음: 전 후보 포함 + 집합 동등성

- **Given** non-null 후보 3개 + NULL 후보 4개(중복 없음), `max_stocks_to_check = 150`(절단 압력 없음, 7 <= 150),
  `null_cap_min_slots = 2`일 때
- **When** `detect_near_limit_up_carries`를 호출하면
- **Then** 후보 SET(= fetch된 종목코드 **집합**)이 7개 종목 전부와 동일하고(어떤 그룹도 탈락 없음),
- **And** non-null 3개·NULL 4개가 모두 fetch된다(기존 거동과 집합 동일).

## AC-077-006 (REQ-005) — null_cap_min_slots=0 레거시 동등성 [백워드 호환 탈출구]

- **Given** `null_cap_min_slots = 0`, 그리고 AC-077-001과 동일한 절단 압력 입력(non-null 4개 1000/900/800/700억,
  NULL 2개, `max_stocks_to_check = 3`)일 때
- **When** `detect_near_limit_up_carries`를 호출하면
- **Then** 후보 SET(= fetch된 종목코드 집합)이 기존 레거시 `nullslast(market_cap.desc()).limit(3)` 결과와 **정확히
  동일**해야 한다(= non-null 상위 3개 1000/900/800만 fetch, NULL 0개 — 즉 굶주림 거동 복원). 로테이션·floor 무효화.

## AC-077-007 (REQ-004) — NULL 서브셋 날짜 로테이션 + 시간 커버리지

- **Given** `max_stocks_to_check = 3`, `null_cap_min_slots = 1`, non-null 후보 2개(모두 fetch되도록) + NULL 후보
  4개(서로 다른 코드, 모두 near-limit-up mock), 그리고 서로 다른 스캔 날짜 D1, D2(시간 mock으로 주입)일 때
- **When** 각 날짜에 `detect_near_limit_up_carries`를 호출하면
- **Then** 각 호출은 NULL 종목을 정확히 1개 평가하되(`null_limit=3−2=1`), **D1에 평가된 NULL 종목 코드 != D2에
  평가된 NULL 종목 코드**(서브셋이 날짜에 따라 회전),
- **And** 연속 `ceil(4 / 1)` = 4개 스캔 날짜에 걸쳐 NULL 4개 **전부**가 최소 1회 평가된다(영구 굶주림 없음),
- **And** **동일 날짜** 반복 호출은 **동일** NULL 종목을 평가한다(결정적 — 같은 날 10:00/15:20 정합).

## AC-077-008 (REQ-006) — floor 설정 로딩 + clamp + yaml 비구동

- **Given** `NearLimitUpConfig`일 때
- **Then** `null_cap_min_slots` 필드가 존재하고 기본값이 `300`이다(`hasattr` + 기본값 단언),
- **And** `surge_detection.yaml`에 `null_cap_min_slots`/`near_limit_up` 키가 **존재하지 않는다**(yaml 비구동
  확인 — grep 0건 또는 로드된 config가 기본값과 동일),
- **And** `null_cap_min_slots > max_stocks_to_check`인 오설정(예: floor=10, cap=3)에서 호출 시 예외 없이 완료되고
  총 fetch <= 3을 유지하며(예약 안전 축소) 경고 로그가 남는다,
- **And** 정상 설정(floor <= cap)에서는 floor가 설정값 그대로 적용된다(AC-077-001로 확인).

## AC-077-009 (REQ-008) — 굶주림 관측성

- **Given** AC-077-001 입력일 때
- **When** `detect_near_limit_up_carries`를 호출하면
- **Then** `[near_limit_up]` 로그에 non-null 평가 수·NULL 평가 수·로테이션 offset·총 후보 수가 함께 출력된다
  (굶주림/로테이션 진행이 로그에서 관측 가능). 신규 테이블/컬럼 없음(로그 전용).

## AC-077-010 (REQ-007) — 회귀 및 품질 게이트

- **Given** 변경 적용 후
- **When** `cd backend && uv run pytest tests/test_near_limit_up_carry.py -q` 및 전체 스위트(`-n 4` 포함)를
  실행하면
- **Then** 기존 AC-001~015 / AC-072-001~005 / EC-1~5 전량 통과(특히 `min_market_cap_eok` 소형주 배제
  `test_bugfix_ai023_min_market_cap_eok_filters_small_cap_stock`, confidence 공식, `surge_basis`, `paper_executed`,
  AC-014 단일 NULL 종목 포함), 신규 characterization 통과, 신규/변경 로직 커버리지 85%+, `ruff` 무경고,
  `mypy app/` 무오류.

## AC-077-011 (Exclusions) — 무변경 보장

- **Given** 전체 변경 diff일 때
- **Then** 다음이 모두 성립: (a) 탐지 임계(15.0/29.99)·confidence(`change_rate/30*0.5`)·`surge_basis`·
  `paper_executed`·`yesterday_change_pct`·`price_at_signal`·reasoning·change_rate 소스(`_compute_t1_change_from_history`)
  diff 0; (b) `max_signals_per_day`(None)/후보 루프 diff 0; (c) `surge_detection.yaml` diff 0; (d) 신규 DB 테이블/
  컬럼/마이그레이션 0; (e) `max_stocks_to_check` 리터럴 diff 0, 후보 총 상한(.limit) 유지; (f) 다른 탐지기
  (`detect_bollinger_squeeze`/group_cascade 등) diff 0; (g) 매매·포트폴리오 로직 diff 0(AI-043 예측 기록 모드);
  (h) 과거 데이터 백필/재계산 0, market_cap 백필 0.

---

## Definition of Done

- [ ] AC-077-001 ~ AC-077-011 전부 충족.
- [ ] 재현 우선(Rule 4): 수정 전 실패 테스트(NULL 후보 도달=0 포착) 작성·확인 → 수정 후 통과.
- [ ] 후보 쿼리 분리 + NULL floor quota + 날짜 로테이션이 비굶주림·비용 상한·non-null 우선 잔여·레거시 동등성
      (floor=0)·시간 커버리지를 동시에 만족.
- [ ] `null_cap_min_slots`는 `NearLimitUpConfig` 기본값(300)으로만 추가(yaml 무변경 — dead config 방지).
- [ ] `:2701-2704` 증상-처치 주석 갱신(NULL 대표=floor quota+날짜 로테이션 SPEC-AI-077 소유, `max_stocks_to_check`
      =비용 상한 불변) + `@MX:ANCHOR/NOTE`.
- [ ] 전체 백엔드 스위트(`-n 4` 포함) 회귀 0, 커버리지 85%+, `ruff`/`mypy` 무오류.
