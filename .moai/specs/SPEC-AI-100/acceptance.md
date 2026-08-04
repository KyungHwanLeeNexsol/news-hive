# SPEC-AI-100 Acceptance Criteria

> GEARS 정규 문장 형식. 각 AC는 **볼드 WHEN/WHILE/WHERE 트리거 + 볼드 shall/shall not 절**로
> 구성한다.

## §A. AC 매트릭스 (REQ ↔ AC 매핑)

| AC ID | 대응 REQ | 심각도 |
|-------|----------|--------|
| AC-100-001 | REQ-AI100-001 | Must-Pass |
| AC-100-002 | REQ-AI100-002 | Must-Pass |
| AC-100-003 | REQ-AI100-003 | Must-Pass |
| AC-100-004 | REQ-AI100-003, REQ-AI100-005 | Must-Pass |
| AC-100-005a | REQ-AI100-004 | Must-Pass |
| AC-100-005b | REQ-AI100-004 | Must-Pass |
| AC-100-006 | REQ-AI100-006 | Must-Pass |
| AC-100-007 | REQ-AI100-006 | Must-Pass |
| AC-100-008 | REQ-AI100-007 | Must-Pass |
| AC-100-009 | REQ-AI100-008 | Must-Pass |
| AC-100-010 | REQ-AI100-003 | Must-Pass |
| AC-100-011 | REQ-AI100-009 | Must-Pass |

## §B. 인수 기준 (정규 문장)

### AC-100-001 — 지평 라벨 설정이 조회 가능하며 미설정 키는 안전 기본값으로 처리된다

**Where** `config.ensemble.horizon_aware_thresholds.enabled`가 `true`이면, the
system **shall** `config.ensemble.weights`의 각 탐지기 키에 대응하는 지평 라벨을
조회할 수 있어야 한다. **When** 특정 탐지기 키에 지평 라벨이 설정되지 않았으면,
the system **shall** `multi_day` 기본값으로 처리해야 하며 예외를 발생시켜서는
**shall not** 안 된다.

- 검증 방법: pytest — 지평 라벨 맵에서 키를 하나 누락시킨 fixture로 조회 함수
  실행, 예외 없이 `multi_day`가 반환됨을 확인

### AC-100-002 — 지평 시그니처가 실제 발화한 탐지기 그룹으로부터 올바르게 산출된다

**When** 후보의 앙상블 점수가 계산된 직후, **Where** `horizon_aware_thresholds.enabled`
가 `true`이면, the system **shall** 그 후보에 대해 0 초과 스코어를 가진 탐지기들의
지평 라벨을 조합해 지평 시그니처(`same_day_dominant`/`next_day_dominant`/
`multi_day_dominant`/`mixed`)를 산출해야 한다.

- 검증 방법: pytest — same_day 라벨 탐지기만 스코어를 가진 fixture, next_day
  라벨 탐지기만 스코어를 가진 fixture, 두 지평이 혼합된 fixture 3종으로 각각
  올바른 시그니처가 산출됨을 확인

### AC-100-003 — 플래그 활성 시 레짐 × 지평 시그니처 조합으로 임계값이 선택된다

**When** 지평 시그니처가 산출되고 `horizon_aware_thresholds.enabled`가 `true`이면,
the system **shall** 시장 레짐과 지평 시그니처의 조합으로 임계값을 조회해야
하며, 이 조회 결과가 기존 `effective_threshold`(레짐별 단일 표) 값과 다를 수
있어야 한다(동일 레짐이라도 지평 시그니처에 따라 다른 임계값을 적용할 능력이
있어야 함).

- 검증 방법: pytest — 동일 레짐(BULL)에 대해 서로 다른 지평 시그니처를 가진
  두 fixture로 임계값 조회 함수를 실행, 두 결과가 (설정에 따라) 서로 다른 값을
  반환할 수 있는 조회 경로임을 확인(초기값이 동일하게 설정되어 있어도 조회
  경로 자체가 지평 시그니처를 인자로 받는지 확인)

### AC-100-004 — 플래그 비활성 시 동작이 기존과 바이트 동일하다

**While** `horizon_aware_thresholds.enabled`가 `false`(기본값)이면, the system
**shall** 기존 `effective_threshold`(레짐별 단일 표) 조회 경로만 사용해야 하며,
지평 시그니처 계산이나 신규 임계값 조회 로직을 **shall not** 실행해서는 안
된다. 이 상태에서 산출되는 최종 qualified 후보 집합은 본 SPEC 적용 이전과
**100% 동일**해야 한다.

- 검증 방법: pytest — 본 SPEC 적용 전/후 동일 fixture 입력에 대해
  `gather_surge_candidates()`(또는 해당 메인 함수)의 qualified 집합을 비교해
  완전히 일치함을 확인(characterization test)

### AC-100-005a — `combo_chase_guard` Gate 4의 판정 로직은 무변경이다

**While** 본 SPEC이 적용된 상태에서, the system **shall not** Gate 4(combo 단독
신호 배제)의 companion-detector 판정 조건을 변경해서는 안 된다.

- 검증 방법: pytest — combo 단독 신호(companion 없음) fixture로 Gate 4가 여전히
  해당 후보를 제거함을 확인 + `git diff`로 Gate 4 판정 조건 라인 무변경 확인

### AC-100-005b — Gate 4가 지평 시그니처 계산보다 먼저 실행된다

**While** 본 SPEC이 적용된 상태에서, the system **shall** Gate 4를 지평
시그니처 계산 및 임계값 선택보다 먼저 실행해야 한다(Gate 4에 의해 `merged`에서
제거된 후보는 지평 시그니처 계산 대상에서 자연히 제외됨).

- 검증 방법: pytest — Gate 4가 제거한 후보가 지평 시그니처 계산 함수의 호출
  대상 목록에 나타나지 않음을 확인(호출 순서 검증 + 제거된 후보 코드가 산출된
  시그니처 매핑에 없음을 확인)

### AC-100-006 — 섀도우 모드가 플래그 비활성 상태에서 신규/기존 경로를 모두 계산하고
차이를 로깅한다

**Where** 섀도우 모드 관측이 활성화되어 있고 `horizon_aware_thresholds.enabled`가
`false`이면, the system **shall** 매 스코어링 사이클마다 기존 임계값 경로와 신규
지평 인식 임계값 경로의 qualified 집합을 모두 계산하고, 두 집합의 차이를 구조화
로그로 기록해야 한다.

- 검증 방법: pytest — 두 경로의 qualified 집합이 다르게 나오는 fixture로 실행 후,
  로그에 차이 종목 코드가 정확히 기록됨을 확인

### AC-100-007 — 섀도우 모드 계산 실패가 기존 시그널 생성 흐름을 막지 않는다

**When** 섀도우 모드의 신규 경로 계산이 예외를 발생시키면, the system **shall**
그 예외를 포착해 로그로 남기고 기존 임계값 경로의 qualified 집합 산출 및
`FundSignal` 생성 결과를 **shall not** 되돌리거나 스캔 사이클 전체를 실패시켜서는
안 된다.

- 검증 방법: pytest — 섀도우 계산 호출부에 예외를 주입한 fixture로 실행 후,
  기존 경로의 qualified 집합과 `FundSignal` 생성이 정상적으로 완료되었음을 확인

### AC-100-008 — 고아 탐지기가 본 SPEC 적용 전후 동일하게 배선되지 않은 상태를
유지한다

**While** 본 SPEC이 적용된 상태에서, the system **shall not**
`detect_weekend_gap_up_signals()`나 `detect_bollinger_squeeze_signals()`의 결과를
앙상블 스코어링 대상(`merged`) 또는 `FundSignal` 생성 경로에 신규로 포함시켜서는
안 된다.

- 검증 방법: 코드 리뷰 — `git diff`로 두 함수의 호출부(`fund_manager.py`,
  `scheduler.py`)에 변경이 없음을 확인

```bash
git diff --name-only | grep -E 'fund_manager\.py|scheduler\.py'
# 기대: 0 매치 — 본 SPEC은 이 두 파일을 건드리지 않는다
```

### AC-100-009 — 평가 계층과 재스캔 메커니즘이 완전히 무변경이다

**While** 본 SPEC이 적용된 상태에서, the system **shall not**
`_is_same_day_event_horizon_signal()`(평가 계층)이나
`_maybe_trigger_event_rescan()`(SPEC-AI-066 재스캔)의 판정 로직을 변경해서는
안 된다.

- 검증 방법: 코드 리뷰 — `git diff`로 두 함수 본문에 라인 변경이 없음을 확인 +
  기존 `test_spec_ai_075.py`, `test_spec_ai_080.py`, `test_spec_ai_066.py`류
  (실제 파일명은 구현 시 재확인) characterization 테스트 무수정 통과

```bash
git diff --name-only | grep -E 'surge_evaluation_service\.py|scheduler\.py' \
  | xargs -I{} git diff {} -- :^backend/tests
# 기대: 위 REQ 대상 함수 본문에 diff 없음(코드 리뷰 병행 — grep만으로는 완전히
# 커버되지 않음)
```

### AC-100-010 — `compute_ensemble_score`와 매수 실행 게이트가 완전히 무변경이다

**While** 본 SPEC이 적용된 상태에서, the system **shall not**
`compute_ensemble_score()`의 가중합·컨센서스 배율 계산 본체, 3개 bypass 루프,
`sector_contagion` 게이트, `surge_threshold_service.py`의 어떤 함수도 변경해서는
안 된다.

- 검증 방법: 코드 리뷰 + `git diff` — 대상 함수 본문 무변경 확인, 기존
  `test_spec_ai_017.py`, `test_spec_ai_030.py`, `test_spec_ai_092.py`류(실제
  파일명은 구현 시 재확인) characterization 테스트 무수정 통과

```bash
git diff --name-only | grep -E 'surge_threshold_service\.py'
# 기대: 0 매치 — 본 SPEC은 이 파일을 건드리지 않는다
```

### AC-100-011 — 섀도우→프로덕션 전환 게이트가 구조적 최소 요건 3가지를 모두
요구한다

**When** `horizon_aware_thresholds.enabled`를 `true`로 전환하는 결정이
검토되면, the system **shall** 다음 세 요건이 모두 충족되었는지 확인 절차의
일부로 요구해야 한다: (1) 섀도우 모드 관측 거래일 ≥ 10일(잠정값), (2)
BULL/SIDEWAYS/BEAR 3개 레짐 각 1회 이상 관측, (3) qualified 후보 집합 변화폭이
기존 경로 대비 ±30%(잠정값) 이내. **When** 세 요건 중 하나라도 미충족이면,
the system **shall not** 전환 절차를 완료된 것으로 표시해서는 안 된다.

- 검증 방법: 코드 리뷰 + 문서 검토 — 전환 체크리스트(plan.md §D "전환 게이트"
  또는 구현 시 작성되는 별도 런북)에 세 요건이 명시적 항목으로 존재함을 확인.
  자동화된 pytest 검증은 섀도우 로그 파서가 구현된 이후 추가 가능(본 SPEC
  범위에서는 게이트 구조의 존재 여부만 Must-Pass로 요구한다).

## §C. Given-When-Then 시나리오 (AC 보강용, AC 정의 아님)

### 시나리오 1 — 당일 지평 우세 후보가 신규 임계값으로, 다일 지평 우세 후보가 별도
임계값으로 게이팅된다

- **Given** `horizon_aware_thresholds.enabled=true`이고, 종목 A는
  `volume_breakout_score`(same_day 라벨)만 0 초과, 종목 B는
  `theme_cluster_score`(multi_day 라벨)만 0 초과인 상태로 동일 레짐(BULL)에서
  스코어링된다.
- **When** 앙상블 스코어링 사이클이 완료된다.
- **Then** 종목 A는 `same_day_dominant` 시그니처로 same_day 임계값 표를 조회하고,
  종목 B는 `multi_day_dominant` 시그니처로 기존 `regime_thresholds`에 대응하는
  값을 조회한다 — 두 조회가 서로 다른 임계값 표 경로를 사용했음을 로그로 확인할
  수 있다. (AC-100-002, AC-100-003)

### 시나리오 2 — 플래그 비활성 상태에서는 기존 배포와 완전히 동일하게 동작한다

- **Given** `horizon_aware_thresholds.enabled=false`(기본값)이고, 실제 프로덕션과
  동일한 후보 집합이 주어진다.
- **When** 앙상블 스코어링 사이클이 실행된다.
- **Then** 최종 qualified 후보 집합, `FundSignal` 생성 결과, 로그 메시지 포맷이
  본 SPEC 적용 이전과 완전히 동일하다. (AC-100-004)

### 시나리오 3 — 섀도우 모드가 프로덕션 영향 없이 두 경로를 비교 관측한다

- **Given** `horizon_aware_thresholds.enabled=false`이고 섀도우 모드 관측이
  활성화된 상태에서, 신규 경로 계산 중 일시적 오류(예: 지평 라벨 조회 실패)가
  발생한다.
- **When** 스코어링 사이클이 계속 진행된다.
- **Then** 기존 경로의 qualified 집합 산출과 `FundSignal` 생성은 정상적으로
  완료되고, 오류는 로그에만 남는다. (AC-100-006, AC-100-007)

## §D. Edge Cases

- **어떤 탐지기도 발화하지 않은 후보(모든 스코어 0)**: 지평 시그니처 계산이
  호출되지 않거나(애초에 `merged`에 포함되지 않음) `mixed`/기본값으로 안전하게
  처리되어야 하며, 예외를 발생시켜서는 안 된다.
- **모든 탐지기가 동시에 발화한 후보(지평 혼합)**: `mixed` 시그니처로 분류되며,
  이 경우 임계값 선택은 보수적으로(기존 레짐 임계값과 동일하거나 더 엄격한 값)
  처리되어야 한다 — 정확한 처리 규칙은 구현 시 Open Question 1/2와 함께 확정.
- **지평 라벨 맵과 `ensemble.weights`의 키 불일치**(설정 오류로 라벨 맵에 없는
  키가 weights에 존재): AC-100-001에 따라 `multi_day` 기본값으로 안전 처리되며
  시스템 전체가 실패해서는 안 된다.
- **섀도우 모드와 플래그가 동시에 `true`인 설정 오류 상태**: REQ-AI100-006은
  섀도우 모드를 "`enabled=false`이고 섀도우 모드가 활성화된" 조건으로 명시했다
  — 두 조건이 동시에 `true`인 설정 오류 시의 동작(섀도우 로깅을 건너뛰는지,
  아니면 계속 실행하는지)은 구현 시 명시적으로 결정하고 테스트에 포함한다.

## §E. Definition of Done

- [ ] AC-100-001 통과 — 지평 라벨 조회 + 안전 기본값 처리.
- [ ] AC-100-002 통과 — 지평 시그니처 산출 정확성.
- [ ] AC-100-003 통과 — 레짐 × 지평 시그니처 임계값 조회 경로.
- [ ] AC-100-004 통과 — 플래그 비활성 시 바이트 동일 동작(characterization test).
- [ ] AC-100-005a 통과 — `combo_chase_guard` Gate 4 판정 로직 무변경.
- [ ] AC-100-005b 통과 — Gate 4가 지평 시그니처 계산보다 먼저 실행됨.
- [ ] AC-100-006 통과 — 섀도우 모드 비교 로깅.
- [ ] AC-100-007 통과 — 섀도우 모드 계산 실패가 기존 흐름 무영향.
- [ ] AC-100-008 통과 — 고아 탐지기 비배선 상태 유지.
- [ ] AC-100-009 통과 — 평가 계층·재스캔 메커니즘 무변경.
- [ ] AC-100-010 통과 — `compute_ensemble_score`·bypass 루프·`sector_contagion`·
      `surge_threshold_service` 완전 무변경.
- [ ] AC-100-011 통과 — 섀도우→프로덕션 전환 게이트 구조적 최소 요건(관측기간·
      레짐 커버리지·후보집합 변화폭) 명문화.
- [ ] `ruff check` / `mypy` 통과.
- [ ] 기존 회귀 테스트 전체 통과: `cd backend && uv run pytest tests/ -m "not slow"`.
- [ ] spec.md §Open Questions 1(지평 라벨 정확한 값)이 구현 착수 전 확정됨(적어도
      `volume_news_combo`의 분류는 도메인 검증 후 확정).
- [ ] spec.md §Open Questions 2(임계값 수치)와 3(섀도우 모드 관측 기간)의 세부
      수치 미확정 상태는 본 SPEC의 DoD를 막지 않는다 — REQ-AI100-009(AC-100-011)가
      요구하는 전환 게이트의 구조(3요건 존재) 자체는 Must-Pass이나, 정확한 수치
      (10 거래일, ±30% 등)의 최종 튜닝은 섀도우 모드 관측 후 확정한다. 플래그가
      `false`인 상태에서의 안전한 배포·섀도우 관측 가능 상태까지가 Must-Pass
      범위이며, 플래그를 실제로 `true`로 전환하는 결정 자체는 이 SPEC의 범위가
      아니다(별도 관찰 후 판단).
