# SPEC-AI-100 Plan

## A. 구현 전략

Tier L, cycle_type: ddd(ANALYZE-PRESERVE-IMPROVE — `quality.yaml`
`constitution.development_mode: ddd`). 이 Epic에서 가장 아키텍처적으로 근본적이고
blast radius가 큰 SPEC이므로, 되돌리기 어려운 결정(설정 스키마 형태, 지평 시그니처
계산 방식, 임계값 선택 분기 지점)을 먼저 확정하고, 기계적 배선(로깅 포맷, 플래그
기본값 배선)은 뒤로 미룬다.

핵심 판단:

- 이 SPEC의 위험은 `compute_ensemble_score`의 가중합·컨센서스 배율·3개 bypass
  루프·`sector_contagion` 게이트를 **어느 것도 건드리지 않는 것**으로 완화된다
  (design.md §E 결정 — 옵션 (b)). 유일한 진짜 위험은 (1) 지평 시그니처 계산이
  기존 `detector_groups` 로직을 잘못 재사용해 회귀를 유발하는 것, (2) feature
  flag 기본값이 실수로 `true`가 되어 검증 없이 프로덕션에 영향을 주는 것이다.
- `combo_chase_guard`, `surge_threshold_service`, 평가 계층
  (`_is_same_day_event_horizon_signal`), 재스캔 메커니즘(`_maybe_trigger_event_rescan`)은
  spec.md §Out of Scope / §Decisions에 따라 완전히 무수정이다.

### A.1 신규 설정 스키마 — 지평 라벨 맵 (가장 되돌리기 어려운 결정)

`surge_settings.py`의 `EnsembleWeightsConfig` 옆에 신규 `EnsembleHorizonLabelsConfig`
(가칭) 추가를 제안한다 — 정확한 클래스명·필드명은 구현 시 기존 명명 관례
(`snake_case`, `Config` 접미사)를 따라 확정한다:

| 탐지기 키 (기존 `weights`와 동일 키) | 제안 지평 라벨 | 근거 (Open Question 1 대상) |
|---|---|---|
| `theme_cluster` | `multi_day` | 48시간 뉴스 윈도우 스캔 |
| `volume_news_combo` | `same_day`(잠정, OQ1) | combo_score의 정확한 데이터 소스 재확인 필요 |
| `disclosure_pattern` | `same_day` | `best_disclosure_score` = `max(pattern_score, immediate_disclosure_score)` — 둘 다 당일/즉시 공시 기반 |
| `legacy_detectors` | `multi_day`(가중치 0 — 영향 없음) | 사용 중지 상태 유지 |
| `news_delayed` | `multi_day` | 24-72시간 지연 반응 |
| `volume_breakout` | `same_day` | 당일 장중 거래량 비율 |
| `momentum_continuation` | `next_day` | 전일(T-1) 등락률 기반 — SPEC-AI-065 REQ-3 |

신규 섹션은 `ensemble.weights`와 **독립**된 필드이며, 기존 `weights` dataclass/
pydantic 모델 구조는 무수정이다(REQ-AI100-001 필수 조건). 최상위에
`horizon_aware_thresholds.enabled: bool = False`(신규 섹션) 플래그를 추가한다.

### A.2 지평 시그니처 계산 (되돌리기 두 번째로 어려운 결정)

대상: `compute_ensemble_score`(1538-1608행) 반환 직후, 메인 루프(2192-2199행) 내부
— `compute_ensemble_score`가 이미 계산하는 `detector_groups`(news/disclosure/
technical, 1576-1584행)와 `active_groups`를 함수 스코프 밖으로 노출하거나(반환값을
튜플로 확장하거나 별도 헬퍼 함수로 재계산), 신규 헬퍼 함수
`_compute_horizon_signature(candidate, config)`(가칭)를 신설해 어떤 지평의 탐지기가
0 초과 스코어를 가졌는지 판정한다.

- `compute_ensemble_score`의 시그니처(인자·반환 타입)는 **변경하지 않는 것을
  우선 검토**한다 — 호출부가 3곳(메인 루프 2193행, 정렬 2290행 등)이므로 반환
  타입 확장은 모든 호출부 수정을 요구한다. 대신 지평 시그니처는 별도 헬퍼 함수로
  분리해 `compute_ensemble_score`를 무수정 유지하는 방향을 우선한다(구현 시
  재검토, `compute_ensemble_score` 무수정이 REQ-AI100-003 필수 조건과 직접
  연결됨).
- 지평 시그니처는 `same_day_dominant`(same_day 라벨 탐지기만 0 초과, 또는 same_day
  스코어 합이 다른 지평보다 우세) / `next_day_dominant` / `multi_day_dominant` /
  `mixed`(복수 지평이 비슷한 비중으로 기여) 중 하나로 산출한다 — 정확한 판정
  규칙(비교 방식)은 구현 시 A.1의 지평 라벨 확정과 함께 결정한다.

### A.3 지평 인식 임계값 선택 (되돌리기 세 번째로 어려운 결정)

대상: `effective_threshold` 조회(2184-2186행) 지점. `horizon_aware_thresholds.enabled`
가 `true`일 때만 레짐 × 지평 시그니처 2축 조회로 확장한다. `false`일 때는 기존
단일 레짐 조회 경로만 실행한다(REQ-AI100-003). 신규 임계값 표의 초기값은 Open
Question 2에 따라 기존 `regime_thresholds`와 동일값으로 시작하는 것을 제안한다
(플래그가 켜져도 당장은 동작 변화가 없도록, 안전한 초기 배포).

### A.4 `combo_chase_guard`/평가 순서 명문화 (기계적 배선, 되돌리기 쉬움)

대상: 코드 변경 없음 — Gate 4(2158-2174행)가 지평 시그니처 계산(A.2)보다 먼저
실행됨을 코드 주석 또는 함수 docstring에 명문화한다(REQ-AI100-004). 실제 실행
순서는 이미 그러하므로(merged 딕셔너리 필터링 → 메인 루프 스코어링), 순서를
바꾸는 코드 변경은 없다.

### A.5 섀도우 모드 비교 로깅 (기계적 배선, 되돌리기 쉬움)

대상: 메인 루프 종료 지점(2199행 이후) 또는 신규 헬퍼 함수. 플래그가 `false`인
동안, 매 사이클 신규 임계값 경로도 병행 계산해 qualified 집합 차이를 구조화 로그
(JSON 라인)로 남긴다(REQ-AI100-006). 예외 발생 시 `try/except` + 로그로 격리하고
기존 흐름에 영향을 주지 않는다.

### A.6 PRESERVE 목록 (수정 금지)

| 대상 | 사유 |
|------|------|
| `compute_ensemble_score()`의 가중합·컨센서스 배율 계산 본체 | REQ-AI100-003 필수 조건 — 무수정 유지 |
| 3개 bypass 루프(즉각 공시/강한 단일 신호/거래량 폭발) | design.md §E 결정 — 옵션 (b)는 이 루프들을 건드리지 않음 |
| `combo_chase_guard` Gate 4 판정 로직 자체 | REQ-AI100-004 — 순서만 명문화, 로직은 무수정 |
| `sector_contagion` 게이트(2303-2350행) | 무관 — 본 SPEC의 지평 시그니처와 독립적인 사후 필터 |
| `surge_threshold_service.py` 전체 | REQ-AI100-005 — 매수 실행 전용, 독립 유지 |
| `_is_same_day_event_horizon_signal()`(평가 계층) | REQ-AI100-008 — 무수정, 소비하지 않음 |
| `_maybe_trigger_event_rescan()`(SPEC-AI-066 재스캔) | REQ-AI100-008 — 무수정, 소비하지 않음 |
| `detect_weekend_gap_up_signals()`, `detect_bollinger_squeeze_signals()` | REQ-AI100-007 — 고아 상태 유지, 신규 배선 금지 |

## B. 작업 분해

### TASK-001: 신규 설정 스키마 + 기본값 배선 (REQ-AI100-001)

- 대상: `backend/app/surge_config/surge_settings.py`, `surge_detection.yaml`
- A.1의 지평 라벨 맵 + `horizon_aware_thresholds.enabled: false` 플래그 신규
  추가. 기존 `EnsembleWeightsConfig` 등 기존 스키마는 무수정.
- Open Question 1(지평 라벨 정확한 값, 특히 `volume_news_combo`)을 구현 시
  도메인 검증으로 확정.

추적: REQ-AI100-001 / AC-100-001

### TASK-002: 지평 시그니처 계산 헬퍼 (REQ-AI100-002)

- 대상: `backend/app/services/surge_detector.py`
- A.2에 따라 `compute_ensemble_score`를 무수정 유지하면서, 기존 `detector_groups`
  로직을 재사용/확장한 신규 헬퍼 함수를 추가한다.
- `@MX:SPEC` 서브라인에 `SPEC-AI-100 REQ-AI100-002` 추가.

추적: REQ-AI100-002 / AC-100-002

### TASK-003: 지평 인식 임계값 선택 배선 (REQ-AI100-003, REQ-AI100-005)

- 대상: `backend/app/services/surge_detector.py`(`effective_threshold` 조회 지점)
- A.3에 따라 플래그 분기 추가. `surge_threshold_service`에 대한 신규 import나
  참조는 추가하지 않는다(REQ-AI100-005 — 독립성 보존 확인).
- Open Question 2(임계값 초기값)에 따라 플래그 활성 시에도 기존 `regime_thresholds`
  와 동일값으로 시작.

추적: REQ-AI100-003, REQ-AI100-005 / AC-100-003, AC-100-004

### TASK-004: `combo_chase_guard` 평가 순서 명문화 (REQ-AI100-004)

- 대상: `backend/app/services/surge_detector.py`(주석/docstring만, 코드 로직
  변경 없음)
- A.4에 따라 Gate 4 → 지평 시그니처 계산 순서를 문서화.

추적: REQ-AI100-004 / AC-100-005a, AC-100-005b

### TASK-005: 섀도우 모드 비교 로깅 (REQ-AI100-006)

- 대상: `backend/app/services/surge_detector.py`
- A.5에 따라 플래그 `false` 상태에서 병행 계산 + 구조화 로그(diff) 추가. 예외
  격리 확인.

추적: REQ-AI100-006 / AC-100-006, AC-100-007

### TASK-006: 고아 탐지기/평가 계층/재스캔 무변경 확인 (REQ-AI100-007, REQ-AI100-008)

- 대상: 없음(신규 코드 아님) — `git diff`로 `detect_weekend_gap_up_signals`,
  `detect_bollinger_squeeze_signals`, `_is_same_day_event_horizon_signal`,
  `_maybe_trigger_event_rescan` 함수 본문에 변경이 없음을 확인하는 것 자체가
  이 TASK의 산출물이다.

추적: REQ-AI100-007, REQ-AI100-008 / AC-100-008, AC-100-009

### TASK-007: 무회귀·신규 검증

- 대상: 신규 `backend/tests/test_spec_ai_100.py`
- 케이스: 플래그 `false`일 때 바이트 동일 동작(기존 qualified 집합과 100% 일치),
  플래그 `true`일 때 지평 시그니처가 올바르게 산출되는지(fixture로 same_day/
  next_day/multi_day 우세 케이스 구성), 임계값 선택이 레짐 × 지평 조합을
  올바르게 조회하는지, `compute_ensemble_score`/3개 bypass 루프/`combo_chase_guard`/
  `sector_contagion`/`surge_threshold_service`/평가 계층/재스캔 메커니즘 무변경
  확인(diff grep), 섀도우 모드 로깅이 예외 시에도 기존 흐름을 막지 않는지.
- 기존 테스트(`test_spec_ai_017.py`, `test_spec_ai_030.py`, `test_spec_ai_092.py`류,
  실제 파일명은 구현 시 `ls backend/tests/`로 재확인) 전체 무수정 통과 확인.

추적: REQ-AI100-001~008 전체 / AC-100-001~009

### TASK-008: 섀도우→프로덕션 전환 게이트 체크리스트 (REQ-AI100-009)

- 대상: 본 plan.md §D(배포/롤백) — 신규 코드 없음, 문서화 산출물.
- A.1~A.5 구현이 모두 완료된 후, 플래그를 `true`로 전환하기 전 확인해야 할
  구조적 최소 요건 3가지(§D "전환 게이트" 참고)를 팀이 실제로 사용할 런북
  또는 체크리스트 형태로 명문화한다.
- Open Question 2(임계값 변화폭 상한 ±30%, 잠정)와 Open Question 3(관측
  거래일 ≥10일 + 3개 레짐, 잠정)의 정확한 수치는 섀도우 모드 관측 데이터
  축적 후 조정 가능하나, 체크리스트 항목 자체(3요건 존재)는 구현 시 생략할
  수 없다.

추적: REQ-AI100-009 / AC-100-011

## C. 검증 계획

타겟 테스트:

```powershell
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests\test_spec_ai_100.py -q
```

전체 회귀:

```powershell
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests -q -m "not slow"
```

정적 검사:

```powershell
.\backend\.venv\Scripts\ruff.exe check .\backend
.\backend\.venv\Scripts\python.exe -m mypy .\backend\app
```

범위 규율 grep (기존 검증된 가중합/게이트 로직 무변경 확인, REQ-AI100-003/004/005/007/008):

```bash
git diff backend/app/services/surge_detector.py -- :^backend/tests
# 기대: compute_ensemble_score() 함수 본문, 3개 bypass 루프, combo_chase_guard
# Gate 4 판정 조건, sector_contagion 게이트, detect_weekend_gap_up_signals/
# detect_bollinger_squeeze_signals 본문에 라인 변경이 없어야 한다(자동 grep만으로는
# 완전히 커버되지 않으므로 코드 리뷰 병행 — 신규 코드는 이 로직들 "주변"에 삽입되는
# 순수 추가만 허용한다).

git diff backend/app/services/surge_threshold_service.py backend/app/services/surge_evaluation_service.py backend/app/services/scheduler.py -- :^backend/tests
# 기대: 0 매치 — 본 SPEC은 이 3개 파일을 건드리지 않는다.
```

평가 지표 대조(섀도우 모드 활성화 후, 플래그 전환 전):

```bash
# 섀도우 모드 로그에서 기존/신규 qualified 집합 차이를 수동 검토
# (구체적 쿼리/스크립트는 TASK-005 구현 시 확정, plan.md 갱신 대상 아님 —
# 로그 포맷이 확정된 후 별도 관찰 절차로 문서화)
```

## D. 배포/롤백

TASK-001~002(신규 설정 + 헬퍼 함수 추가)는 플래그 `false` 상태에서 순수 추가이며
기존 매매/시그널 로직에 영향을 주지 않는다 — 배포 자체는 무해하다. TASK-003(임계값
선택 배선)은 플래그 조건부 분기이므로 플래그가 `false`인 한 무해하다. TASK-005
(섀도우 로깅)는 부가 관측 경로이며 예외 격리로 무해하다.

### 전환 게이트(REQ-AI100-009) — 구조적 최소 요건 3가지

플래그를 `false`에서 `true`로 전환하기 전, 다음 세 요건이 **모두** 충족되었는지
확인 절차의 일부로 요구한다(plan-auditor 1차 감사 반영, 2026-07-28
`theme_news_carry` 자기강화 피드백 루프 사고 재발 방지):

1. 섀도우 모드 관측 거래일 수 ≥ 10 거래일(잠정값, Open Question 3과 연계 —
   실제 확정은 관측 데이터의 변동성을 보고 판단).
2. 관측 기간 동안 BULL/SIDEWAYS/BEAR 3개 시장 레짐이 각각 최소 1회 이상
   관측됨.
3. 신규 지평 인식 임계값 경로의 qualified 후보 집합이 기존 경로 대비
   ±30%(잠정값, Open Question 2와 연계) 이내로 유지됨 — 초과 시 전환을
   보류하고 재조사한다.

세 요건 중 하나라도 미충족이면 전환을 진행하지 않는다. 수치 자체(10 거래일,
±30%)는 섀도우 모드 관측 데이터 축적 후 조정 가능하나, 이 세 요건이 존재해야
한다는 게이트 구조 자체는 계획 단계에서 확정한다(REQ-AI100-009, AC-100-011).

롤백 트리거:

- 섀도우 모드 로그 관찰(design.md §I, 기본 10 거래일) 중 신규 지평 인식 임계값
  경로가 기존 경로 대비 qualified 집합을 비정상적으로 축소/확대시키는 패턴 발견
  → 지평 라벨 맵(A.1) 또는 임계값 초기값(A.3)을 재검토
- 플래그 활성화 후 스코어링 사이클 소요 시간이 유의하게 증가 → 지평 시그니처
  계산 로직(A.2)을 조사, 필요 시 플래그를 즉시 `false`로 되돌림(신규 설정/헬퍼
  함수는 그대로 두어도 무해)
- 섀도우 로깅이 기존 시그널 생성 흐름에 영향을 주는 사례 발견(TASK-005 예외
  격리 실패) → 즉시 되돌림, TASK-007에 회귀 케이스 추가
- 전환 게이트(위, REQ-AI100-009) 3요건 중 하나라도 미충족 상태에서 전환이
  시도됨 → 전환을 보류하고 미충족 요건을 재조사(신규 코드 롤백 대상 없음 —
  전환 자체를 진행하지 않는 것이 조치)

롤백 단위: 플래그 `false` 전환 1줄로 완전 복구(설정/헬퍼 함수는 독립적으로
존재해도 무해). DB 마이그레이션이 없으므로 스키마 롤백 이슈가 없다(design.md §K).

## E. 리스크

- **지평 라벨 분류(A.1)가 실제 탐지기 동작과 어긋날 위험**: 특히
  `volume_news_combo`(combo_score)의 정확한 데이터 소스가 순수 당일 신호인지
  다일 요소를 포함하는지 재확인이 필요하다(Open Question 1). 오분류 시 지평
  시그니처가 잘못 산출되어 임계값 선택이 왜곡될 수 있다 — 섀도우 모드 관찰이
  이를 조기에 발견하는 안전망이다.
- **`compute_ensemble_score` 무수정 유지가 지평 시그니처 계산의 정확도를 제한할
  위험**: `detector_groups`(news/disclosure/technical)는 지평이 아닌 "이벤트
  유형"으로 그룹핑되어 있어, 지평 시그니처로 직접 재활용할 때 근사(approximation)가
  발생할 수 있다(예: news 그룹 = theme_cluster(다일) + combo(당일 잠정) 혼합).
  design.md §B에서 이 근사를 의도적으로 선택했으나(비용 대비 이득), 실제 구현
  시 근사 오차가 예상보다 크면 지평 시그니처 계산을 detector_groups와 독립적으로
  재설계해야 할 수 있다.
- **섀도우 모드 관측 기간(기본 10일 제안)이 실제 변동성을 포착하기에 부족할
  위험**: 시장 레짐 변화(BULL/SIDEWAYS/BEAR)가 10일 내에 모두 발생하지 않으면
  일부 레짐 × 지평 조합이 전혀 관측되지 않은 채 플래그가 전환될 수 있다 — 이
  위험은 REQ-AI100-009(D6, 2026-08-03 plan-auditor 1차 감사 반영)가 "3개 레짐
  전량 관측"을 전환 게이트의 구속력 있는 최소 요건으로 확정하며 완화되었다
  (§D "전환 게이트" 참고). 남은 잔여 위험은 그 하한을 넘어서는 실제 관측
  기간의 적정성 판단뿐이다.
- **고아 탐지기(weekend_gap_up, bollinger_squeeze) 배선 유예가 장기 방치로
  이어질 위험**: 본 SPEC이 명시적으로 범위 밖으로 남겼으나(D4), 후속 SPEC이
  실제로 계획되지 않으면 이 2개 탐지기는 계속 관측 전용으로 남는다 — 이는
  알려진 트레이드오프이며 본 SPEC의 범위를 벗어난다.
