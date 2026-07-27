# SPEC-AI-087 인수 기준

> 각 인수 기준(AC)의 정본은 EARS 문장이다. 그 아래 "테스트 시나리오(Given/When/Then)"는 구현 검증을
> 위한 내부 교차참조이며, 정본 EARS 문장을 대체하지 않는다.

## Acceptance Criteria (EARS + 테스트 시나리오)

### AC-087-001 (REQ-001, 페이지 상한 확장)
- **EARS**: **While** 시가총액 업데이트 배치 잡이 실행되는 동안, the system **shall** 시장당 안전
  상한 60페이지(`_MARKET_CAP_UPDATE_MAX_PAGES = 60`)에 도달하거나 빈 페이지를 반환받을 때까지 순위
  페이지를 계속 조회한다.
- 테스트 시나리오(1): **Given** mock `fetch_naver_stock_list`가 11페이지 이상의 데이터를 반환하도록
  설정(기존 `range(1, 11)`이면 10페이지에서 절단될 상황), **When** `_update_market_caps()` 실행,
  **Then** 11페이지 이상의 데이터가 `cap_map`에 반영됨(기존 10페이지 상한 절단이 더 이상 발생하지
  않음이 특성화 테스트로 확인).
- 테스트 시나리오(2, 안전 상한 경계): **Given** mock `fetch_naver_stock_list`가 61페이지 이상
  무한히 비-빈 페이지를 반환하도록 설정(API 이상 동작 시뮬레이션), **When**
  `_update_market_caps()` 실행, **Then** 정확히 60페이지에서 조회가 종료됨(`_MARKET_CAP_UPDATE_MAX_PAGES`
  값의 실제 상한 경계가 고정됨을 확인).

### AC-087-002 (REQ-002, 기존 커버리지 값 불변) [HARD]
- **EARS**: **When** 페이지 상한이 확장된 상태에서 시가총액 업데이트가 실행되면, the system
  **shall NOT** 이미 상위 500위 이내로 조회되던 종목의 market_cap 값을 변경하며, 갱신 대상을
  `stocks` 테이블 밖으로 확장하지 아니한다.
- 테스트 시나리오: **Given** 상위 500위 이내 순위 종목 집합과 그 market_cap 값(확장 전 특성화
  테스트로 고정), **When** 확장된 루프로 재실행, **Then** 해당 종목들의 market_cap 값이 바이트
  동등하고, 갱신 대상 종목 집합이 여전히 `Stock.stock_code.in_(cap_map.keys())` 교집합 내에만
  존재함(추적 종목 밖 신규 삽입 없음).

### AC-087-003 (REQ-003, volume_anomaly floor-quota OFF 기본값) [HARD]
- **EARS**: **Where** `null_cap_min_slots=0`(기본값)인 경우, the system **shall** 기존
  `market_cap >= min_market_cap` 단일 조건 조회를 바이트 동등하게 유지한다.
- 테스트 시나리오: **Given** `null_cap_min_slots=0`, NULL 시총 종목 존재, **When**
  `_detect_volume_anomaly_internal` 실행, **Then** 후보 집합이 확장 전 구현과 완전히 동일(NULL
  시총 종목 미포함).

### AC-087-004 (REQ-003, volume_anomaly floor-quota ON)
- **EARS**: **Where** `null_cap_min_slots=N`(N>0)로 설정된 경우, the system **shall** NULL 시총
  종목을 최대 N개까지 날짜 로테이션 기반으로 후보풀에 추가 편입한다.
- 테스트 시나리오: **Given** `null_cap_min_slots=5`, NULL 시총 종목 10개 존재, **When** 서로 다른
  두 날짜에 각각 실행, **Then** 두 실행 모두 후보풀에 NULL 시총 종목이 최대 5개 포함되며, 두 날짜
  간 편입된 종목 집합이 로테이션 offset에 따라 달라짐(전체 NULL 풀을 순환).

### AC-087-005 (REQ-004, group_cascade NULL 편입)
- **EARS**: **Where** `cascade_include_null_market_cap=True`인 경우, the system **shall** 기존
  `max_cascade_per_flagship` 상한 내에서 NULL 시총 계열사를 non-null 종목보다 낮은 순위로 후보에
  포함시킨다.
- 테스트 시나리오: **Given** `cascade_include_null_market_cap=True`, `max_cascade_per_flagship=3`,
  동일 접두사 매칭 종목 5개(non-null 2개 + NULL 시총 3개), **When** `detect_group_cascade_signals`
  실행, **Then** 반환된 계열사 후보가 3개 이하이고, non-null 2개가 NULL 3개 중 최대 1개보다 항상
  우선 순위로 포함됨.

### AC-087-006 (REQ-005, gap_up_runners NULL 편입)
- **EARS**: **Where** `runner_include_null_market_cap=True`인 경우, the system **shall** 기존
  섹터 피어 상한(`.limit(5)`) 및 런너 선정(`[:2]`) 내에서 NULL 시총 피어를 non-null 종목보다 낮은
  순위로 후보에 포함시킨다.
- 테스트 시나리오: **Given** `runner_include_null_market_cap=True`, 동일 섹터 피어 5개(non-null
  1개 + NULL 시총 4개), **When** `detect_gap_up_runners` 실행, **Then** 선정된 런너 2개 중 non-null
  피어가 항상 포함되고, 남은 1자리에 NULL 시총 피어가 편입될 수 있음.

### AC-087-007 (REQ-006, 편입 경계 회귀) [HARD]
- **EARS**: **When** REQ-003~005의 NULL 시총 편입 옵션이 전부 활성화되어도, the system **shall NOT**
  flagship NULL 시총 제외 로직 및 bollinger_squeeze 상위 N 쿼리를 변경한다.
- 테스트 시나리오: **Given** `null_cap_min_slots>0`, `cascade_include_null_market_cap=True`,
  `runner_include_null_market_cap=True` 전부 활성화, **When** flagship 판정(`detect_group_cascade_signals`
  내부) 및 `detect_bollinger_squeeze` 각각 실행, **Then** flagship 판정은 여전히 NULL 시총 종목을
  무조건 배제하고, bollinger_squeeze 상위 N 쿼리는 여전히 `market_cap.isnot(None)` 필터를 적용함
  (두 경로 모두 M1 특성화 테스트 스냅샷과 바이트 동등).

### AC-087-008 (REQ-007, 키워드 백필 스케줄 등록)
- **EARS**: The system **shall** `backfill_stock_keywords()`를 정기 잡으로 등록하며, `keywords`가
  NULL/공백인 종목만 갱신하고 기존 값이 있는 종목은 변경하지 아니한다.
- 테스트 시나리오: **Given** 스케줄러 초기화, **When** `register_jobs()` 실행, **Then** 잡 목록에
  `backfill_stock_keywords`(또는 이를 래핑한 함수)가 등록된 ID로 존재함. **Given** `keywords=NULL`
  종목 A와 `keywords="기존값"` 종목 B, **When** `backfill_stock_keywords()` 직접 실행, **Then**
  A는 갱신 시도되고 B의 `keywords`는 불변.

### AC-087-009 (REQ-008, 전체 백워드 호환) [HARD]
- **EARS**: **While** REQ-003~005의 신규 설정 필드가 모두 기본값일 때, the system **shall** 본
  SPEC 적용 이전과 바이트 동등한 탐지 후보 집합 및 시그널 생성 결과를 낸다.
- 테스트 시나리오: **Given** 모든 신규 필드 기본값(`null_cap_min_slots=0`,
  `cascade_include_null_market_cap=False`, `runner_include_null_market_cap=False`), **When**
  전체 백엔드 테스트 스위트 실행(`uv run pytest tests/ --tb=short -q -m "not slow"`), **Then**
  무회귀(기존 통과 테스트 전부 유지) + `ruff check .` / `mypy app/` 통과.

## REQ ↔ AC 추적성 매트릭스

| REQ | 대응 AC |
|-----|---------|
| REQ-AI087-001 | AC-087-001 |
| REQ-AI087-002 | AC-087-002 |
| REQ-AI087-003 | AC-087-003, AC-087-004 |
| REQ-AI087-004 | AC-087-005 |
| REQ-AI087-005 | AC-087-006 |
| REQ-AI087-006 | AC-087-007 |
| REQ-AI087-007 | AC-087-008 |
| REQ-AI087-008 | AC-087-009 |

REQ-001~008 전량이 최소 1개 AC로 커버됨(8/8, 미커버 REQ 0건).

## 엣지 케이스

- 시총 업데이트 시 Naver API가 특정 페이지에서 예외를 던짐 → `retry_with_backoff(max_attempts=3)`
  기존 데코레이터가 함수 전체를 재시도(기존 동작 유지, 페이지 단위 재시도는 아님).
- `null_cap_min_slots`가 NULL 시총 종목 총수보다 큼 → 가용한 만큼만 반환(SPEC-AI-077의
  `reserved_null = min(null_count, null_cap_min_slots)` 패턴 재사용).
- group_cascade/gap_up_runners에서 NULL 시총 편입 활성화 상태로 동일 접두사/섹터에 non-null 종목이
  전혀 없음 → 전량 NULL 시총 후보로 채워짐(상한 내에서 정상 동작, 특별 처리 불필요).
- 키워드 백필 잡 실행 중 `NewsArticle`/`Disclosure` 레코드가 전혀 없는 신규 상장 종목 → 빈 텍스트
  리스트로 스킵(기존 `_gather_stock_theme_texts` 계약, 변경 없음).

## Definition of Done

- [ ] REQ-001~008 전량이 대응 AC(AC-087-001~009)로 커버됨 — 추적성 매트릭스 기준 미커버 REQ 0건
- [ ] AC-087-001~009 전부 특성화 테스트 통과 (RED→GREEN)
- [ ] AC-087-002/003/007/009 백워드 호환(바이트 동등) 통과 [HARD]
- [ ] AC-087-007 flagship + bollinger_squeeze 회귀 assert 통과 [HARD]
- [ ] 전체 스위트 무회귀 (`uv run pytest tests/ --tb=short -q -m "not slow"`, backend/에서 실행)
- [ ] `uv run ruff check .` + `uv run mypy app/` 통과
- [ ] 신규 DB 마이그레이션 0건
- [ ] 신규 설정 필드 3개(`null_cap_min_slots`, `cascade_include_null_market_cap`,
      `runner_include_null_market_cap`) 기본값이 전부 backward-compat(OFF)임을 확인
