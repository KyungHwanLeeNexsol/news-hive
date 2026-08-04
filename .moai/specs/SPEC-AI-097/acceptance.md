# SPEC-AI-097 Acceptance Criteria

> GEARS 정규 문장 형식. 각 AC는 **볼드 WHEN/WHILE 트리거 + 볼드 shall/shall not 절**로 구성한다.

## §A. AC 매트릭스 (REQ ↔ AC 매핑)

| AC ID | 대응 REQ | 심각도 |
|-------|----------|--------|
| AC-097-001 | REQ-AI097-001 | Should-Pass |
| AC-097-002 | REQ-AI097-003 | Must-Pass |
| AC-097-003 | REQ-AI097-003 | Must-Pass |
| AC-097-004 | REQ-AI097-002 | Must-Pass |
| AC-097-005 | REQ-AI097-002 | Must-Pass |
| AC-097-006 | REQ-AI097-005 | Should-Pass |
| AC-097-007 | REQ-AI097-002 (스레드 안전성) | Must-Pass |
| AC-097-008 | REQ-AI097-004 | Must-Pass |

## §B. 인수 기준 (정규 문장)

### AC-097-001 — 벌크 엔드포인트 조사 결과가 기록된다

**When** TASK-001 사전조사가 완료되면, the system(의 plan.md 또는 구현 커밋 메시지)은 "진짜
벌크 엔드포인트 존재 여부"에 대한 결론과 그 근거(실제 요청/응답 예시 또는 코드 인용)를 문서에
남겨야 하며, 그 결론이 `fetch_current_prices_batch()`(동시성-배치)와 명확히 구분되어 있어야
한다.

- 검증 방법: 코드 리뷰 — plan.md 또는 M1 커밋 메시지에 조사 결과 단락이 존재하는지 확인.

### AC-097-002 — pages 부족 시 캐시 미스로 재조회한다

**When** 종목 X가 이미 `pages=1`로 캐시되어 있고 이후 같은 사이클에서 `pages=3`이 요청되면,
the system **shall** 캐시를 히트로 처리하지 않고 실제 HTTP 재조회를 수행해야 하며, 재조회 후
캐시의 `pages_fetched[X]`가 3 이상으로 갱신되어야 한다.

- 검증 방법: pytest — `_price_cache`를 pages=1 데이터로 사전 채운 뒤 pages=3 요청, mock으로
  HTTP 재호출 발생 여부와 갱신된 `pages_fetched` 값을 검사.

### AC-097-003 — pages 충분 시 캐시 히트로 재조회하지 않는다

**While** 종목 Y가 이미 `pages=3`으로 캐시되어 있고 TTL이 만료되지 않았으면, the system
**shall not** `pages=1` 또는 `pages=3` 요청에 대해 추가 HTTP 호출을 수행한다 — 캐시된 결과의
선행 부분집합으로 응답해야 한다.

- 검증 방법: pytest — mock HTTP 클라이언트 호출 횟수가 0임을 검사(pages=1, pages=3 두 요청
  모두).

### AC-097-004 — 배치 함수가 N개 종목을 동시조회하고 개별 실패를 격리한다

**When** 신규 배치 함수가 서로 다른 종목 코드 N개(N≥2)를 요청받으면, the system **shall** 배치
단위로 동시 HTTP 조회를 수행해야 하며, 그중 일부 종목의 조회가 실패해도(mock 예외 주입) 나머지
종목의 결과는 정상 반환되어야 하고 함수 전체가 예외를 전파해서는 **shall not** 한다.

- 검증 방법: pytest — N=5 요청 중 2개를 mock으로 실패시키고, 반환 dict에 5개 키가 모두 존재하며
  실패한 2개는 빈 리스트, 나머지 3개는 정상 `PriceRecord` 리스트임을 검사.

### AC-097-005 — 전환된 탐지기 호출부의 결과가 순차 방식과 동일하다

**While** TASK-004에서 전환한 탐지기(예: `detect_volume_breakout`)가 신규 배치 함수를
사용하는 상태에서, the system **shall** 동일 입력 fixture에 대해 전환 이전(순차 호출) 방식과
완전히 동일한 신호 집합(`SurgeCandidate` 목록의 종목 코드·점수)을 산출해야 한다.

- 검증 방법: pytest — 기존 `detect_volume_breakout` characterization 테스트가 무수정으로
  통과(diff 0).

### AC-097-006 — 성능 측정 로그가 존재한다

**When** 신규 배치 조회 경로가 실행되면, the system **shall** 로그에 해당 사이클의 가격이력
HTTP 호출 수(캐시 히트 제외)와 소요 시간(초)을 남겨야 한다.

- 검증 방법: pytest — `caplog`로 로그 라인에 호출 수·소요 시간 필드가 포함됨을 확인.

### AC-097-007 — 캐시 동시쓰기 경합이 발생하지 않는다

**When** 신규 배치 함수가 `ThreadPoolExecutor`로 여러 스레드에서 동시에 `_price_cache`에
쓰기·축출(`evict_expired`)을 수행하면, the system **shall not** 예외(예:
`RuntimeError: dictionary changed size during iteration`)를 발생시키거나 캐시 데이터를
손상시킨다 — 모든 스레드 완료 후 캐시에 저장된 각 종목의 레코드 수는 해당 종목의 마지막 성공
조회 결과와 일치해야 한다.

- 검증 방법: pytest — 10개 이상 종목을 동시 요청하는 스트레스 테스트를 반복 실행(예: 20회
  반복)하여 예외 미발생 및 캐시 데이터 무결성을 검사.

### AC-097-008 — 매수 주문 실행 경로 diff 0

**While** 본 SPEC이 적용된 상태에서, the system **shall not** `fetch_current_prices_batch()`,
`fetch_current_price_with_change()`, `surge_trading_service.py`의 동작을 변경한다.

- 검증 방법: pytest — 기존 SPEC-AI-016 관련 테스트 전체 무수정 통과 + 다음 grep이 0 매치:

```bash
git diff --name-only | grep -E 'surge_trading_service\.py'
```

## §C. Given-When-Then 시나리오 (AC 보강용, AC 정의 아님)

### 시나리오 1 — 동일 사이클 내 서로 다른 pages 요청 순서로 인한 과소 이력 재사용 방지

- **Given** `detect_volume_breakout`가 종목 A를 `pages=3`으로 먼저 조회해 캐시를 채운다.
- **When** 같은 스캔 사이클에서 `detect_volume_anomaly_dormant_stocks`가 같은 종목 A를
  `config.history_pages`(예: 6)로 요청한다.
- **Then** 캐시는 `cached_pages(3) < requested_pages(6)`이므로 미스로 처리하고 재조회해야
  한다 — 3페이지 분량의 과소 이력이 6페이지가 필요한 호출에 반환되어서는 안 된다. (AC-097-002)

### 시나리오 2 — 배치 조회 중 일부 종목 실패가 전체를 막지 않는다

- **Given** `detect_volume_breakout`의 유니버스에 20개 종목이 있고, 그중 2개 종목 코드가 Naver
  서버에서 404를 반환한다.
- **When** 신규 배치 함수로 20개 종목을 동시 조회한다.
- **Then** 나머지 18개 종목은 정상적으로 이력을 반환받고, 실패한 2개는 빈 리스트로 처리되어
  `detect_volume_breakout`의 신호 생성이 예외 없이 완료되어야 한다. (AC-097-004)

## §D. Edge Cases

- **`pages_fetched` 필드가 없는 레거시 캐시 상태(코드 배포 직후, 재시작 전 인메모리 캐시)**:
  존재하지 않는 필드는 0(또는 미기록)으로 취급해 항상 캐시 미스로 처리한다 — 안전한 방향
  (과소 이력 재사용보다 재조회 1회 추가가 낫다).
- **N=1(단일 종목) 배치 요청**: 배치 함수가 오버헤드 없이 단일 요청과 동등하게 동작해야 한다
  (스레드풀 생성 비용이 유의미하면 N=1 시 배치 경로를 우회하는 최적화는 구현 시 선택 가능,
  AC로 강제하지 않음).
- **전체 배치가 전부 실패(네트워크 완전 단절)**: 신규 함수는 예외를 전파하지 않고 모든 종목에
  대해 빈 리스트를 반환해야 한다 — 기존 `fetch_stock_price_history_sync`의 개별 실패 시
  `_price_cache.data.get(stock_code, [])` 폴백 관례와 동일한 방향.
- **`_price_cache` 축출(`evict_expired`)이 배치 실행 도중 트리거되는 경우**: TASK-003의
  락/일괄갱신 설계가 이 경우도 커버해야 한다(AC-097-007의 스트레스 테스트가 간접 검증).

## §E. Definition of Done

- [ ] AC-097-001 통과 — 벌크 엔드포인트 조사 결과 문서화.
- [ ] AC-097-002 통과 — pages 부족 시 캐시 미스.
- [ ] AC-097-003 통과 — pages 충분 시 캐시 히트(재조회 없음).
- [ ] AC-097-004 통과 — 배치 함수 동시조회 + 개별 실패 격리.
- [ ] AC-097-005 통과 — 전환된 탐지기 무회귀.
- [ ] AC-097-006 통과 — 성능 측정 로그 존재.
- [ ] AC-097-007 통과 — 캐시 동시쓰기 경합 없음.
- [ ] AC-097-008 통과 — 매수 주문 실행 경로 diff 0.
- [ ] `ruff check` / `mypy` 통과.
- [ ] `uv run python -c "from app.main import app; print('OK')"` 통과.
- [ ] spec.md §Open Questions(로컬 영속 OHLCV 테이블 신설 여부, D3)이 Implementation Kickoff
      Approval 이전에 사용자와 확정됨 — 확정 없이는 run-phase 진입을 보류한다.
