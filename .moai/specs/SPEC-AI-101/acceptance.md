# SPEC-AI-101 Acceptance Criteria

> GEARS 정규 문장 형식. 각 AC는 **볼드 WHEN/WHILE/WHERE 트리거 + 볼드 shall/shall not 절**로
> 구성한다.

## §A. AC 매트릭스 (REQ ↔ AC 매핑)

| AC ID | 대응 REQ | 심각도 |
|-------|----------|--------|
| AC-101-001 | REQ-AI101-001 | Must-Pass |
| AC-101-002 | REQ-AI101-001 | Must-Pass |
| AC-101-003 | REQ-AI101-001 | Must-Pass |
| AC-101-004 | REQ-AI101-002 | Must-Pass |
| AC-101-005 | REQ-AI101-002 | Must-Pass |
| AC-101-006 | REQ-AI101-004 | Must-Pass |
| AC-101-007 | REQ-AI101-004 | Must-Pass |
| AC-101-008 | REQ-AI101-004 | Must-Pass |
| AC-101-009 | REQ-AI101-003 | Must-Pass |
| AC-101-010 | REQ-AI101-005 | Must-Pass |
| AC-101-011 | REQ-AI101-005 | Must-Pass |
| AC-101-012 | REQ-AI101-006 | Must-Pass |

## §B. 인수 기준 (정규 문장)

### AC-101-001 — 신호가 기준 EOD 최대수익률이 정확히 계산된다

**When** `price_at_signal`, `high_change_rate`, T-1 종가 조회가 모두 성공하면, the system
**shall** `day_high_price = prev_close_price × (1 + high_change_rate/100)`과
`forward_max_return_pct = (day_high_price − price_at_signal) / price_at_signal × 100`을
설계 수식(design.md §B.1)과 정확히 일치하게 계산해야 한다.

- 검증 방법: pytest — 알려진 `price_at_signal`/`high_change_rate`/T-1 종가 fixture로
  `forward_max_return_pct` 기댓값과 계산값을 부동소수점 허용오차 이내로 비교

### AC-101-002 — 동일 신호에 대한 평가 잡 재실행이 멱등적으로 upsert된다

**When** 동일 `(trading_date, fund_signal_id)`에 대해 평가 잡이 두 번 실행되면, the
system **shall** 두 번째 실행이 신규 행을 추가하지 않고 기존 행을 갱신(upsert)해야 한다.

- 검증 방법: pytest — 동일 fixture로 평가 함수를 2회 호출 후 `SurgeSignalForwardOutcome`
  행 수가 1건임을 확인

### AC-101-003 — `price_at_signal` NULL 또는 T-1 종가 조회 실패 시 안전하게 NULL 처리된다

**When** `price_at_signal`이 NULL이거나 T-1 종가 조회가 실패하면, the system **shall**
`day_high_price`/`forward_max_return_pct`를 NULL로 저장해야 하며 평가 잡 전체를
**shall not** 실패시켜서는 안 된다.

- 검증 방법: pytest — `price_at_signal=None` fixture 및 T-1 종가 조회 예외 주입 fixture
  각각으로 평가 잡이 정상 완료되고 해당 필드가 NULL임을 확인

### AC-101-004 — 신호가 기준 병렬 recall/precision이 표준 지표와 별도로 산출된다

**When** REQ-AI101-001의 신규 테이블에 `forward_max_return_pct >= 10.0`인 신호가
존재하면, the system **shall** 이 집합을 `predicted_set`과 비교해 병렬
recall/precision을 산출해야 하며, 이 값은 `legacy_recall`/`scannable_recall`과 다를 수
있어야 한다(서로 다른 라벨 기준이므로).

- 검증 방법: pytest — 종가 기준으로는 `was_surge=False`이나 `forward_max_return_pct>=10`인
  fixture로, 표준 recall은 해당 신호를 FN으로, 신규 병렬 recall은 TP로 계산함을 확인

### AC-101-005 — 표준 T-1→T recall/precision/coverage 산출 로직이 완전히 무변경이다

**While** 본 SPEC이 적용된 상태에서, the system **shall not**
`predicted_set`/`actual_set` 확정 로직이나 `legacy_recall`/`scannable_recall`/`coverage`
산출 로직을 변경해서는 안 된다. 이 상태에서 산출되는 표준 지표 값은 본 SPEC 적용 이전과
**100% 동일**해야 한다.

- 검증 방법: pytest — 본 SPEC 적용 전/후 동일 fixture 입력에 대해
  `evaluate_surge_predictions()`의 표준 지표 반환값을 비교해 완전히 일치함을 확인
  (characterization test) + `git diff`로 해당 로직 라인 무변경 확인

### AC-101-006 — 섀도우 비교 결과가 변화 없는 사이클에도 반드시 1행 적재된다

**When** `run_horizon_shadow_comparison()`이 실행되고 `shadow_mode_enabled=true`이면,
the system **shall** `added`와 `removed`가 모두 빈 경우(qualified 집합 변화 없음)에도
`SurgeHorizonShadowObservation`에 1행을 적재해야 한다.

- 검증 방법: pytest — 기존 경로와 신규 경로의 qualified 집합이 동일한 fixture로 실행 후,
  신규 테이블에 정확히 1행이 적재되고 added/removed가 빈 리스트로 기록됨을 확인

### AC-101-007 — 섀도우 영속화 실패가 기존 시그널 생성 흐름을 막지 않는다

**When** `SurgeHorizonShadowObservation` 적재가 예외를 발생시키면, the system **shall**
그 예외를 포착해 로그로 남기고 기존 임계값 경로의 qualified 집합 산출 및 `FundSignal`
생성 결과를 **shall not** 되돌리거나 스캔 사이클 전체를 실패시켜서는 안 된다
(REQ-AI100-007 예외 격리 원칙 재사용).

- 검증 방법: pytest — DB 적재 호출부에 예외를 주입한 fixture로 실행 후, 기존 경로의
  qualified 집합과 `FundSignal` 생성이 정상적으로 완료되었음을 확인

### AC-101-008 — 지평 인식 판정 로직 본체가 완전히 무변경이다

**While** 본 SPEC이 적용된 상태에서, the system **shall not**
`compute_ensemble_score()`, `compute_horizon_signature()`, `select_effective_threshold()`의
판정 로직 본체를 변경해서는 안 된다. `run_horizon_shadow_comparison()`의 변경은 신규 `db`
인자 추가와 무조건 영속화 코드 추가로 한정되어야 한다.

- 검증 방법: `git diff`로 세 함수의 판정 로직 라인에 변경이 없음을 확인 + 기존
  `test_spec_ai_100.py` characterization 테스트 무수정 통과

```bash
git diff backend/app/services/surge_detector.py -- :^backend/tests \
  | grep -E "^\+" | grep -v "def run_horizon_shadow_comparison" \
  | grep -c "compute_ensemble_score\|compute_horizon_signature\|select_effective_threshold"
# 기대: 0 (판정 함수 시그니처/본체 라인이 diff의 추가분에 나타나지 않아야 함; 코드
# 리뷰 병행 — grep만으로는 완전히 커버되지 않음)
```

### AC-101-009 — 섀도우 관측 활성화가 `enabled` 플래그를 건드리지 않는다

**When** `shadow_mode_enabled`가 `true`로 전환되면, the system **shall**
`horizon_aware_thresholds.enabled`는 `false`로 그대로 유지해야 한다.

- 검증 방법: 설정 파일 diff 확인 — `shadow_mode_enabled: false → true` 1줄만 변경,
  `enabled:` 라인은 diff에 나타나지 않음

### AC-101-010 — 전환 게이트 3요건 판정 함수가 정확히 집계한다

**When** `check_horizon_transition_readiness(db)`가 호출되면, the system **shall**
`SurgeHorizonShadowObservation`으로부터 (1) 관측된 고유 거래일 수, (2) 관측된 시장 레짐
집합, (3) 관측 기간 중 qualified 집합 최대 변화폭(%)을 정확히 집계해 반환해야 한다.

- 검증 방법: pytest — BULL 5일/SIDEWAYS 3일/BEAR 2일 관측 fixture로 함수를 호출해
  `observed_trading_days=10`, `regimes_observed={BULL,SIDEWAYS,BEAR}`,
  `max_change_pct`가 fixture 중 최댓값과 일치함을 확인

### AC-101-011 — 어떤 코드도 `enabled` 플래그를 자동으로 전환하지 않는다

**While** 본 SPEC이 적용된 상태에서, the system **shall not**
`horizon_aware_thresholds.enabled`를 프로그램적으로 `True`/`true`로 설정하는 코드를
포함해서는 안 된다(`check_horizon_transition_readiness`의 반환값을 근거로 한 자동 전환
포함).

- 검증 방법: 코드 리뷰 + grep

```bash
grep -rn "horizon_aware_thresholds.enabled\s*=\s*True\|horizon_aware_thresholds\[.enabled.\]\s*=" \
  backend/app/services/ backend/app/surge_config/
# 기대: 0 매치
```

### AC-101-012 — `enabled=true` 전환은 본 SPEC의 완료 조건이 아니다

**While** 본 SPEC의 모든 다른 AC(AC-101-001~011)가 PASS한 시점에도, the system **shall
not** `horizon_aware_thresholds.enabled=true`인 상태를 본 SPEC의 Definition of Done
조건으로 요구하지 않는다.

- 검증 방법: DoD 체크리스트(§E)에 `enabled=true` 전환 항목이 없음을 확인(문서 검토)

## §C. Given-When-Then 시나리오 (AC 보강용, AC 정의 아님)

### 시나리오 1 — 종가 기준으로는 실패, 신호가 기준으로는 적중한 경우가 병렬 지표에서
올바르게 재분류된다

- **Given** 종목 A가 신호 발행가(`price_at_signal`) 대비 장중 고점에서 +12% 상승했다가
  종가 +7%로 마감했다(`was_surge=False`, `forward_max_return_pct≈+12%`).
- **When** `evaluate_surge_predictions()`가 실행된다.
- **Then** 표준 `legacy_recall`/`scannable_recall`은 이 신호를 FN으로 계산하고(무변경,
  AC-101-005), 신규 병렬 지표는 이 신호를 TP로 계산한다(AC-101-004) — 두 지표가 서로
  다른 결과를 내는 것 자체가 이 SPEC이 해결하려는 문제의 가시화다.

### 시나리오 2 — 섀도우 관측이 변화 없는 날에도 관측 거래일로 정확히 집계된다

- **Given** `shadow_mode_enabled=true`이고, 특정 거래일의 모든 스코어링 사이클에서
  기존 경로와 신규 지평 인식 경로의 qualified 집합이 완전히 동일하다.
- **When** 그날의 스코어링이 종료된다.
- **Then** `SurgeHorizonShadowObservation`에는 여전히 그날의 사이클 수만큼 행이
  적재되어 있고(AC-101-006), `check_horizon_transition_readiness`가 그날을 관측된
  고유 거래일 수에 포함시킨다(AC-101-010) — 로그 스크래핑 방식이었다면 이날이 누락됐을
  것이다(design.md §F 기각 대안).

### 시나리오 3 — 전환 게이트 3요건이 모두 충족되어도 자동 전환은 일어나지 않는다

- **Given** `check_horizon_transition_readiness`가 3요건 모두 충족(`all_criteria_met=True`)을
  반환한다.
- **When** 다음 스코어링 사이클이 실행된다.
- **Then** `horizon_aware_thresholds.enabled`는 여전히 `false`이며(AC-101-009,
  AC-101-011), 전환 여부는 사람이 이 함수의 출력을 검토해 별도로 결정한다.

## §D. Edge Cases

- **신호가 여러 개인 종목·같은 날**(T-1 배치 + 장중 재스캔): 각 `fund_signal_id`별로
  독립적인 행이 적재되어야 하며, 어느 하나가 다른 하나를 덮어써서는 안 된다(D1, design.md
  §B.2).
- **T-1이 공휴일 경계 또는 신규 상장 직후**: `fetch_stock_price_history_sync`가 유효한
  T-1 종가를 찾지 못하면 AC-101-003에 따라 NULL 처리한다.
- **`shadow_mode_enabled=true`이지만 `enabled`도 실수로 `true`인 설정 오류 상태**:
  SPEC-AI-100 REQ-AI100-006이 이미 "섀도우 모드는 `enabled=false`이고 섀도우 모드가
  활성화된" 조건으로 명시했다 — `run_horizon_shadow_comparison()` 진입부의 기존
  `if config.ensemble.horizon_aware_thresholds.enabled: return` 가드(SPEC-AI-100 소유,
  무수정)가 이 경우 섀도우 계산 자체를 건너뛴다. 본 SPEC의 영속화 코드도 동일 가드
  아래에서만 실행되므로 이 설정 오류 상태에서 영속화가 이중으로 실행되지 않는다.
- **`SurgeHorizonShadowObservation` 테이블이 매우 커진 상태**: `check_horizon_transition_readiness`가
  느려질 수 있다 — 성능 저하는 관측 창(예: 최근 30일)으로 쿼리를 제한해 완화 가능하나,
  정확한 창 크기는 구현 시 결정(Open Question 3과 연계, 본 SPEC의 Must-Pass 범위 밖).

## §E. Definition of Done

- [ ] AC-101-001 통과 — 신호가 기준 EOD 최대수익률 계산 정확성.
- [ ] AC-101-002 통과 — 평가 잡 재실행 멱등성(upsert).
- [ ] AC-101-003 통과 — NULL 안전 처리.
- [ ] AC-101-004 통과 — 신호가 기준 병렬 recall/precision 산출.
- [ ] AC-101-005 통과 — 표준 T-1→T 지표 완전 무변경(characterization test).
- [ ] AC-101-006 통과 — 섀도우 비교 결과가 변화 없는 사이클에도 1행 적재.
- [ ] AC-101-007 통과 — 섀도우 영속화 실패가 기존 흐름 무영향.
- [ ] AC-101-008 통과 — 지평 인식 판정 로직 본체 완전 무변경.
- [ ] AC-101-009 통과 — 섀도우 관측 활성화가 `enabled` 플래그 무변경.
- [ ] AC-101-010 통과 — 전환 게이트 3요건 판정 함수 정확성.
- [ ] AC-101-011 통과 — 자동 전환 코드 부재(grep 0 매치).
- [ ] AC-101-012 통과 — `enabled=true` 전환이 DoD 조건이 아님(문서 검토).
- [ ] `ruff check` / `mypy` 통과.
- [ ] 기존 회귀 테스트 전체 통과: `cd backend && uv run pytest tests/ -m "not slow"`.
- [ ] spec.md §Open Questions 1(신규 테이블 정확한 PK/컬럼명)이 구현 착수 전 확정됨.
- [ ] spec.md §Open Questions 2(`price_at_signal` 실측 채움률)가 구현 착수 시 도메인
      검증으로 확인됨 — 극단적으로 낮으면(예: <10%) 오케스트레이터에게 블로커 보고.
- [ ] spec.md §Open Questions 3(섀도우 테이블 보존 정책)의 미확정 상태는 본 SPEC의
      DoD를 막지 않는다 — 관측 인프라가 정상 동작하는 상태까지가 Must-Pass 범위이며,
      장기 보존 정책 확정은 후속 작업으로 유예 가능하다.
