# Acceptance Criteria: SPEC-AI-080

동일-당일 고확신 공시 촉매의 즉시 급등 시그널 발화의 인수 기준.

## Given-When-Then Scenarios

### Scenario 1 (P0) — T-1 종가 이후 고확신 촉매 → 즉시 발화 + recall 편입

**Given** T-1 15:20 KST 배치 스캔 종료 이후(예: 16:41 KST) 고확신 이벤트 클래스 공시(예:
단일판매·공급계약체결)가 접수되고, 그 공시의 `impact_score`(계약금액/시총 스케일)가 발화 임계
(`immediate_surge_min_impact`) 이상인 상태에서,

**When** `process_disclosure_impact()`가 그 공시를 수집하면,

**Then**
- 30분 `run_reflection_check`/`detect_unreflected_gap` 게이트를 기다리지 않고 즉시
  `signal_type="surge_candidate"`(+`surge_metadata` same-day-event-driven 근거) 시그널이 발화되고,
- 그 시그널의 `created_at`(T-1)이 `evaluate_surge_predictions`의 T-1→T `predicted_set` 버킷에
  편입되어 `scannable_recall`에 집계된다.

- 실증 대응: 신테카바이오(226330) 07-09 16:41 접수 → 07-10 급등 유형.

### Scenario 2 (P0) — 급등 당일(T) 장중 접수분 → T-1 버킷 배제 + 별도 서브지표

**Given** 급등 당일(T) 장중(예: 10:00 KST)에 고확신 촉매 공시가 접수되어 즉시 발화되는 상태에서,

**When** `evaluate_surge_predictions`가 실행되면,

**Then**
- 그 당일-접수 시그널은 표준 T-1→T `predicted_set`에 **포함되지 않고**(SPEC-AI-075 지평 태깅
  배제 패턴 재사용),
- 대신 별도로 라벨링된 same-day 이벤트 서브지표에 집계된다.

- 근거: "내일 예측(T-1→T)"과 "오늘 촉매 포착(T→T)"의 지평 혼입 방지(spec.md REQ-004 둘째 규칙).

### Scenario 3 (P0) — 저확신/범용 공시는 즉시 발화 안 됨 (오탐 통제)

**Given** 고확신 이벤트 클래스가 아닌 범용 공시(지분공시/정기공시/루틴 거버넌스) 또는 고확신
클래스이나 `impact_score`가 발화 임계 미만(예: 소액 보일러플레이트 계약)인 상태에서,

**When** `process_disclosure_impact()`가 그 공시를 수집하면,

**Then** 즉시 발화 경로가 **실행되지 않고**, 기존 동작(장중=30분 반영 체크 예약 / 장마감후
impact>=25=gap_pullback / 그 외 무발화)만 수행된다.

- 근거: REQ-003(클래스 한정) + REQ-002(impact_score 게이팅). 루틴 거버넌스는 5점 캡으로 자연 배제.

### Scenario 4 (P0) — 예측 기록 전용 (페이퍼 트레이딩 미배선)

**Given** 즉시 발화 경로가 surge_candidate 시그널을 생성한 상태에서,

**When** 그 시그널 생성 흐름을 확인하면,

**Then** `execute_signal_trade`(페이퍼 트레이딩 실행)가 **호출되지 않는다**(SPEC-AI-043 예측 기록
모드 일관). 시그널은 예측/recall 추적 목적으로만 존재한다.

- 근거: 기존 `_create_disclosure_signal`의 `execute_signal_trade` 호출(`:519-520`)을 신규 경로가
  답습하지 않음(REQ-005).

### Scenario 5 (P1) — 중복 행 방지 (기존 네이티브 업서트가 즉시 발화 경로 추가 후에도 계속 동작함)

**Given** 배치 윈도우(~15:20 KST) 이전에 접수된 고확신 공시가 (a) 즉시 발화 경로와 (b) 같은 날
T-1 배치 스캔 양쪽에서 잡히는 상태에서 — 코드베이스에는 **SPEC-AI-080 이전부터** 5역일 재탐지 업서트
(fund_manager.py:1436-1464)가 존재해, 같은 `stock_id`+`signal_type=="surge_candidate"` 기존 행을 찾으면
신규 INSERT 대신 UPDATE로 처리한다(네이티브 업서트-기반 디듀프),

**When** 두 경로가 모두 실행되면,

**Then** 동일 (종목, 영업일)에 대해 `predicted_set`에 **중복 surge_candidate 행이 생성·집계되지 않는다**
— 즉시 발화 경로는 이 기존 업서트의 조회 키(stock_id+signal_type)에 정합해야 하며, 본 시나리오는 새 디듀프
계층 구축이 아니라 **기존 업서트-기반 디듀프가 즉시 발화 경로 추가 후에도 올바르게 유지됨**을 검증한다
(REQ-006은 "신규 디듀프 신설"이 아니라 "기존 메커니즘 인지·통합").

- 연계: **Scenario 7은 같은 업서트의 반대편 우려**를 다룬다 — 이 업서트가 중복 행은 막지만 그 수단이 기존
  행을 UPDATE하며 `created_at`을 덮어쓰는 것이라, 즉시 발화 시그널의 T-1 귀속이 그 덮어쓰기에 훼손되지
  않도록 보존되어야 한다(DP-1 마커 인지형 스킵). Scenario 5(중복 미생성)와 Scenario 7(귀속 보존)은 동일
  메커니즘의 두 측면이다.

### Scenario 6 (P0, 하위호환) — 즉시 발화 비활성 시 레거시 동작 불변

**Given** `surge_detection.yaml`의 `immediate_surge.enabled`가 `false`(레거시)인 상태에서,

**When** `process_disclosure_impact()` 및 `evaluate_surge_predictions`가 실행되면,

**Then** 즉시 발화 경로가 전혀 실행되지 않고, 기존 이벤트 구동 경로(반영 체크/gap_pullback/
disclosure_impact 시그널)와 T-1 배치 recall 집계가 **완전히 이전과 동일**하다(rollback 완전성 보장).

### Scenario 7 (P0, v0.2.0) — 즉시 발화 시그널의 T-1 귀속이 익일 배치 재탐지·캐리오버에도 보존됨

**Given** 즉시 발화 경로가 T-1(예: 07-09 16:41 KST)에 `surge_candidate` 시그널(created_at=T-1,
즉시 발화 식별 마커 포함 `surge_metadata`)을 생성한 상태에서,

**When** 익일 T(예: 07-10)에 **같은 종목**이 정규 T-1 배치 스캔(10:00 또는 15:20 KST)에 의해
독립적으로 재탐지되어 재탐지 업서트(fund_manager.py:1436-1464)를 타거나, 재탐지되지 않아도 SPEC-AI-039
캐리오버(fund_manager.py:1542-1597) 대상이 되어 5역일 윈도우 내에서 다시 처리되고, 그 후 18:30 KST
평가(`evaluate_surge_predictions`)가 실행되면,

**Then**
- 즉시 발화 시그널의 `created_at`은 **T-1로 보존**되어(배치·캐리오버가 T로 덮어쓰지 않음),
  `date(created_at)==T-1` 버킷에 계속 포함되어 `scannable_recall` 귀속이 **소실되지 않고**,
- 즉시 발화 식별 마커(`surge_metadata`)도 배치 업서트의 metadata 교체(`:1449`)에 의해 **소실되지 않는다**.

- 근거: spec.md [E-9] + REQ-004 T-1 귀속 불변식. 배치(10:00·15:20)가 평가(18:30)보다 먼저 실행되므로
  보호가 없으면 이 귀속은 안정적으로 사라진다(R-6). 실증 대응: 신테카바이오(226330) 07-09 발화 → 07-10 재탐지 유형.

## Edge Cases (엣지 케이스)

- [EC-1] `market_cap`이 None/0인 종목의 계약 공시: `score_disclosure_impact`가 계약금액/시총 경로를
  못 타 기본값 점수로 회귀 → 발화 임계 미달 시 즉시 발화 안 됨(오탐 방지, 무회귀).
- [EC-2] `extract_contract_amount`가 금액 추출 실패(None): 계약 스케일 불가 → impact_score 기본값 →
  임계 미달 시 미발화.
- [EC-3] 심야(00:00~09:00 KST) 접수 공시: `created_at` UTC/KST 날짜 경계 교차 시 버킷 오편입 가능
  (R-5/OQ-1) → Run 단계 타임존 검증으로 보정. 테스트로 경계 케이스 고정.
- [EC-4] 동일 공시 재수집/중복 저장: 동일 disclosure_id에 대해 중복 시그널 미발화(REQ-006 디듀프와
  정합).
- [EC-5] 즉시 발화 종목이 실제로 T에 급등하지 않음: FP로 집계되어 precision 하락에 반영 — 정상
  동작(측정 목적). R-1 관측 대상.
- [EC-6] 고확신 공시이나 접수 시각이 배치 윈도우 이전이고 배치가 이미 잡음: 중복 방지로 이중집계
  회피(Scenario 5).
- [EC-7] (v0.2.0) 즉시 발화 종목이 T에 재탐지되지도, 캐리오버 임계(decayed>=0.50)도 못 넘는 경우:
  두 덮어쓰기 경로(fund_manager.py:1464/:1597) 모두 미해당이라 created_at이 원래 T-1로 유지됨(보호
  분기 없이도 정상). 단 이는 사실상 급등/모멘텀 유지 실패 케이스 — 보호의 실익은 재탐지·캐리오버되는
  진짜 양성에 있음(spec.md [E-9] 정직한 범위 한정).
- [EC-8] (v0.2.0) 즉시 발화 시그널의 `surge_metadata`가 None/누락: `surge_metadata.isnot(None)`
  (surge_evaluation_service.py:554)에서 signal_type·날짜가 맞아도 침묵 배제 → predicted_set 미포함.
  발화 경로가 마커 포함 non-None metadata를 항상 기록하는지 회귀 테스트로 고정.

## Quality Gate Criteria (품질 게이트)

- 재현 우선(Rule 4): Scenario 1(T-1편입) / Scenario 2(당일 분리) / **Scenario 7(익일 배치 재탐지·
  캐리오버에도 T-1 created_at 보존, v0.2.0)**을 재현하는 실패→통과 테스트가 수정 전 작성·확인됨.
- `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"` — 전체 회귀 통과.
  - CI 재현 시 `-n 4` xdist로도 확인(과거 `surge_detection.auto.yaml` 워커 공유 레이스 이력).
- `cd backend && uv run ruff check . && uv run mypy app/` — 통과.
- 신규/변경 로직 커버리지 85%+.
- 기존 이벤트 구동(`test` 스위트), 평가(`test_surge_evaluation_service.py`), 배치 업서트·캐리오버
  (fund_manager, SPEC-AI-012/039) 무회귀 — **마커 미검출 시 두 덮어쓰기 사이트(fund_manager.py:1464/:1597)
  거동이 비트 단위로 불변**임을 회귀 테스트로 보장. 이 두 사이트는 본 SPEC 범위 밖 다른 surge_candidate
  생산자(near_limit_up_carry/insider/theme_carry/forum/group_cascade 등)의 행도 공유 조회 키로 덮어쓰므로,
  무회귀 검증은 이들 생산자 행에 대해서도 수행해야 한다(spec.md R-7).

## Definition of Done (완료 정의)

- [ ] REQ-AI080-001: 고확신 클래스 + impact_score 임계 충족 시 수집 시점 즉시 발화(반영 게이트 우회).
- [ ] REQ-AI080-002: 게이팅은 계약금액/시총 스케일 `impact_score` 기준(surge_detector flat 0.82 미사용).
- [ ] REQ-AI080-003: 소수 고확신 이벤트 클래스로 한정, 범용 공시 미발화(Scenario 3).
- [ ] REQ-AI080-004: T-1 접수분 recall 편입(Scenario 1) + 당일 접수분 지평 분리 서브지표(Scenario 2).
- [ ] REQ-AI080-004 불변식(v0.2.0): 즉시 발화 시그널의 `created_at`(T-1)이 익일 배치 재탐지 업서트
  (fund_manager.py:1464)·SPEC-AI-039 캐리오버(fund_manager.py:1597) 실행 후에도 보존됨(Scenario 7).
- [ ] 부차 발견(v0.2.0): 즉시 발화 시그널이 `surge_metadata`를 **non-None**으로 기록함 — 미기록 시
  signal_type·날짜가 맞아도 `surge_metadata.isnot(None)`(surge_evaluation_service.py:554)로 recall에서
  **침묵 배제**됨(EC-8). 마커는 `_is_near_limit_up_carry_signal`에 near_limit_up_carry로 오판되지 않음.
- [ ] REQ-AI080-005: 신규 발화 경로에서 `execute_signal_trade` 미호출(Scenario 4).
- [ ] REQ-AI080-006(v0.2.0 개정): 기존 5역일 업서트·캐리오버와 통합해 중복 surge_candidate 미집계 +
  즉시 발화 행 created_at·마커 보존(Scenario 5/7). 마커 미검출 시 기존 거동 완전 불변.
- [ ] REQ-AI080-007 (P2): (채택 시) 즉시 발화 신호량/구성 집계 로그·서브지표, 스키마 변경 없음.
- [ ] Scenario 6: `immediate_surge.enabled=false`에서 레거시 동작 완전 불변(rollback 완전성).
- [ ] OQ-1(타임존)/DP-1(기존 업서트·캐리오버 마커 인지형 통합, v0.2.0 개정)/DP-2(서브지표 영속화)/
  OQ-5(마커 형태) Run 전 확정 기록.
- [ ] 배포 후 며칠간 `scannable_recall`/precision/신호량 관측(R-1/R-2 완화) + 즉시 발화 종목의 T-1 귀속이
  익일 배치 실행 후에도 유지되는지 확인(R-6 완화).
