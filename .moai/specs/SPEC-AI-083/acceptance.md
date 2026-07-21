# Acceptance Criteria: SPEC-AI-083 — 장중 고빈도 재스캔 + 이벤트드리븐 즉시발화 활성화

검증은 (1) 스케줄러 잡 등록/속성(잡 id·트리거 시각·`max_instances`/`coalesce`), (2) 재스캔 후보의
same-day 지평 귀속(관찰 가능한 `surge_metadata`/평가 서브지표 편입), (3) 뉴스 이벤트 재스캔 활성화 및
가드 준수, (4) 공통 불변식 diff 0으로 고정한다. 실제 12~20분 gather HTTP 지연은 재현하지 않으며, 후보
생성 경로는 mock으로 대체해 잡/메타데이터/설정 거동을 결정적으로 검증한다. 매매/발신 부작용은 검증
대상이 아니다(예측 기록 모드).

모든 AC는 EARS(Ubiquitous/Event-Driven/State-Driven/Unwanted/Optional) 문장 패턴으로 서술한다. RED(수정
전 특성화)와 GREEN(수정 후 목표) 거동이 모두 있는 AC는 각각 별도 문장으로 구분한다(DDD 재현 우선).

**중요 — 전제 정정 고지 (spec.md HISTORY, §2 [E-4]/[E-6] 참조):** 작업 지시 전제와 달리
`immediate_surge.enabled`는 이미 `true`(2026-07-16)이고, `surge_check_exits` 5분 잡은 비활성이다. 본
acceptance는 이 정정된 현실을 기준으로 방향 B를 회귀 보호(공시) + 뉴스 재스캔 활성화로 검증한다.

---

## AC-083-001 (REQ-001/013, 장중 고빈도 재스캔 잡 등록) [HARD]

- **WHEN** 스케줄러가 기동되면, the system **SHALL** 09:05~BUY_CUTOFF(11:00) 구간에 기존 10:00 스캔
  외에 **최소 2개 이상의 추가 당일 후보 생성 잡**을 등록한다(예: ~09:10 조기 스캔 포함, ~20분 간격).
  각 잡은 `run_surge_signal_generation`을 재사용하는 콜백을 사용하며 distinct `id`로 등록된다.
- the system **SHALL** 각 재스캔 잡을 `max_instances=1`, `coalesce=True`, `replace_existing=True`로
  등록한다(기존 `surge_signal_generate_intraday` 속성 계승, spec.md §2 [E-1]).
- 근거: 단일 10:00 스캔이 장 초반 급등을 놓치는 구조를 다잡 확장으로 교정. 정확한 시각·개수·간격은
  plan.md §1에서 확정하되, "10:00 외 추가 조기/장중 잡 존재 + 지정 속성"을 하한으로 고정한다.

---

## AC-083-002 (REQ-002/003, 겹침 방지 — gather 소요 대비 유계) [HARD]

- **WHILE** 직전 재스캔의 gather가 아직 실행 중이면, the system **SHALL** `max_instances=1` +
  `coalesce=True`로 다음 트리거의 중복 실행을 방지한다(겹침 없음). 테스트는 잡 속성으로 이 보장을
  확인한다(실제 지연 재현 없이 등록 속성 검증).
- the system **SHALL NOT** gather 정상 소요(12~15분)보다 짧은 간격을 유계 없이 설정해 스캔을 무한
  누적시켜서는 안 된다 — 재스캔 시각 간 최소 간격이 spec.md/plan.md에 명시된 근거(gather 소요 +
  헤드룸) 이상임을 값 회귀 가드로 고정한다.

---

## AC-083-003 (REQ-004, 장 초반 사각지대 처리) [HARD]

- **WHEN** 09:00~10:00 구간이 대상이면, the system **SHALL** (택1, plan에서 확정) (a) 조기 스캔
  (09:05~09:15 구간 잡)을 최소 1회 실행하거나, (b) 그 구간에 이미 실현된 급등을 명시적으로
  "미탐(miss)"으로 정확히 집계한다. 테스트는 채택된 정책의 관찰 가능한 증거(조기 잡 등록 존재 또는
  miss 집계 경로)를 검증한다.
- 근거: 09:51 KST에 이미 +29% 실현된 종목을 10:00 스캔이 못 잡는 사각지대를 조기 스캔으로 축소하거나,
  최소한 그 미탐을 지표에서 정확히 드러낸다.

---

## AC-083-004 (REQ-005, 당일 후보 same-day 지평 귀속 — RED/GREEN) [HARD]

**핵심 시나리오.** 장중(T) 재스캔이 당일 급등 예측 후보를 생성해도 same-day 귀속이 없으면 recall이
움직이지 않는 지평 불일치를 교정한다.

- (RED, 특성화) 장중 재스캔이 생성한 당일 후보에 same-day 지평 태깅이 없으면, **WHEN**
  `evaluate_surge_predictions`가 실행되면 the system **SHALL** 그 후보를 표준 `date(created_at)==T-1`
  버킷으로 처리한다(당일 캐치가 T+1 급등과 비교되어 same-day recall에 미편입 — 이 거동을 특성화 테스트가
  포착한다).
- (GREEN, 목표) 장중 재스캔이 당일 급등 예측 후보를 생성하면, the system **SHALL** 그 후보의
  `surge_metadata`에 `horizon="same_day"`를 부여하고, `_is_same_day_event_horizon_signal`
  (surge_evaluation_service.py:506)이 이를 표준 predicted_set에서 배제해 **별도 same-day 서브지표로
  집계**되게 한다(SPEC-AI-080 평가 경로 재사용, 스키마 변경 없음).
- 근거(spec.md [R-4]): same-day 귀속 누락은 SPEC 목적을 무효화하는 최상위 리스크이므로 관찰 가능
  증거(메타데이터 + 서브지표 편입)로 검증한다.

---

## AC-083-005 (REQ-007, 공시 즉시발화 회귀 보호) [HARD]

- **IF** 본 SPEC의 방향 A 변경이 적용되면, **THEN** the system **SHALL NOT**
  `immediate_surge.enabled`(=true), `_create_immediate_surge_signal`,
  `_classify_disclosure_horizon`, `_is_same_day_event_horizon_signal`의 거동을 변경한다 — 코드/설정
  diff 0으로 확인한다.
- **WHILE** 기존 SPEC-AI-080 테스트(`test_surge_ai080_fund_manager.py` 등)가 실행되는 동안, the system
  **SHALL** 전체 케이스를 코드 변경 없이 그대로 통과시킨다.
- 근거(정정-1): 방향 B의 공시 절반은 2026-07-16에 이미 완료됨. 본 AC는 그 상태가 방향 A로 회귀하지
  않음을 보장한다.

---

## AC-083-006 (REQ-008/009, 뉴스 이벤트 재스캔 활성화 + 가드 준수 — 확정 범위, 사용자 승인 2026-07-21)

- **WHEN** `catalyst_conviction.event_rescan_enabled`가 `true`로 설정된 상태에서 고확신 뉴스가 도착하면
  (keyword_matching 완료 훅), the system **SHALL** `_maybe_trigger_event_rescan`을 통해 이벤트 재스캔을
  발화한다(surge_detection.yaml 플립 + 인프라 재사용, 신규 인프라 구현 없음).
- **WHILE** 이벤트 재스캔이 활성인 동안, the system **SHALL** 종목당 쿨다운(30분)과 일일 상한(20회)
  가드를 준수한다 — 쿨다운 내 재트리거 차단 및 일일 상한 도달 시 추가 발화 차단을 테스트로 확인한다.
- the system **SHALL NOT** 가드 값(쿨다운/일일 상한)을 변경한다(플래그 활성화만, [X-8]).
- 근거([R-3]): 활성화는 설정 플립이며, precision 일시 저하는 예측 기록 모드라 자금 리스크 0. 롤백=플래그
  false 복귀. **뉴스 트리거 정밀도(고확신 뉴스→실제 급등 상관)는 활성화만으로 검증되지 않으므로**,
  활성화 후 첫 수 거래일간 이벤트 재스캔 발화 로그·precision을 관측해 트리거 품질을 사후 검증한다
  (Optional/관측성 AC, 값 회귀 게이트 아님).

---

## AC-083-007 (REQ-010/011/012, 공통 불변식 diff 0) [HARD]

- **IF** 본 SPEC의 변경이 적용되면, **THEN** the system **SHALL NOT** 다음을 변경한다:
  `gather_surge_candidates`(탐지 본체)·앙상블 점수/가중치/임계·스캔 유니버스 구성, 15:20 T-1→T 배치
  크론 시각·표준 평가 지평, BUY_CUTOFF(11:00) 값/비교 로직, 매수·매매·포트폴리오 로직 — 코드 diff 0으로
  확인한다.
- the system **SHALL NOT** 비활성된 매수/청산 잡(`surge_execute_buys`/`surge_check_exits`/
  `force_max_holding_exit`)을 되살리거나 `execute_signal_trade`를 호출한다(예측 기록 모드, [X-3]).
- 근거: 재스캔/즉시발화는 기존 배치를 보완(additive)할 뿐 대체하지 않는다.

---

## AC-083-008 (REQ-002/005, 재현·특성화 테스트 선행 — DDD 재현 우선) [HARD]

- **IF** 재스캔 잡 확장 또는 same-day 귀속 배선 변경이 이루어지면, **THEN** the system **SHALL** 그
  변경 이전에 (a) 현행 단일 10:00 잡 상태와 (b) same-day 귀속 부재 시 표준 T-1→T 버킷 처리 거동을
  포착하는 특성화 테스트가 먼저 작성·실행되어 기준선이 확인된 이후에만 IMPROVE로 진행한다(CLAUDE.md
  Rule 4, DDD ANALYZE-PRESERVE).
- the system **SHALL** 전체 백엔드 회귀 스위트를 무회귀로 통과한다: `cd backend && uv run pytest
  tests/ --tb=short -q -m "not slow"`(기본) 및 `-n 4`(xdist) 양쪽.
- the system **SHALL** `cd backend && uv run ruff check .`를 무경고로 통과하고, `uv run mypy app/`을
  프로젝트 기존 상태 대비 회귀 없이 통과한다.

---

## AC-083-009 (REQ-013, 최소 간격 근거 명시 — 관측성)

- **WHERE** 재스캔 간격/시각이 결정된 경우, the system **SHALL** 그 값의 근거(gather 정상 소요 12~15분,
  최악 20분, Naver/DART 크롤 부하)를 spec.md/plan.md에 명시하고, 재스캔 잡 등록 지점에 `@MX:NOTE`
  (+`@MX:SPEC: SPEC-AI-083`)로 스케줄 근거와 겹침 방지 원칙을 기록한다.
- 근거: 후속 유지보수자가 "왜 이 간격인가 / 왜 분 단위가 아닌가"를 gather 제약([E-3])과 함께 이해할 수
  있도록 한다.

---

## Definition of Done

- [ ] AC-083-001~008 전부 통과(004/008은 RED→GREEN 재현 우선 순서 준수). 009는 관측성/문서(P2 성격).
- [ ] 09:05~BUY_CUTOFF 구간에 10:00 외 추가 재스캔 잡(조기 스캔 포함) 등록, 각 잡 `max_instances=1`/
      `coalesce=True`/distinct id, 콜백은 후보 생성만 호출(매수/청산 미참조).
- [ ] 장중 재스캔 당일 후보가 same-day 지평(`horizon="same_day"`)으로 귀속되어 SPEC-AI-080 same-day
      서브지표에 편입됨(스키마 변경 없음).
- [ ] `immediate_surge` 활성 상태 + same_day 평가 경로 회귀 보호(diff 0), 기존 SPEC-AI-080 테스트 무회귀.
- [ ] `catalyst_conviction.event_rescan_enabled: true` 활성화 + 쿨다운/일일 상한 가드 준수(값 불변).
- [ ] 탐지 본체·앙상블·가중치·임계·유니버스·15:20 배치 크론·평가 지평·BUY_CUTOFF·매매 로직 diff 0.
      비활성 매수/청산 잡 미복구, `execute_signal_trade` 미호출.
- [ ] 신규 테이블/마이그레이션 없음. 과거 데이터 백필 없음(전진 적용).
- [ ] 재스캔 간격/시각 근거가 spec.md/plan.md에 명시되고, 잡 등록 지점에 `@MX:NOTE`(+`@MX:SPEC`) 기록.
- [ ] 신규/변경 로직 커버리지 85%+, `ruff` 무경고, `mypy` 회귀 없음.
- [ ] 전체 백엔드 스위트 회귀 없음 — 로컬 기본 실행 + `-n 4`(xdist) 병렬 양쪽 확인.
- [x] **전제 정정 2건(immediate_surge 이미 활성 / surge_check_exits 비활성)과 방향 B 재범위화가
      오케스트레이터를 통해 사용자에게 고지되어 annotation 단계에서 확인 완료 — 사용자가 REQ-AI083-008
      (뉴스 재스캔 활성화) 포함(권장안)을 승인(2026-07-21). 방향 B 범위 확정.** (Plan 게이트 충족;
      아래 구현 DoD 항목은 Run 단계 대상)
