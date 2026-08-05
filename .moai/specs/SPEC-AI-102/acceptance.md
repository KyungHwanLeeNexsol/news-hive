# SPEC-AI-102 Acceptance Criteria

> GEARS 정규 문장 형식. 각 AC는 **볼드 WHEN/WHILE/WHERE 트리거 + 볼드 shall/shall not 절**로
> 구성한다.

## §A. AC 매트릭스 (REQ ↔ AC 매핑)

| AC ID | 대응 REQ | 심각도 |
|-------|----------|--------|
| AC-102-001 | REQ-AI102-003 | Must-Pass |
| AC-102-002 | REQ-AI102-001 | Must-Pass |
| AC-102-003 | REQ-AI102-001 | Must-Pass |
| AC-102-004 | REQ-AI102-002 | Must-Pass |
| AC-102-005 | REQ-AI102-002 | Must-Pass |
| AC-102-006 | REQ-AI102-002 (상한 준수) | Must-Pass |
| AC-102-007 | REQ-AI102-004 | Must-Pass |
| AC-102-008 | REQ-AI102-004 | Must-Pass |
| AC-102-009 | REQ-AI102-004 (판단 근거 기록) | Should-Pass |
| AC-102-010 | REQ-AI102-005 | Must-Pass |

## §B. 인수 기준 (정규 문장)

### AC-102-001 — `_MAX_PRICE_FETCH_CANDIDATES` 재평가 결과가 근거와 함께 기록된다

**When** TASK-001 사전조사가 완료되면, the system(의 plan.md 또는 구현 커밋 메시지)은
`_MAX_PRICE_FETCH_CANDIDATES`를 유지하거나 상향하는 결정과 그 실측 근거(N=80/100/150 각각의
소요시간 측정치)를 문서에 **남겨야 한다**.

- 검증 방법: 코드 리뷰 — plan.md 또는 M4 커밋 메시지에 실측 결과 단락이 존재하는지 확인.

### AC-102-002 — Pool 소싱 함수를 `existing_codes` 없이 단독 호출해도 동일한 Pool A/B/C/D가 산출된다

**When** 신규 분리된 Pool 소싱 함수를 `existing_codes=set()`으로 단독 호출하면, the system
**shall** `build_scan_universe()` 전체 호출 시와 동일한 Pool A/B/C/D 코드 리스트 및
existing 태깅을 제외한 `entry_pool_map`을 산출해야 한다.

- 검증 방법: pytest — 동일 fixture(DB 상태 고정)로 Pool 소싱 함수 단독 호출 결과와
  `build_scan_universe(existing_codes=set())` 전체 호출 결과를 비교, Pool A/B/C/D 4개
  리스트가 완전히 동일함을 확인.

### AC-102-003 — `build_scan_universe()` 공개 시그니처·반환값이 분리 이전과 완전히 동일하다

**While** TASK-002 함수 분리가 적용된 상태에서, the system **shall not**
`build_scan_universe(db, config, existing_codes, now)`의 시그니처, 반환 타입
(`tuple[list[str], dict[str, str], dict[str, int]]`), 또는 기존 호출부 대비 산출값을
변경한다.

- 검증 방법: pytest — 기존 `test_spec_ai_094.py`/`test_spec_ai_096.py`의
  `build_scan_universe` 관련 테스트가 무수정으로 통과(diff 0).

### AC-102-004 — pool_b bridge 하위 플래그가 OFF(기본)이면 완전 무회귀다

**While** `scan_universe_bridge_pool_b_enabled`가 False(기본값)이면, the system **shall not**
`generate_scan_universe_bridge_candidates()`의 산출 결과(pool_a/pool_c bridge 후보 집합)를
TASK-003 적용 이전과 다르게 만든다 — `scan_universe_bridge_candidates_enabled`(마스터
스위치) 값과 무관하게 이 무회귀는 유지되어야 한다.

- 검증 방법: pytest — 마스터 스위치 True/False × pool_b 하위 플래그 False 조합 2가지 모두에서
  기존 SPEC-AI-092 characterization 테스트가 diff 0으로 통과.

### AC-102-005 — pool_b bridge가 ON이면 pool_b 소속 미탐지 종목이 배치 조회로 점수화된다

**When** `scan_universe_bridge_candidates_enabled`와 `scan_universe_bridge_pool_b_enabled`가
모두 True이고 pool_b 소속이면서 `merged`에 없는 종목이 존재하면, the system **shall**
`fetch_stock_price_history_batch_sync()`로 해당 종목들의 가격이력을 배치 조회해 거래량 비율로
점수화하고, 결과를 bridge 후보 목록에 포함해야 한다.

- 검증 방법: pytest — mock으로 pool_b 소속 미탐지 종목 3개를 주입, 배치 함수가 호출되고
  반환된 bridge 후보 목록에 3개 종목이 포함됨을 확인.

### AC-102-006 — pool_b bridge 후보 수가 상한을 초과하지 않는다

**When** pool_b bridge 후보화가 실행되면, the system **shall**
`scan_universe_bridge_pool_limits["pool_b"]` 및 `scan_universe_bridge_max_candidates`
전체 상한을 모두 준수해야 하며, 상한을 초과하는 신규 HTTP 호출을 발생시켜서는 **shall not**
한다.

- 검증 방법: pytest — pool_b 소속 미탐지 종목을 상한보다 많이(예: limit=5인데 후보 10개)
  주입, 실제 배치 조회된 종목 수가 상한을 넘지 않음을 확인.

### AC-102-007 — Pool B 루프 배치 전환 결과가 순차 방식과 동일하다

**While** TASK-005에서 전환한 `build_scan_universe()` Pool B 루프가 배치 함수를 사용하는
상태에서, the system **shall** 동일 입력 fixture(`volume_leader_codes` 목록 고정)에 대해
전환 이전(순차 호출) 방식과 완전히 동일한 `pool_b_codes` 산출 결과를 내야 한다.

- 검증 방법: pytest — 전환 전/후 동일 fixture로 `pool_b_codes` 리스트를 비교, diff 0.

### AC-102-008 — Pool B 배치 조회 중 일부 종목 실패가 전체를 막지 않는다

**When** Pool B 루프의 배치 조회 중 일부 종목의 가격이력 조회가 실패하면(mock 예외 주입),
the system **shall** 나머지 종목은 정상적으로 baseline 대비 비율 판정을 수행해야 하고,
`build_scan_universe()` 전체가 예외를 전파해서는 **shall not** 한다.

- 검증 방법: pytest — `volume_leader_codes` 20개 중 2개를 mock으로 실패시키고, 나머지 18개는
  정상 판정되며 함수가 예외 없이 완료됨을 확인.

### AC-102-009 — 미전환 순차 호출 지점의 판단 근거가 기록된다

**When** TASK-006이 완료되면, the system(의 plan.md)은 배치 전환하지 않기로 결정한 순차
호출 지점 각각에 대해 그 판단 근거(단발 조회 규모, 배치 이득 없음 등)를 **기록해야 한다**.

- 검증 방법: 코드 리뷰 — plan.md TASK-006 섹션에 `_get_volume_history`,
  `_get_peer_price_5d_trend`를 포함해 최소 검토 대상 5곳 각각의 판단(전환/미전환+근거)이
  기재되어 있는지 확인.

### AC-102-010 — 매수 주문 실행 경로 및 탐지 스코어링 diff 0

**While** 본 SPEC이 적용된 상태에서, the system **shall not** `fetch_current_prices_batch()`,
`surge_trading_service.py`, 8개 탐지기 스코어링 알고리즘, `compute_ensemble_score()`의
동작을 변경한다.

- 검증 방법: pytest — 기존 SPEC-AI-016 관련 테스트 및 8개 탐지기 개별 테스트 전체 무수정
  통과 + 다음 grep이 0 매치:

```bash
git diff --name-only | grep -E 'surge_trading_service\.py'
```

## §C. Given-When-Then 시나리오 (AC 보강용, AC 정의 아님)

### 시나리오 1 — pool_b bridge OFF 상태에서 마스터 스위치만 켜도 pool_b는 여전히 제외된다

- **Given** `scan_universe_bridge_candidates_enabled=True`, `scan_universe_bridge_pool_b_enabled=False`(기본값)이고, pool_b 소속이면서 `merged`에 없는 종목 A가 존재한다.
- **When** `generate_scan_universe_bridge_candidates()`가 실행된다.
- **Then** 종목 A는 bridge 후보 목록에 포함되지 않아야 한다 — pool_a/c만 대상인 기존 SPEC-AI-092
  동작과 동일해야 한다. (AC-102-004)

### 시나리오 2 — Pool B 루프 배치 조회 중 일부 종목 실패가 나머지 판정을 막지 않는다

- **Given** `build_scan_universe()`의 Pool B 후보 유니버스에 20개 종목이 있고, 그중 2개
  종목 코드가 Naver 서버에서 404를 반환한다.
- **When** 신규 배치 함수로 20개 종목을 동시 조회한다.
- **Then** 나머지 18개 종목은 정상적으로 baseline 대비 비율 판정을 받고, 실패한 2개는
  빈 리스트로 처리되어 `build_scan_universe()`의 스캔 유니버스 생성이 예외 없이 완료되어야
  한다. (AC-102-008)

## §D. Edge Cases

- **Pool B 소속 종목이 0개인 상태에서 pool_b bridge가 ON인 경우**: `generate_scan_universe_bridge_candidates()`는
  pool_b bridge 후보 0개를 반환해야 하며(빈 리스트), 배치 함수를 0개 종목으로 호출하려는
  시도(빈 리스트 요청)가 예외를 유발해서는 안 된다.
- **`existing_codes`가 빈 집합인 상태에서 Pool 소싱 함수를 단독 호출**: Pool A/B/C/D 소싱은
  정상 산출되어야 하고(검증된 사실 1), existing 태깅만 빈 상태(`entry_pool_map`에 "existing"
  값이 하나도 없음)로 남아야 한다.
- **`scan_universe_bridge_pool_limits`에 `"pool_b"` 키가 없는 레거시 config 상태(배포 직후,
  구성 파일 미갱신)**: 존재하지 않는 키는 "무제한"이 아니라 안전한 기본값(0 또는 신규
  기본 상수)으로 취급해 pool_b bridge가 암묵적으로 비활성 상태를 유지해야 한다 — 명시적
  플래그 없이 새 HTTP 호출 경로가 열려서는 안 된다.
- **TASK-004(`_MAX_PRICE_FETCH_CANDIDATES` 상향)가 "변경 없음"으로 결론난 경우**: AC-102-001의
  "근거 기록" 요건은 여전히 충족되어야 하며, 이 경우 §Definition of Done의 해당 항목은
  "변경 없음, 근거: <M1 실측 요약>" 형태로 체크된다.

## §E. Definition of Done

- [ ] AC-102-001 통과 — `_MAX_PRICE_FETCH_CANDIDATES` 재평가 결과 문서화.
- [ ] AC-102-002 통과 — Pool 소싱 함수 단독 호출 동등성.
- [ ] AC-102-003 통과 — `build_scan_universe()` 공개 인터페이스 무회귀.
- [ ] AC-102-004 통과 — pool_b bridge 하위 플래그 OFF 시 완전 무회귀.
- [ ] AC-102-005 통과 — pool_b bridge ON 시 배치 조회+점수화.
- [ ] AC-102-006 통과 — pool_b bridge 상한 준수.
- [ ] AC-102-007 통과 — Pool B 루프 배치 전환 무회귀.
- [ ] AC-102-008 통과 — Pool B 배치 조회 개별 실패 격리.
- [ ] AC-102-009 통과 — 미전환 지점 판단 근거 기록.
- [ ] AC-102-010 통과 — 매수 주문 실행 경로·탐지 스코어링 diff 0.
- [ ] `ruff check` / `mypy` 통과.
- [ ] `uv run python -c "from app.main import app; print('OK')"` 통과.
- [ ] `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"` 전체 회귀 통과.
- [ ] spec.md §Open Questions(1: 상향 폭, 2: pool_b 상한 기본값)이 Implementation Kickoff
      Approval 이전에 사용자와 확정됨 — 확정 없이는 run-phase 진입을 보류한다.
