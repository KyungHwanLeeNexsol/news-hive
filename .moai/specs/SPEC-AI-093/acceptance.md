# SPEC-AI-093 Acceptance Criteria

> GEARS 정규 문장(normative sentence) 형식으로 작성한다. 각 AC는 **볼드 WHEN/WHILE/WHERE
> 트리거 + 볼드 shall/shall not 절**로 구성한다 — Given-When-Then 시나리오는 아래 별도
> 섹션에서 각 AC를 구체적 예시로 보강하는 용도로만 사용하며, AC 정의 자체는 아니다.

## §A. AC 매트릭스 (REQ ↔ AC 매핑)

| AC ID | 대응 REQ | 심각도 |
|-------|----------|--------|
| AC-093-001 | REQ-AI093-001 | Must-Pass |
| AC-093-002 | REQ-AI093-002 | Must-Pass |
| AC-093-003 | REQ-AI093-003 | Must-Pass |
| AC-093-004 | REQ-AI093-004 | Must-Pass |
| AC-093-005 | REQ-AI093-001 (change_rate 경로 불변) | Must-Pass |
| AC-093-006 | REQ-AI093-001 (불변식) | Must-Pass |
| AC-093-007 | REQ-AI093-005 | Must-Pass |
| AC-093-008 | REQ-AI093-005 (coverage guard) | Should-Pass |
| AC-093-009 | REQ-AI093-006 | Should-Pass |
| AC-093-010 | REQ-AI093-004 (기존 테스트 무회귀) | Must-Pass |

## §B. 인수 기준 (정규 문장)

### AC-093-001 — 고가 기준 등락률 실측 저장

**When** 어떤 종목의 당일 일봉이 `high` = 전일 종가 대비 +15%, `close` = 전일 종가 대비 +7%를
나타내면, the system **shall** 해당 행의 `high_change_rate`를 non-None으로 저장하고 그 값이
15.0에 근사(허용 오차 ±0.01)해야 한다.

- 검증 방법: pytest — 일봉 fixture(`PriceRecord` 리스트) 주입 후 upsert 행 검사

### AC-093-002 — T-1 종가는 date 매칭으로 특정된다

**When** 일봉 리스트에 T일 레코드보다 앞에 다른 거래일 레코드가 섞여 있거나 T-1 레코드가
리스트의 인덱스 1이 아닌 위치에 있으면, the system **shall** `PriceRecord.date` 값 매칭으로
직전 영업일 레코드를 특정해야 하며, 인덱스 위치로 T-1을 추정해서는 **shall not**.

- 검증 방법: pytest — 인덱스 1이 T-1이 아닌 순서 교란 fixture (SPEC-AI-072 회귀 방지)

### AC-093-003 — fallback 경로는 구분 가능하게 로깅된다

**When** 고가 기반 계산이 5개 사유(`no_candle_t` / `no_candle_t1` / `invalid_high` /
`invalid_prev_close` / `invariant_violation`) 중 하나로 실패하면, the system **shall**
`high_change_rate`를 NULL로 저장하고 해당 사유 코드를 식별할 수 있는 로그 이벤트를 남겨야 하며,
배치 종료 시 사유별 건수를 요약 로그 1건으로 집계해야 한다.

- 검증 방법: pytest — 사유별 fixture 5종 + `caplog` 사유 코드 문자열 검사

### AC-093-004 — `was_surge` 값 및 소비자 무회귀

**While** 본 SPEC이 적용된 상태에서, the system **shall** 동일 입력 fixture에 대해 적용 이전과
완전히 동일한 `was_surge` 값과 동일한 `change_rate` 값을 저장해야 하며, `was_surge`를 소비하는
7개 지점의 코드를 변경해서는 **shall not**.

- 검증 방법: pytest — 적용 전후 동일 fixture 값 비교 + 다음 grep이 0 매치

```bash
git diff --name-only | grep -E 'surge_evaluation_service|surge_universe_gap_service|surge_auto_improver|surge_detector|scheduler'
```

### AC-093-005 — `change_rate` 산출 경로 불변

**When** 고가 조회가 실패하거나 성공하거나에 관계없이, the system **shall** `change_rate`를
`fetch_current_price_with_change` 반환값에서만 취해야 하며, 일봉 종가로부터 재계산해서는
**shall not**.

- 검증 방법: pytest — `fetch_current_price_with_change`가 반환한 값과 일봉 종가 유도값이 서로 다른
  fixture에서 저장 값이 전자와 일치하는지 확인

### AC-093-006 — 고가-종가 불변식 위반 방어

**When** 계산된 `high_change_rate`가 같은 행의 `change_rate`보다 작으면, the system **shall**
그 값을 저장하지 않고 NULL + `invariant_violation` 사유로 처리해야 한다.

- 검증 방법: pytest — 모순 fixture (일봉 high가 종가 기준 등락률보다 낮은 비정상 데이터)

### AC-093-007 — 고가 기반 파생 지표는 병렬로 제공된다

**Where** 고가 기반 성공 판정이 필요하면, the system **shall**
`COALESCE(high_change_rate, change_rate) >= 10.0`으로 판정값을 산출하고, 이를 기존 `was_surge`
기반 지표와 **병렬로** 반환해야 하며, 기존 지표를 대체해서는 **shall not**.

- 검증 방법: pytest — `high_change_rate`가 NULL인 행과 non-NULL인 행이 섞인 fixture에서 두 지표가
  모두 반환되는지 확인

### AC-093-008 — coverage guard 부착

**When** 어떤 거래일의 `high_change_rate` 실측 커버리지가 설정 임계값 미만이면, the system
**shall** 그 거래일의 고가 기반 지표에 "부분 수집" 표시와 실제 커버리지 수치를 함께 반환해야 한다.

- 검증 방법: pytest — 커버리지 임계값 위/아래 fixture 2종

### AC-093-009 — 비용 증가 계측

**When** 수집 배치가 완료되면, the system **shall** 고가 조회 시도 수와 실제 외부 호출 수를 로그로
남겨야 한다.

- 검증 방법: pytest — `caplog`에서 계측 필드 존재 확인

### AC-093-010 — 기존 테스트 스위트 통과

**When** 전체 백엔드 테스트를 실행하면, the system **shall** 기존
`test_surge_actual_outcome_service.py`의 모든 테스트를 통과해야 한다. mock 범위 확장은 허용하되
기존 단언을 약화시켜서는 **shall not**.

- 검증 방법: `pytest backend/tests -q -m "not slow"` 전체 통과 + 기존 단언 diff 검토

## §C. Given-When-Then 시나리오 (AC 보강용, AC 정의 아님)

### 시나리오 1 — 장중 급등 후 되밀린 종목

- **Given** 종목 X의 T-1 종가가 10,000원이고, T일 일봉이 `high=11,500` / `close=10,700`이다.
- **When** `collect_daily_surge_outcomes()`를 실행한다.
- **Then** `change_rate ≈ 7.0`, `was_surge = False`(동결 유지), `high_change_rate ≈ 15.0`이
  저장되어야 한다. 고가 기반 파생 판정은 True다. (AC-093-001, AC-093-004, AC-093-007)

### 시나리오 2 — 인덱스 기반 T-1 조회 금지 (SPEC-AI-072 회귀)

- **Given** 일봉 리스트가 `[T, T-1, T-2, ...]` 순이 아니라 중간에 다른 날짜가 끼어 있어 인덱스 1이
  T-1이 아니다.
- **When** 고가 기준 등락률을 계산한다.
- **Then** `date` 매칭으로 찾은 실제 T-1 레코드의 종가가 분모로 쓰여야 한다. 인덱스 1 레코드가
  분모로 쓰이면 실패다. (AC-093-002)

### 시나리오 3 — 당일 일봉 미게시

- **Given** 16:10 KST 실행 시점에 종목 Y의 T일 일봉이 아직 게시되지 않아 일봉 리스트에 T가 없다.
- **When** 수집 배치가 실행된다.
- **Then** Y의 `high_change_rate`는 NULL이고, `no_candle_t` 사유가 로깅되며, 배치는 다른 종목
  처리를 계속해야 한다. (AC-093-003)

### 시나리오 4 — `was_surge` 값 불변

- **Given** 본 SPEC 적용 전 어떤 거래일의 `was_surge=True` 행이 N건이었다.
- **When** 동일 입력으로 본 SPEC 적용 후 재실행한다.
- **Then** `was_surge=True` 행 수는 여전히 N건이어야 한다. (AC-093-004)

### 시나리오 5 — 모순 데이터 방어

- **Given** 종목 Z의 일봉 `high`로 계산한 등락률이 8.0인데, `change_rate`는 12.0으로 서로 모순된다
  (고가가 종가보다 낮다는 불가능한 상태).
- **When** 계산을 수행한다.
- **Then** `high_change_rate`는 8.0으로 저장되지 **않고** NULL + `invariant_violation`이어야 한다.
  (AC-093-006)

### 시나리오 6 — 배포 직후 부분 커버리지

- **Given** 배포 당일 200행 중 40행만 `high_change_rate`가 채워졌다 (커버리지 20%).
- **When** 고가 기반 지표를 조회한다.
- **Then** 지표와 함께 "부분 수집" 표시와 커버리지 0.20이 반환되어야 한다. (AC-093-008)

### 시나리오 7 — 과거 행은 백필되지 않는다

- **Given** 배포 이전 거래일의 `surge_actual_outcome` 행들이 `high_change_rate=NULL`이다.
- **When** 수집 배치가 이후 거래일에 대해 실행된다.
- **Then** 과거 행은 변경되지 않아야 하며, upsert는 `trading_date` 일치 행에만 작용해야 한다.
  (D3 전진 적용 원칙)

## §D. Edge Cases

- **연휴 직후**: T-1이 3~4거래일 전인 경우 `pages` 값이 부족하면 `no_candle_t1`이 발생한다.
  `pages`를 보수적으로 잡아 완화하되, 발생 시 fallback으로 안전하게 처리되어야 한다.
- **신규 상장 종목**: T-1 일봉 자체가 존재하지 않는다 → `no_candle_t1` fallback.
- **거래정지 후 재개**: 직전 영업일에 거래가 없어 일봉이 비어 있을 수 있다 → `no_candle_t1` fallback.
- **`_price_cache` 오염**: 캐시된 일봉이 T일을 포함하지 않는 오래된 데이터일 수 있다. `date` 매칭이
  이를 자연스럽게 걸러내어 `no_candle_t`로 처리된다.
- **T-1 종가 0 또는 음수**: 파싱 이상 데이터 → `invalid_prev_close` fallback.
- **upsert 재실행(idempotency)**: 같은 날 배치를 두 번 실행하면 `high_change_rate`는 동일 값으로
  덮어써져야 하며, 두 번째 실행에서 NULL로 되돌아가서는 안 된다 (조회 실패 시에는 NULL 갱신이
  정상 — 이 동작을 명시적으로 결정하고 테스트한다).

## §E. Definition of Done

- [ ] AC-093-001 통과 — `high_change_rate` 실측 저장.
- [ ] AC-093-002 통과 — date 매칭 (SPEC-AI-072 회귀 방지).
- [ ] AC-093-003 통과 — 5개 fallback 사유 구분 로깅 + 배치 요약.
- [ ] AC-093-004 통과 — `was_surge` 및 소비자 7개 지점 무회귀.
- [ ] AC-093-005 통과 — `change_rate` 산출 경로 불변.
- [ ] AC-093-006 통과 — 불변식 위반 방어.
- [ ] AC-093-007 통과 — 고가 기반 파생 지표 병렬 제공.
- [ ] AC-093-008 통과 — coverage guard.
- [ ] AC-093-009 통과 — 비용 계측.
- [ ] AC-093-010 통과 — 기존 테스트 스위트 무회귀.
- [ ] `ruff check` / `mypy` 통과.
- [ ] spec.md §Open Questions 1~3(coverage 임계값 기본값 / 파생 지표 노출 표면 / `pages` 값)이
      구현 착수 전 해소됨.
- [ ] 배포 후 첫 거래일 fallback 비율과 배치 소요 시간을 실측 확인.
