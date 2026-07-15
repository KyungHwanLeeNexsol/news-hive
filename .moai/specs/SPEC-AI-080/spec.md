---
id: SPEC-AI-080
version: 1.0.0
status: completed
created: 2026-07-14
updated: 2026-07-15
author: Nexsol
priority: High
issue_number: null
lifecycle_level: 1
---

# SPEC-AI-080: 동일-당일 고확신 공시 촉매의 즉시 급등 시그널 발화 (Same-Day High-Conviction Disclosure → Immediate Surge Signal)

## HISTORY

- 2026-07-15 (v1.0.0): **완료** (commit `66776b6`). DDD ANALYZE-PRESERVE-IMPROVE로 T0~T10 전 태스크
  구현 완료. 신규 테스트 3개 파일(102 tests) 포함 전체 회귀 스위트 통과(1978 passed, 4 skipped,
  3 xpassed, failures 0), ruff clean. 상세는 아래 "Implementation Notes" 섹션 참조.
- 2026-07-14 (v0.1.0): 최초 작성. 2026-07-14 근본원인 조사(DB 포렌식 + 코드 추적)로 확정된
  **예측 지평 불일치(horizon mismatch)** 를 SPEC화. `scannable_recall`이 사전 선별된 T-1 스캔
  유니버스 종목에 대해서도 ~0%(07-06 0.0625, 07-07/08/10 0.0)로 정체된 근본 원인은 탐지기 임계 튜닝이
  아니라 **"측정되는 예측은 T-1 15:20 KST 배치 스캔 1회인데, 실제 +30% 상한가 촉매는 대부분 급등
  당일(T) 또는 T-1 배치 종료 이후에 공시/보도된다"** 는 구조적 시점 불일치임. 이미 존재하는
  이벤트 구동 공시 경로(`disclosure_impact_scorer.py`)를 **repurpose**하여, 고확신 당일 촉매가
  DART 수집 시점에 즉시 급등-집계 시그널을 발화하도록 복구/전용화하는 것이 목표.
  research 단계에서 제안 메커니즘 대비 **2건의 정정/단순화**를 발견함(§2 [E-7], [E-8] 참조):
  ① 이벤트 구동 경로는 이미 계약금액/시총 스케일된 `impact_score`를 보유(surge_detector의 flat 0.82
  상수 교체 불필요), ② 지배적 미탐 표본이 "T-1 종가 이후 공시"라 즉시 발화 시 `created_at`이 T-1로
  기록되어 기존 recall 버킷에 자연 편입됨(별도 지표 없이도 지배적 갭이 닫힘).

- 2026-07-14 (v0.2.0): 독립 코드 리뷰(read-only)로 발견한 구조적 리스크 반영 — **T-1 배치 스캔
  자신의 `surge_candidate` 영속화 로직이 `created_at`을 무조건 덮어써 즉시 발화 시그널의 T-1 귀속을
  파괴**할 수 있음(§2 [E-9] 신설). `fund_manager.py:1436-1464`(재탐지 업서트; 실제 윈도우는 주석의
  "5영업일"과 달리 `timedelta(days=5)`=5역일)와 `fund_manager.py:1542-1597`(SPEC-AI-039 48h 캐리오버,
  **별개 경로**)가 각각 `existing.created_at`/`prev.created_at = datetime.now(...)`로 덮어씀. 배치 스캔
  (10:00·15:20 KST, scheduler.py:2402/2386)이 평가(18:30 KST, scheduler.py:809/838)보다 먼저 실행되므로
  덮어쓰기가 평가 전에 안정적으로 반영됨 → [E-8]의 "created_at이 T-1로 남아 자연 편입"이라는 가정이
  불완전함을 코드·스케줄 대조로 확정. REQ-004에 **T-1 created_at 귀속 불변식** 추가, REQ-006을
  "신규 디듀프 설계" → "기존 네이티브 업서트/캐리오버 인지·통합"으로 개정. plan.md DP-1 권장을
  (i) 신규 디듀프 → **마커 인지형 덮어쓰기 스킵(기존 업서트/캐리오버 통합)**으로 변경. 부차 발견:
  predicted_set 필터의 세 번째 조건 `surge_metadata.isnot(None)`(surge_evaluation_service.py:554)를
  [E-1]에 명시하고 DoD 체크리스트 라인으로 승격(즉시 발화 시그널이 surge_metadata 미기록 시
  signal_type·날짜가 맞아도 recall에서 침묵 배제됨). Scenario 7(재탐지·캐리오버 귀속 보존) 신설.

- 2026-07-14 (v0.2.1): 2차 독립 리뷰(신규 코드 조사 없음 — 기존 내용 정합성 정리)로 발견한 2건의
  좁은 정정. ① acceptance.md Scenario 5 문구를 v0.1.0 잔재("디듀프 또는 배치 윈도우 이후 한정 —
  DP-1 결정에 따름")에서 v0.2.0 DP-1 결정(마커 인지형 스킵 — 네이티브 업서트/캐리오버 통합)에 맞게
  개정. 5역일 네이티브 업서트(fund_manager.py:1436-1464)는 SPEC-AI-080 **이전부터** 기존 행을 찾으면
  UPDATE로 처리해 중복 INSERT를 막아왔으므로, Scenario 5는 "새 디듀프 계층 구축"이 아니라 "**기존
  업서트-기반 디듀프가 즉시 발화 경로 추가 후에도 올바르게 유지됨**"을 검증함을 명확화하고, 동일
  업서트의 반대편 우려(덮어쓰기가 T-1 귀속을 보존해야 함)를 다루는 Scenario 7과 상호 참조. ② 공유
  고 fan_in 영속 코드(`fund_manager.py:1436-1464`/`:1542-1597`)가 본 SPEC 범위 밖 다른 `surge_candidate`
  생산자의 행까지 덮어쓰는 회귀 리스크를 §5 **R-7**로 승격(R-1~R-6과 나란히). plan.md Files-to-Modify와
  acceptance.md 품질 게이트의 기존 "무회귀" 문장에 (R-7) 태그로 3개 문서 간 추적성 부여. v0.2.0에서
  확정된 결정 사항은 불변.

---

## 1. Overview (개요)

### 문제

급등예측 페이퍼 시스템의 `scannable_recall`(surge_evaluation_service.py)이, **사전 선별된 T-1 스캔
유니버스 안에 실제로 있던 종목에 대해서도** 수 주째 0%에 가깝다. 반복된 탐지기 임계 튜닝
(SPEC-AI-073/074/076/078/079)으로도 개선되지 않았다. 2026-07-14 심층 조사 결과, 근본 원인은
**예측 지평 불일치**로 확정되었다.

`evaluate_surge_predictions()`(surge_evaluation_service.py)의 recall 지표는 오직
`signal_type=="surge_candidate"` AND `date(created_at)==T-1(전 영업일)`인 시그널만 집계한다
(`:553-555`). 이 조건을 만족하는 유일한 발생원은 **T-1 15:20 KST 배치 스캔 1회**
(`_run_surge_signal_generate`, scheduler)다. 그러나 실제 +30% 상한가를 만드는 촉매(수주 계약,
M&A, 자사주 소각, 속보성 뉴스)는 압도적으로 **급등 당일(T) 또는 T-1 배치 종료 이후**에 공시/보도된다.

**포렌식 실증 (2026-07-10):** 상한가 종목의 촉매 공시가 T-1 15:20 배치 스캔 이후에 접수됨 —
신테카바이오(226330) 단일판매·공급계약 07-09 16:41 KST, 대성파인텍 07-09 17:40, 드림텍 07-09 15:38.
셋 다 T-1(07-09) 15:20 배치가 이미 끝난 뒤 접수 → 그날 배치는 원천적으로 이들을 볼 수 없었다.

### 이미 존재하나 구조적으로 무력화된 이벤트 구동 경로

이벤트 구동 경로가 이미 있으나 급등에 대해서는 구조적으로 발화 불가다:

`process_disclosure_impact()`(disclosure_impact_scorer.py:355, DART 수집 시 실행)
→ 장중 공시는 `_schedule_reflection_check`로 30분 뒤 `run_reflection_check()`(`:452`) 예약
→ `run_reflection_check`는 오직 `detect_unreflected_gap()`(`:245`)가 True일 때만
   `_create_disclosure_signal()`(`:483`) 발화.

그러나 `detect_unreflected_gap()`는 주가가 공시 충격의 **80% 이상 반영되면 False**를 반환한다
(`:253-255`, `reflected_pct >= impact_score * 0.8`). 상한가 급등은 촉매를 **거의 즉시** 반영하므로
이 게이트는 진짜 급등에 대해 **항상 False** — 이 경로는 "느린 저반응(under-reaction)"을 잡도록
설계된 것이지 빠른 급등을 잡는 경로가 아니다. 게다가 발화하더라도 `signal_type="disclosure_impact"`
(`:501`)를 부여하므로 `evaluate_surge_predictions()`의 recall 집계에 **전혀 포함되지 않는** 별도 사일로다.

### 목표

기존 이벤트 구동 공시 경로를 **repurpose**하여, **고확신 당일 촉매가 DART 수집 시점에 급등-집계
시그널을 즉시 발화**하도록 한다 — 다음 T-1 배치 스캔을 기다리지 않음으로써 **지배적 TIMING 갭을
닫는다**. 동시에, 발화 범위를 소수의 기계 검증 가능한 고확신 이벤트 클래스로 좁혀 오탐 리스크를 통제한다.

### 운영 안전 (검증됨)

실매매(매수 실행)는 **시스템 전반 비활성** — SPEC-AI-043이 scheduler의
`_run_surge_execute_buys`/`_run_surge_check_exits`/`_run_force_max_holding_exit` 3개 잡을 주석
처리(`# DISABLED by SPEC-AI-043`)했다. 본 시스템 전체가 페이퍼(모의) 트레이딩이며 실제 자금
리스크는 없다. 따라서 본 SPEC은 **예측/recall 추적에만** 영향을 주고 실매매 리스크는 없다.
(단, 이벤트 구동 경로의 `_create_disclosure_signal`은 여전히 `execute_signal_trade`를 직접
호출하므로 — `:519-520` — 신규 즉시 발화 경로는 이 페이퍼 트레이딩 배선을 **타지 않도록** 명시
분리해야 한다. REQ-AI080-005 참조.)

---

## 2. Environment & Assumptions (환경 및 가정)

- Backend: Python 3.12+, FastAPI, SQLAlchemy 2.0, PostgreSQL 16(프로덕션) / SQLite(테스트).
  배포: OCI VM 베어메탈 + systemd(`newshive`). 운영 모드: **예측 기록 전용(실매매 비활성)**.

코드 검증 완료(2026-07-14, read-only):

- [E-1] recall 지표 필터 확정: `evaluate_surge_predictions()`의 predicted_set은 **3개 조건 AND**로
  구성된다 — `FundSignal.signal_type == "surge_candidate"`(surge_evaluation_service.py:553) AND
  `FundSignal.surge_metadata.isnot(None)`(**:554**) AND
  `sqlfunc.date(FundSignal.created_at) == prev_business_day`(:555). `signal_type="disclosure_impact"` 등
  다른 값은 recall에 **미집계**. **[v0.2.0 강조] 세 번째가 아니라 두 번째 조건 `surge_metadata.isnot(None)`가
  침묵 실패 위험이다: 즉시 발화 시그널이 signal_type·날짜를 모두 맞춰도 `surge_metadata`를 채우지 않으면
  이 조건에서 조용히 배제된다** → DoD/인수 기준으로 승격(REQ-004, acceptance.md). 추가로 predicted_set
  구성 시 `_is_near_limit_up_carry_signal(surge_metadata)`(:482-503, :570-574)가 True인 행은 배제되므로
  (SPEC-AI-075), 즉시 발화 마커는 near_limit_up_carry로 오판되지 않는 형태여야 한다.
- [E-2] 이벤트 구동 진입점: `process_disclosure_impact()`(disclosure_impact_scorer.py:355)는
  DART 수집 시 impact_score 계산·기준가 스냅샷 후 —
  - **장중(09:00~15:30)**: `_schedule_reflection_check`로 30분 뒤 반영도 측정 예약(`:391-393`)
  - **장마감 후(15:30~18:00) AND impact_score>=25**: `_create_gap_pullback_signal`
    (signal_type=gap_pullback_candidate, `:398-400` + docstring `:362`)
  두 경로 모두 **`signal_type="surge_candidate"`를 발화하지 않는다** → recall 미집계.
- [E-3] 반영-갭 게이트: `detect_unreflected_gap()`(`:245`)는 `reflected_pct >= impact_score*0.8`이면
  False(`:253-255`). 급등은 즉시 반영 → 이 게이트는 진짜 급등에 항상 False.
- [E-4] 미반영 시그널: `_create_disclosure_signal()`(`:483`)은 `signal_type="disclosure_impact"`
  (`:501`) 부여 + `execute_signal_trade` 직접 호출(`:519-520`, 페이퍼 트레이딩 연동).
- [E-5] 고확신 이벤트 클래스는 이미 기계 인식 가능한 형태로 존재:
  `_IMMEDIATE_EVENT_PATTERNS`(surge_detector.py:1325-1342) — 자기주식소각(0.90), 주식소각결정(0.90),
  보통주식소각(0.88), 단일판매ㆍ공급계약체결(0.82), 수주계약체결(0.78), 흡수합병결정(0.82),
  흡수합병(0.80), 합병결정(0.78), 자기주식취득결정(0.70). 루틴 거버넌스 공시는
  `_ROUTINE_GOVERNANCE_KEYWORDS`로 이미 5점 캡 처리(disclosure_impact_scorer.py:175-179).
- [E-6] 계약금액 추출 헬퍼 존재: `extract_contract_amount(report_name, ai_summary)`
  (disclosure_impact_scorer.py:135) — 조/억/백만원 파싱 → 억원 단위 int 반환.
- [E-7] **[정정 — 제안 메커니즘 #2 재검토] `impact_score`는 이미 계약금액/시총 스케일이다.**
  `score_disclosure_impact()`(`:163`)의 계약 공시 경로(`:181-190`)는 이미
  `ratio = contract_amt / market_cap_億` → `score = min(ratio*500, 100)` (+tier 배수)로
  **계약금액/시총 비율 기반** impact_score(0~100)를 만든다. 제안이 지목한 "flat 0.82 상수"는
  **다른 스코어링 시스템** — surge_detector의 `immediate_disclosure_score`(0~1, T-1 배치 앙상블
  bypass 전용)에만 존재한다. 즉 이벤트 구동 경로는 **이미 잘 스케일된 점수를 보유**하므로, 즉시
  발화 게이팅은 `impact_score`를 그대로 재사용하면 되고 **surge_detector의 flat 0.82 교체는
  지배적 TIMING 갭 해소에 불필요**하다(범위 축소 — §4 [X-4], §5 [R-4]).
- [E-8] **[단순화 발견] 지배적 미탐 표본은 "T-1 종가 이후 공시"다.** 포렌식 3건(신테카바이오/
  대성파인텍/드림텍) 모두 T-1 15:20 배치 종료 후 접수 → T에 급등. 이 종목들에 대해 **수집 시점
  (T-1 저녁)에 즉시 surge_candidate를 발화하면 `created_at`이 T-1로 기록**되어 기존 recall 버킷
  (`date(created_at)==T-1`)에 **자연 편입**된다. 즉 지배적 갭은 별도 지표 신설 없이도 닫힌다.
  진짜 별도 지평 처리가 필요한 것은 **급등 당일(T) 장중 접수 공시**의 소수 케이스뿐이다
  (REQ-AI080-004 참조). **[v0.2.0 정정] 이 "자연 편입"은 즉시 발화 *시점*에만 성립한다 — [E-9]가
  밝히듯 익일(T) 배치 재탐지 업서트/캐리오버가 `created_at`을 T로 덮어써 편입을 무효화할 수 있으므로,
  REQ-004 T-1 귀속 불변식으로 보호하지 않으면 지배적 갭이 다시 열린다.**
- [E-9] **[신규 구조 리스크 — 독립 코드 리뷰 확인] T-1 배치 스캔 자신이 기존 surge_candidate 시그널의
  `created_at`을 무조건 덮어쓴다 → 즉시 발화 시그널의 T-1 귀속 파괴 위험.**
  - **경로 1 (재탐지 업서트):** T-1 배치 스캔의 후보 영속화부(`gather_surge_candidates()` 산출 소비부,
    fund_manager.py)는 `stock_id` + `signal_type=="surge_candidate"` + `created_at >= five_days_ago`로
    기존 행을 조회(fund_manager.py:1436-1445)해, 있으면 신규 INSERT 대신 UPDATE하고 **`existing.created_at
    = datetime.now(timezone.utc)`로 무조건 덮어쓴다**(`:1464`). `five_days_ago`는 주석("5영업일")과 달리
    실제로는 `timedelta(days=5)` = **5역일**(fund_manager.py:1352). 같은 UPDATE는
    `existing.surge_metadata = metadata_json`(`:1449`)으로 **surge_metadata까지 배치 값으로 교체**한다
    (즉시 발화 마커가 surge_metadata에 있으면 소실될 수 있음).
  - **경로 2 (별개 코드 경로 — SPEC-AI-039 캐리오버):** fund_manager.py:1542-1597의 캐리오버 루프는
    48h 윈도우(`prev_window_start = today_start - 48h`, `:1522`)의 surge_candidate를 5% decay 후 재사용하며
    `prev.created_at = datetime.now(timezone.utc)`로 **역시 덮어쓴다**(`:1597`). 경로 1과 다른 경로이며
    (배치에 재탐지되지 *않은* 종목까지 포괄), decayed>=0.50·confidence>=0.28을 통과하는 즉시 발화
    시그널을 별도로 위협한다 → 경로 1과 별개 처리 필요.
  - 두 경로 모두 `originally_created_at`은 보존하나(`:1462-1463`, `:1595-1596`),
    `evaluate_surge_predictions`는 `date(created_at)`으로만 버킷팅([E-1]) — `originally_created_at`을
    보지 않으므로 **보존만으로는 recall 귀속이 구제되지 않는다.**
  - **구체 실패 시나리오(타이밍 확정):** 신테카바이오(226330) 즉시 발화 시그널이 2026-07-09 16:41 KST
    생성(created_at=07-09). 익일 2026-07-10에 같은 종목이 (계속되는 모멘텀·뉴스로) 배치 앙상블에
    재탐지되면 — 배치 스캔은 **10:00·15:20 KST**(scheduler.py:2402/2386)에 실행되고, 평가
    `_run_surge_verify_predictions`(→ `evaluate_surge_predictions`)는 **18:30 KST**(scheduler.py:809/838)에
    실행된다. 즉 **배치가 평가보다 먼저** 돌아 07-09 행의 created_at을 07-10으로 덮어쓴 뒤 18:30 평가가
    돌면 `date(created_at)==07-09` 버킷에서 그 종목이 사라져 — REQ-AI080-004 Scenario 1이 의존하는 바로
    그 메커니즘이 **조용히 무력화**된다. 재탐지가 안 되면 경로 2 캐리오버가 같은 덮어쓰기를 한다.
    (이 종목의 재탐지는 희귀 엣지가 아니라 흔한 패턴 — 급등·뉴스가 계속되는 종목을 탐지기가 다시 잡음.)
  - **정직한 범위 한정(과장 방지):** created_at이 그대로 보존되는 유일한 경우는 종목이 T에 **재탐지되지도
    않고**(경로 1 미해당) **캐리오버 임계(decayed>=0.50)도 못 넘는** 경우다 — 이는 사실상 "T에 실제로
    급등/모멘텀 유지에 실패한" 케이스이므로, 덮어쓰기는 **우리가 잡고자 하는 진짜 양성(true positive)에
    대해 정확히 귀속을 파괴**한다. 따라서 본 리스크는 축소가 아니라 오히려 핵심 케이스에 집중되는 High
    리스크로 확인됨. → REQ-004/006 개정, R-6, plan.md DP-1 권장 변경의 근거.

가정:

- [A-1] 고확신 이벤트 클래스 화이트리스트를 `_IMMEDIATE_EVENT_PATTERNS`/`_CONTRACT_KEYWORDS`/
  `_MNA_KEYWORDS` 계열의 기존 목록으로 한정하면 오탐 표면이 작게 유지된다(A-1은 R-1로 관찰).
- [A-2] 현재 predicted_count는 매우 낮음(일 3~9건)이라 즉시 발화 추가분의 절대량 여유가 있다.
  단 이는 **모니터링 대상 리스크**이지 안전 가정이 아니다(R-1).
- [A-3] `FundSignal.created_at`의 타임존/`date()` 비교 의미(UTC vs KST)는 Run 단계에서
  검증 필요(§7 열린 질문 OQ-1). 특히 00:00~09:00 KST 접수 공시의 UTC 날짜 경계 교차 가능성.

---

## 3. Requirements (EARS)

### REQ-AI080-001 (Event-Driven, P0) — 고확신 당일 촉매의 즉시 발화

**WHEN** `process_disclosure_impact()`가 어떤 공시를 수집하고, 그 공시가 (a) 기계 인식 가능한
고확신 이벤트 클래스에 속하며(REQ-003), (b) `impact_score`가 발화 임계(신규 config 키, 예:
`immediate_surge_min_impact`) 이상이면, the system **SHALL** DART 수집 시점에 급등-집계 시그널을
**즉시** 발화하고, 다음 T-1 배치 스캔이나 30분 `run_reflection_check`/`detect_unreflected_gap`
게이트를 **기다리지 않아야** 한다.

- 근거: `detect_unreflected_gap` 게이트는 급등에 구조적으로 항상 False(§2 [E-3])이므로, 고확신
  이벤트 클래스에 한해 이 게이트를 **우회**한다.

### REQ-AI080-002 (State-Driven, P0) — 확신도 게이팅은 계약금액/시총 스케일된 impact_score 기준

**WHILE** 즉시 발화 여부를 판정하는 동안, the system **SHALL** 기존 `score_disclosure_impact()`의
`impact_score`(계약 공시는 이미 계약금액/시총 비율로 스케일됨, disclosure_impact_scorer.py:181-190)를
게이팅 기준으로 사용하고, surge_detector의 flat `immediate_disclosure_score`(0.82) 상수를
**재도입하거나 사용하지 않아야** SHALL NOT 한다.

- 근거(§2 [E-7]): 이벤트 구동 경로는 이미 잘 스케일된 점수를 보유. 큰 계약이 소형주에 나오면
  ratio가 커져 임계를 넘고, 보일러플레이트/소액 계약은 넘지 못한다(오탐 통제). 제안 메커니즘 #2의
  의도는 `impact_score` 재사용으로 **이미 충족**된다.

### REQ-AI080-003 (Ubiquitous, P0) — 고확신 이벤트 클래스로 범위 한정 (오탐 통제)

즉시 발화 경로는 **소수의 기계 검증 가능한 고확신 이벤트 클래스에만** 한정 SHALL 한다:
자사주 소각(자기주식소각/주식소각결정/보통주식소각), 단일판매·공급계약체결/수주계약체결,
흡수합병/합병결정 등 — 기존 `_IMMEDIATE_EVENT_PATTERNS` 및 계약/M&A 키워드 계열.

- the system **SHALL NOT** 일반·범용 공시 유형(지분공시, 정기공시, 루틴 거버넌스 등)에서 즉시
  발화해서는 안 된다. 루틴 거버넌스는 이미 5점 캡(disclosure_impact_scorer.py:175-179)으로 자연 배제.

### REQ-AI080-004 (Event-Driven, P0) — recall 지표 편입 + 지평 분리

즉시 발화 시그널은 다음 규칙으로 recall 지표에 편입 SHALL 한다:

- **T-1 종가 이후(배치 스캔 윈도우 종료 후) 접수분** — 즉 익일(T) 급등을 예측하는 케이스:
  `signal_type="surge_candidate"`로 발화하고 `surge_metadata`에 same-day-event-driven 근거를
  기록하여, `created_at`(T-1)이 기존 T-1→T `predicted_set` 버킷(surge_evaluation_service.py:547-559)에
  편입되어 `scannable_recall`에 집계되도록 SHALL 한다.
- **급등 당일(T) 장중 접수분** — 지평이 T→T(당일)로 표준 T-1→T 규칙과 다름:
  the system **SHALL NOT** 이들을 T-1→T 버킷에 혼입해서는 안 된다(SPEC-AI-075의 near_limit_up_carry
  지평 태깅 배제 패턴 재사용). 대신 **별도의 명확히 라벨링된 same-day 이벤트 서브지표**로 추적한다.
- **[개정 — [E-9] 반영] T-1 귀속 불변식(핵심):** 첫째 규칙으로 발화한 T-1 즉시 발화 시그널은,
  같은 종목이 이후 T-1 배치 스캔의 재탐지 업서트(fund_manager.py:1436-1464) 또는 SPEC-AI-039
  캐리오버(fund_manager.py:1542-1597)에 의해 5역일 윈도우 내에서 다시 처리되더라도, **그 `created_at`(T-1)
  기준 recall 귀속을 잃지 않아야** SHALL 한다. 구체적으로 the system **SHALL NOT** 즉시 발화 시그널의
  `created_at`을 배치·캐리오버가 T로 덮어써 `date(created_at)==T-1` 버킷에서 이탈시키는 것을 허용해서는 안
  되며, the system **SHALL NOT** 즉시 발화 시그널의 식별용 surge_metadata 마커가 배치 업서트의
  metadata 교체(`:1449`)에 의해 소실되도록 두어서는 안 된다. 구현 수단(마커 인지형 덮어쓰기 스킵 vs
  안정적 원본 시각 기반 평가 버킷팅)은 Run 단계 DP-1에서 확정한다.

- 근거(§2 [E-8], [E-9]): 지배적 미탐 표본은 T-1 종가 이후 접수이므로 첫 규칙만으로도 지배적 갭이 닫힌다.
  "내일을 예측"과 "오늘의 촉매를 잡음"을 단일 `scannable_recall`로 뭉개는 것 자체가 튜닝
  무효화의 일부였다는 조사 소견을 반영해, 두 지평을 **분리**한다. 단 [E-9]가 밝힌 배치·캐리오버의
  `created_at` 덮어쓰기가 이 "자연 편입"을 무효화하므로, 위 T-1 귀속 불변식이 없으면 **첫 규칙조차 성립하지
  않는다** — 이번 개정으로 첫 규칙을 "발화 시점 편입"에서 "**발화 후에도 유지되는 편입**"으로 강화한다.

### REQ-AI080-005 (Unwanted, P0) — 예측 기록 전용, 페이퍼 트레이딩 배선 금지

**IF** 즉시 발화 경로가 시그널을 생성하면, **THEN** the system **SHALL NOT** 그 시그널에 대해
`execute_signal_trade`(페이퍼 트레이딩 실행, disclosure_impact_scorer.py:519-520)를 호출해서는
안 된다 — 예측/recall 추적 전용이며 SPEC-AI-043 예측 기록 모드와 일관한다.

- 근거: 기존 `_create_disclosure_signal`은 페이퍼 트레이딩을 직접 호출한다. 신규 경로가 이를
  재사용하거나 답습하면 SPEC-AI-043 의미가 훼손되고 오탐 페이퍼 매수가 늘어난다.

### REQ-AI080-006 (Unwanted Behavior, P1 — 귀속 보호 부분은 P0) — 기존 네이티브 업서트/캐리오버와의 통합 (중복·귀속 훼손 방지)

**[개정 — [E-9] 반영]** 코드베이스에는 이미 `signal_type=="surge_candidate"`에 대한 네이티브
디듀프/업서트가 존재한다: (a) 5역일 재탐지 업서트(fund_manager.py:1436-1464)와 (b) SPEC-AI-039
48h 캐리오버(fund_manager.py:1542-1597). 이들은 **중복 INSERT를 이미 방지**하지만 동시에 매칭되는
행의 `created_at`(과 업서트의 경우 `surge_metadata`)을 **무조건 덮어쓴다**. 따라서 본 REQ는 "새 디듀프
계층 신설"이 아니라 "**기존 메커니즘 인지·통합**"으로 재정의한다:

- the system **SHALL** 즉시 발화 경로를 이 **기존 메커니즘을 명시적으로 인지**하여 설계해야 하며,
  별도의 평행 디듀프 계층을 새로 만들기보다 기존 업서트/캐리오버와 **통합**하는 것을 우선 SHALL 한다.
- the system **SHALL NOT** 동일 (종목, 영업일)에 대해 즉시 발화 + 배치가 **중복 surge_candidate 행**을
  만들어 recall 이중집계를 유발해서는 안 된다(기존 업서트가 이미 중복 INSERT를 막으므로, 신규 경로는
  같은 조회 키에 정합해야 한다).
- [P0, REQ-004 불변식과 연동] the system **SHALL** 기존 업서트/캐리오버가 즉시 발화 시그널의
  T-1 `created_at`과 식별 마커를 **훼손하지 않도록 보호**해야 한다.

- 설계 고려(DP-1): 즉시 발화의 가치는 "배치가 볼 수 없었던 촉매를 잡는 것"이다. 배치 윈도우(10:00·15:20 KST)
  **이전** 접수 공시는 배치가 이미 볼 수 있어 즉시 발화가 중복일 수 있다. Run 단계 선택지:
  (i) **마커 인지형 스킵** — 즉시 발화 행을 surge_metadata 마커로 식별해 두 덮어쓰기 사이트가 created_at·
  마커를 보존하도록 기존 메커니즘에 통합(**권장** — 기존 메커니즘 재사용, blast radius 최소, REQ-004
  불변식 직접 충족), (ii) 즉시 발화를 배치 윈도우 이후 접수분으로 한정(동시 이중발화는 줄이나 **익일
  재탐지·캐리오버 덮어쓰기는 못 막아 단독으로는 불충분** — (i)의 보완재), (iii) 평가 버킷팅을
  `coalesce(originally_created_at, created_at)`로 이동(전 캐리오버 시그널의 recall 의미 변경 → 회귀 위험
  큼). plan.md DP-1에서 확정, 권장 (i).

### REQ-AI080-007 (Optional, P2) — 관측성 (nice-to-have)

**WHERE** 활성화 이후 신호량/precision 관측이 필요한 경우, the system은 즉시 발화 시그널의 수·구성
(이벤트 클래스별, T-1편입분 vs 당일 서브지표분)을 **구분하는 집계 로그 또는 서브지표**를 방출 MAY 한다.

- 신규 테이블/컬럼/마이그레이션 금지. 종목별 INFO 스팸 금지. 스캔/일 단위 집계로 한정.
- 본 REQ는 P2 optional이며 001~006의 blocker가 아니다.

---

## 4. Exclusions (What NOT to Build) [HARD]

본 SPEC은 다음을 **명시적으로 범위에서 제외**한다:

- [X-1] **매매/포트폴리오 로직 변경 금지.** SPEC-AI-043 예측 기록 모드 유지. 즉시 발화 경로는
  페이퍼 트레이딩(`execute_signal_trade`)을 타지 않는다(REQ-005). 실매매 재활성화는 범위 밖.
- [X-2] **탐지기 7종 본체 로직 변경 금지.** volume_breakout/theme_news_cluster/momentum_continuation
  등 T-1 배치 탐지기의 발화 로직은 불변. 본 SPEC은 이벤트 구동(수집 시점) 경로만 추가/전용화한다.
- [X-3] **`detect_unreflected_gap`의 저반응(under-reaction) 용도 제거 금지.** 이 게이트는 느린
  저반응 탐지 본연의 용도로 유지된다. 본 SPEC은 고확신 이벤트 클래스에 한해 이 게이트를 **우회**할
  뿐 게이트 자체를 삭제/변경하지 않는다(다른 공시 유형의 기존 반영-갭 시그널은 그대로 동작).
- [X-4] **[정정] surge_detector의 flat `immediate_disclosure_score`(0.82) 교체는 본 SPEC 범위 밖.**
  §2 [E-7]대로 이벤트 구동 경로는 이미 계약금액/시총 스케일 impact_score를 쓰므로 지배적 TIMING
  갭 해소에 불필요. T-1 배치 앙상블의 SCORING 갭(0.82 < 0.85 bypass, 가중치 0.14×0.82 < 0.38
  min_score)은 **분리 가능한 별개 후속 사안**으로 유예(§8 후속 후보).
- [X-5] **텍스트-무관 순수 수급 급등(무재료 급등) 탐지는 범위 밖.**
  [[project_systemic_prediction_gap_2026_07_13]]의 미탐 원인 중 "공시/뉴스/전일모멘텀 무재료" 케이스는
  본 SPEC이 공시 기반 촉매를 다루므로 대상 아님(오탐 위험 커 별도 관찰/SPEC).
- [X-6] **SPEC-AI-079(volume_breakout relative_threshold)와 중복·충돌 없음.** 그 SPEC은 거래량 구동
  소수 미탐을 다루며 본 지평 불일치와 직교/보완. 그 로직 변경 없음.
- [X-7] **과거 데이터 소급 재계산/백필 금지.** 이후 수집·평가 실행에만 전진 적용(SPEC-AI-071 무백필
  관례 계승).
- [X-8] **near_limit_up_carry의 T→T 평가 경로 구현은 범위 밖**(SPEC-AI-075가 유예한 별도 미래 SPEC).
  본 SPEC의 same-day 서브지표(REQ-004 둘째 규칙)는 즉시 발화 촉매 전용이며 near_limit_up_carry
  성능 측정과 별개다.
- [X-9] **신규 테이블/스키마 마이그레이션 금지(원칙).** 재사용 우선 — `FundSignal.signal_type` +
  `surge_metadata`(SPEC-AI-075 태깅 패턴) 활용. same-day 서브지표는 평가 함수 내 파생 계산으로
  구현하고, 부득이한 스키마 확장이 필요하면 Run 단계에서 사용자 승인 후 별도 결정(DP-2).

---

## 5. Risks (리스크)

- [R-1] **오탐/precision 리스크 (핵심).** 즉시 발화로 더 많은 공시 유형에 발화 표면이 열리면
  surge_candidate 신호 수가 늘어 precision이 하락할 수 있다. 완화: (i) 발화를 소수 고확신 이벤트
  클래스로 한정(REQ-003), (ii) 계약금액/시총 스케일 impact_score 임계 게이팅(REQ-002), (iii) 활성화
  후 며칠간 신호량/precision을 관측(REQ-007). **자금 리스크는 없음**(실매매 비활성, REQ-005). 단
  현재 predicted_count가 낮다(일 3~9건)는 사실은 **여유의 근거이지 안전 보장이 아니다** — 감시 대상.
- [R-2] **이중집계 리스크.** 배치 윈도우 이전 접수 공시가 즉시 발화 + 배치 스캔 양쪽에서 잡혀
  recall이 부풀 수 있다. 완화: REQ-006 디듀프(또는 배치 윈도우 이후 한정).
- [R-3] **지평 오혼입 리스크.** 당일(T) 장중 접수 공시를 T-1→T 버킷에 잘못 넣으면 SPEC-AI-075가
  고쳤던 것과 동일한 지표 오염이 재발. 완화: REQ-004 둘째 규칙(당일 접수분은 별도 서브지표) 준수.
- [R-4] **범위 오인 리스크.** 제안 메커니즘 #2(flat 0.82 교체)를 그대로 구현하면 지배적 TIMING 갭과
  무관한 T-1 배치 스코어링을 건드려 범위가 커지고 회귀 위험이 는다. 완화: [X-4]로 명시 제외.
- [R-5] **타임존 경계 리스크.** `created_at`가 UTC 저장이고 recall이 `date()`를 KST 영업일과
  비교한다면, 심야(00:00~09:00 KST) 접수 공시가 UTC 날짜 경계를 넘어 잘못된 버킷에 편입될 수 있음.
  Run 단계 검증 필요(OQ-1).
- [R-6] **[핵심 신규 — [E-9]] created_at 덮어쓰기에 의한 T-1 귀속 소실.** 즉시 발화 시그널(created_at=T-1)이
  익일(T) 배치 재탐지 업서트(fund_manager.py:1464) 또는 SPEC-AI-039 캐리오버(fund_manager.py:1597)에
  의해 created_at이 T로 덮어써지면, 18:30 평가 시 `date(created_at)==T-1` 버킷에서 이탈해 recall 귀속이
  조용히 사라진다. 배치(10:00·15:20)가 평가(18:30)보다 먼저 실행되므로 **안정적으로 재현**된다. 게다가
  덮어쓰기는 T에 실제 급등한(재탐지·캐리오버되는) **진짜 양성에 집중**되어 리스크가 크다(축소 아님).
  완화: REQ-004 T-1 귀속 불변식 + REQ-006 기존 업서트/캐리오버 마커 인지형 통합(plan.md DP-1 (i)).
  R-2(이중집계)와 구분: R-2는 "중복 행 생성", R-6은 "기존 행의 created_at 훼손"으로 원인·완화가 다르다.
- [R-7] **[신규 — 공유 고 fan_in 영속 코드 회귀 리스크] 마커 인지형 스킵 분기를 넣는
  `fund_manager.py:1436-1464`(재탐지 업서트)/`:1542-1597`(SPEC-AI-039 캐리오버)는 본 SPEC 범위 밖의
  다른 `surge_candidate` 생산자 시그널까지 함께 처리하는 공유 경로다 — 여기에 결함이 들어가면 즉시 발화
  시그널뿐 아니라 그 생산자들의 recall 버킷팅을 조용히 회귀시킬 수 있다.** 두 덮어쓰기 사이트는 생산자를
  구분하지 않는 공유 조회 키로 대상 행을 선택한다 — 업서트는 `stock_id`+`signal_type=="surge_candidate"`
  (:1437-1445), 캐리오버는 `signal_type=="surge_candidate"`+48h 윈도우(:1531-1540). 따라서 아래 생산자들이
  **각자 직접**(surge_detector.py에서 `db.add`+`commit`) 기록한 surge_candidate 행도 — fund_manager 업서트를
  호출하지 않더라도 — 이 두 사이트의 덮어쓰기 대상이 된다(코드 검증 완료, 2026-07-14):
  핵심 T-1 앙상블 배치(fund_manager.py:1483), near_limit_up_carry(SPEC-AI-072/075, surge_detector.py:2832),
  임원 자사주 매수(SPEC-AI-024, :2984), 테마 그룹 캐리(SPEC-AI-025, :3118), 포럼 언급 급증(SPEC-AI-026, :3272),
  그룹 캐스케이드(SPEC-AI-027, :3528). (검증 소견: `detect_volume_anomaly_dormant_stocks`는
  `signal_type="volume_anomaly"`(:2589)를 발신하므로 이 공유 surge_candidate 경로 대상이 아니어서 목록에서 제외.)
  완화(plan.md의 기존 제약을 인용): (i) 마커 인지형 스킵은 **즉시 발화 마커가 있는 행에서만** 트리거되며,
  (ii) 마커 미검출(=위 모든 기존 생산자) 행에 대해서는 **비트 단위로 동일한 거동**이 요구되고,
  (iii) 회귀 테스트는 신규 즉시 발화 경로뿐 아니라 위에 열거한 다른 생산자 행에 대한 업서트·캐리오버
  무회귀도 함께 검증해야 한다. R-6과 구분: R-6은 "즉시 발화 시그널 **자신**의 T-1 귀속 소실", R-7은
  "이 공유 코드 변경이 **다른 생산자 행**에 미치는 부수 회귀"로 영향 대상이 다르다.

---

## 6. Related SPECs (관련 SPEC)

- **SPEC-AI-004 (선행, 이벤트 구동 공시 인프라)**: `disclosure_impact_scorer.py`,
  `process_disclosure_impact`/`run_reflection_check`/`detect_unreflected_gap`,
  `score_disclosure_impact`, migration 036 소유. 본 SPEC은 이 경로를 **repurpose**한다.
- **SPEC-AI-075 (지평 태깅 패턴 재사용)**: near_limit_up_carry를 `surge_metadata` 기반으로 T-1→T
  버킷에서 배제한 패턴을 REQ-004(당일 접수분 분리)에 그대로 재사용.
- **SPEC-AI-043 (예측 기록 모드) — 유지**: 실매매 3개 잡 비활성. REQ-005가 이 의미를 계승.
- **SPEC-AI-018 (즉각 공시 bypass, `immediate_disclosure_bypass_threshold=0.85`) — 불변**:
  T-1 배치 앙상블의 flat immediate_disclosure_score bypass 경로. 본 SPEC은 이를 건드리지 않음([X-4]).
- **SPEC-AI-041/068 (급등예측 평가·scannable_recall/coverage) — 지표 확장 대상**:
  `evaluate_surge_predictions` 소유. REQ-004의 편입/서브지표 추가는 이 함수에서 이루어짐.
- **SPEC-AI-079 (volume_breakout relative_threshold) — 직교/보완**: 거래량 구동 소수 미탐.
  본 지평 불일치와 독립(§4 [X-6]).

---

## 7. Open Questions (열린 질문 — Run 단계 확정)

- [OQ-1] **`FundSignal.created_at` 타임존.** UTC 저장인지, `evaluate_surge_predictions`의
  `sqlfunc.date(created_at)==prev_business_day` 비교가 KST 영업일과 정합하는지 확인. 불일치 시
  심야 접수 공시의 버킷 편입 보정 방법(R-5)을 결정.
- [OQ-2] **"배치 윈도우 종료" 판정 방식.** 즉시 발화의 T-1편입/당일-서브지표 분기(REQ-004)를 접수
  시각(rcept 시각) 기준으로 판정할지, 급등 발생일(T) 대비 상대일로 판정할지 확정. 스케줄상
  15:20 KST 배치 시각이 기준 후보.
- [OQ-3] **기존 업서트/캐리오버 통합 방식(DP-1, v0.2.0 개정).** [E-9] 발견으로 "신규 디듀프 vs 윈도우
  한정" 프레이밍은 무효화됨 — 네이티브 5역일 업서트(fund_manager.py:1436-1464)가 이미 중복 INSERT를 막고
  있고, 진짜 문제는 그 업서트·캐리오버(:1542-1597)가 즉시 발화 행의 created_at·마커를 덮어쓰는 것이다.
  확정 대상: (i) 마커 인지형 스킵으로 두 덮어쓰기 사이트(fund_manager.py:1464, :1597)를 즉시 발화 행에
  한해 보존하도록 통합(권장), (ii) 윈도우 한정(보완재, 단독 불충분), (iii) 평가 버킷팅을
  originally_created_at 기반으로 이동(회귀 위험 큼). 권장: (i).
- [OQ-4] **same-day 서브지표 영속화(DP-2).** REQ-004 둘째 규칙의 당일 서브지표를 평가 함수 내
  파생 계산으로만 둘지, 관측을 위해 `surge_prediction_evaluation`에 라벨 컬럼을 추가할지. 스키마
  확장은 원칙적으로 지양([X-9]), 필요 시 사용자 승인.
- [OQ-5] **surge_metadata 마커 형태(v0.2.0 신규).** 즉시 발화 시그널의 식별 마커를 surge_basis 리스트
  멤버(예: "immediate_disclosure")로 둘지 플랫 키로 둘지 — 단 (a) `surge_metadata`가 non-None이어야 recall에
  포함되고([E-1] `:554`), (b) `_is_near_limit_up_carry_signal`(surge_evaluation_service.py:482-503)에
  near_limit_up_carry로 오판되지 않아야 하며(surge_basis에 near_limit_up_carry 미포함), (c) 배치 업서트·
  캐리오버가 이 마커로 즉시 발화 행을 식별해 created_at·마커를 보존할 수 있어야 한다(DP-1 (i)와 연동).

---

## 8. Follow-up Candidates (후속 후보 — 본 SPEC 범위 밖)

- T-1 배치 앙상블의 SCORING 갭 교정: 계약 공시 flat 0.82 → 계약금액/시총 스케일로 상향하거나
  disclosure_pattern 가중치/`immediate_disclosure_bypass_threshold` 조정([X-4], R-4). 별개 SPEC.
- 텍스트-무관 순수 수급 급등 탐지기 신설([X-5]) — 오탐 위험 커 수일 관찰 후 판단.

---

## Implementation Notes (Level 1)

### 실제 구현 요약 (2026-07-15, commit 66776b6)

#### 핵심 변경사항

**즉시발화 설정 토글** (`surge_config/surge_detection.yaml`, `surge_settings.py`)
- `immediate_surge` 블록 추가, 기본값 `enabled: false`(레거시 완전 불변 보증, Scenario 6)

**즉시발화 헬퍼 및 분기 연결** (`disclosure_impact_scorer.py`)
- `_create_immediate_surge_signal()`: 고확신 이벤트클래스 + impact_score(계약금액/시총 스케일)
  게이팅, `execute_signal_trade` 미호출(예측 기록 전용, REQ-005), 네이티브 키 정합 업서트
- `process_disclosure_impact()`에 즉시발화 분기 연결, 15:20 KST 컷오프로 next_day/same_day
  horizon 태깅(OQ-2 확정: 접수 시각 기준)

**평가 지평 분리** (`surge_evaluation_service.py`)
- `evaluate_surge_predictions()`: T-1 접수분 recall 편입(Scenario 1) + 당일 접수분 서브지표
  분리(Scenario 2, 파생계산 — DP-2는 스키마 확장 없이 채택)

**기존 덮어쓰기 사이트 마커 인지형 스킵** (`fund_manager.py`, v0.2.0 [E-9] 대응)
- 재탐지 업서트(`:1436-1464`)와 SPEC-AI-039 캐리오버(`:1542-1597`) 양쪽에 `_is_immediate_disclosure_signal`
  마커 인지형 스킵 추가 — 즉시발화 시그널의 `created_at`(T-1)·`surge_metadata`가 익일 배치 실행에도
  보존됨(Scenario 7, DP-1 (i) 채택). 마커 미검출 시 두 사이트 거동은 기존과 완전 동일(R-7 무회귀).

**타임존 검증** (OQ-1/EC-3)
- 검증 완료, 코드 보정 불필요로 확정(T8) — created_at은 이미 KST 영업일과 정합.

**테스트**
- 신규 3개 파일: `test_disclosure_impact_scorer_immediate_surge.py`,
  `test_surge_ai080_fund_manager.py`, `test_surge_ai080_timezone_boundary.py`
- 기존 `test_surge_evaluation_service.py` 확장(228줄 추가)
- 백엔드 전체 스위트: **1978 passed, 4 skipped, 3 xpassed, 0 regressions**. ruff clean.
  (mypy는 프로젝트 미설치 환경으로 스킵 — 기존 프로젝트 상태와 동일)

#### 편차 및 선택사항

**REQ-AI080-007 (P2, 선택) — 별도 모듈 없이 충족**
- 관측성 로그/서브지표 집계를 `evaluate_surge_predictions` 내 기존 로그 라인으로 충족.
  별도 관측 모듈 신설은 불필요로 판단(T10).

#### 신규 테이블/마이그레이션

- 없음 (설정 필드 추가만). 과거 데이터 백필 없음(2026-07-15 이후 전진 적용).

#### 배포 상태

- 로컬 검증만 완료(2026-07-15). 프로덕션 배포는 아직 미완료 — main push 후 CI/CD 배포 확인 필요.

---

## MX Tag 대상 (Run 단계 식별)

- `process_disclosure_impact`(disclosure_impact_scorer.py:355) — DART 수집 시 실행되는 고 fan_in
  진입점. 즉시 발화 분기와 페이퍼 트레이딩 미배선 계약(REQ-005)을 `@MX:NOTE`
  (+`@MX:SPEC: SPEC-AI-080`)로 기록.
- `evaluate_surge_predictions`(surge_evaluation_service.py:547-559) — recall 편입/서브지표 분리
  (REQ-004) 지점. SPEC-AI-075 지평-순수성 계약과 정합하는 `@MX:NOTE`. `surge_metadata.isnot(None)`(:554)
  게이트 인접에 즉시 발화 시그널 침묵 배제 주의를 `@MX:NOTE`로 기록.
- **[v0.2.0 신규]** surge_candidate 재탐지 업서트(fund_manager.py:1436-1464) 및 SPEC-AI-039
  캐리오버(fund_manager.py:1542-1597) — 두 `created_at` 무조건 덮어쓰기 사이트(`:1464`, `:1597`)에
  즉시 발화 행 보존 분기를 `@MX:WARN`(+`@MX:REASON`: created_at 무조건 덮어쓰기가 즉시 발화 T-1 귀속을
  파괴할 수 있음 — 배치가 평가보다 먼저 실행됨, +`@MX:SPEC: SPEC-AI-080`)로 표시. recall 귀속 불변식의
  핵심 위험 지대.
