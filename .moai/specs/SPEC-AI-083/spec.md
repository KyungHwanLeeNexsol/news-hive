---
id: SPEC-AI-083
version: 0.2.0
status: completed
created: 2026-07-21
created_at: "2026-07-21"
updated: 2026-08-03
author: Nexsol
priority: High
issue_number: null
lifecycle_level: 1
labels: [surge-detection, intraday-rescan, event-driven, recall, scheduler, backend]
---

# SPEC-AI-083: 장중 고빈도 재스캔 + 이벤트드리븐 즉시발화 활성화 (Intraday High-Frequency Rescan + Event-Driven Immediate Firing)

## HISTORY

- 2026-07-21 (v0.2.0): **방향 B 범위 확정.** Plan annotation 단계에서 사용자가 방향 B를 "공시 즉시발화
  회귀 보호(REQ-AI083-007) + 뉴스 기반 이벤트 재스캔 활성화(REQ-AI083-008,
  `catalyst_conviction.event_rescan_enabled=false→true`)"까지 포함하는 **권장안을 승인**했다. 이로써
  REQ-AI083-008은 "결정 대기(오케스트레이터 확인 필요)"에서 **정식 확정 요구사항(승인됨)**으로
  승격된다. 활성화만으로 당일 추가 커버리지는 보장되나 뉴스 트리거 정밀도는 미검증이라는 잔존
  리스크(§5 [R-3])는 유지한다. 구현은 여전히 미착수(SPEC 문서 확정까지만).
- 2026-07-21 (v0.1.0): 최초 작성 (Plan 단계 — 구현 미포함). 최근 10 거래일 recall≈0%
  (TP=0)의 **종목 무관 아키텍처 근본원인**(이산 저빈도 샘플링)을 코드 근거로 진단 완료한 뒤,
  사용자가 승인한 두 개선 방향을 EARS로 명세한다. **방향 A** = 장중 후보 생성 스캔을
  단일(10:00) → 09:05~BUY_CUTOFF 구간 고빈도 재스캔으로 확장. **방향 B** = 이벤트드리븐 즉시발화
  활성화.
  - **[중대 정정 — 작업 지시 전제 2건이 현행 코드와 불일치, read-only 재검증 확정 2026-07-21]**:
    (정정-1) 작업 지시 전제 #3은 `immediate_surge.enabled=false`(꺼짐)라 했으나, **실제로는 이미
    `true`**다(`surge_detection.yaml:288`, 2026-07-16 배포 commit `66776b6`/`52258d0`, SPEC-AI-080).
    same_day 지평 평가 경로(`_is_same_day_event_horizon_signal`, `surge_evaluation_service.py:506`)도
    **이미 배선 완료**다. → 방향 B의 원래 핵심 행위(플래그 재플립 + same_day 평가 신설)는 **이미
    완료됨**. 본 SPEC은 방향 B를 (i) 그 활성 상태의 **회귀 보호**와, (ii) 아직 꺼져 있는 **뉴스 기반
    이벤트 재스캔**(`catalyst_conviction.event_rescan_enabled=false`, `surge_detection.yaml:262`)의
    활성화로 **재범위화**한다. (정정-2) 작업 지시 전제 #4는 `surge_check_exits` 잡이 "이미 5분
    간격으로 돈다"라 했으나, 그 잡은 **SPEC-AI-043으로 비활성(주석 처리)**되어 있다
    (`scheduler.py:2428-2439`). `minute='*/5'` 인터벌 패턴 자체는 코드에 남아 있어 검증된 APScheduler
    구문이나 **현재 실행 중은 아니다**. → 본 SPEC의 재스캔 잡은 그 패턴을 참고하되 신규 등록한다.
  - 이 정정은 §2 "코드 검증 완료" 및 최종 보고에 명시되었고, 오케스트레이터가 이를 사용자에게 전달해
    Plan annotation 단계에서 방향 B 재범위화(특히 REQ-AI083-008 뉴스 이벤트 재스캔 활성화)의 **확인을
    완료**했다 — 사용자는 REQ-AI083-008 포함(권장안)을 **승인**(2026-07-21). REQ-AI083-008은 이제
    조건부/보류가 아닌 **확정 요구사항**이며 Run 대상에 포함된다.

---

## 1. Overview (개요)

### 문제 — 종목 무관 아키텍처 근본원인: 이산 저빈도 샘플링

최근 ~10 거래일 급등예측 recall이 거의 전부 0%(TP=0)인 것은 특정 탐지기/파라미터 문제가 아니라
**후보를 언제 생성하느냐(샘플링 시점)**의 구조 문제다(expert-debug 코드 근거 확정).

1. **당일 신규 후보 생성 잡이 사실상 1회뿐이다.** 장중 후보 탐지 잡은
   `surge_signal_generate_intraday`(`scheduler.py:2401-2412`, cron 평일 **10:00 KST 단 1회**)뿐이다.
   `BUY_CUTOFF = time(11, 0)`(`surge_trading_service.py:31`)까지 실행 가능 창은 1시간이고,
   10:00~15:20 KST 사이엔 당일 신규 후보 생성 잡이 전무하다.
2. **"장중 재탐지"가 이름뿐이다.** 10:00 `surge_signal_generate_intraday`와 15:20
   `surge_signal_generate`(익일용)는 **완전히 동일한 콜백** `_run_surge_signal_generate`
   (`scheduler.py:2387`/`2402`, 둘 다 `run_surge_signal_generation`을 호출)를 공유한다. 09:00~10:00
   실시간 가격/거래량 델타를 별도로 보는 로직이 없다. **결과:** 장 초반(09:00~10:00)에 이미 실현된
   급등(예: 2026-07-21 09:51 KST 라이브에서 7종목이 이미 +29.87~29.99%)은 10:00 스캔 시점엔 이미 다
   오른 뒤라 구조적으로 못 잡는다.
3. **당일 급등 캐치가 평가로 인정되지 않는다.** 표준 평가는 `date(created_at)==T-1` 버킷을 T 실제
   급등과 비교하는 T-1→T 고정 지평이다(`surge_evaluation_service.py`). 당일(T) 생성 후보를 같은 날
   급등과 비교하려면 same-day 지평 귀속이 필요하다. SPEC-AI-080이 공시 즉시발화용
   `_is_same_day_event_horizon_signal`(`:506`)로 same_day 서브지표를 이미 만들었으나, **장중 재스캔이
   생성하는 일반 후보는 이 same-day 귀속을 받지 못해** 추가해도 recall이 움직이지 않을 위험이 있다.

### 접근 (사용자 승인 2개 방향)

**방향 A — 장중 고빈도 재스캔:** 09:05~BUY_CUTOFF 구간에 당일 후보 생성 스캔을 N분 간격으로 확장해
장 초반 급등을 조기에 포착하고, 그 후보를 same-day 지평으로 귀속시켜 평가에 편입한다.

**방향 B — 이벤트드리븐 즉시발화(재범위화):** 이벤트 소스는 둘이다.
- (B-공시) 공시 도착 → 즉시발화(`immediate_surge`). **이미 활성**(2026-07-16). 본 SPEC은 **회귀
  보호만** 담당(재플립 없음).
- (B-뉴스) 고확신 뉴스 도착 → 이벤트 재스캔(`_maybe_trigger_event_rescan`, `scheduler.py:107-163`).
  **인프라는 구현됨(SPEC-AI-066 REQ-007)이나 플래그 OFF**(`event_rescan_enabled=false`). 이것이
  방향 B의 실질적 "활성화" 대상이다.

### 목표

당일 급등이 실현되는 시간대(주로 09:00~10:30)에 후보 탐지의 **시간 해상도(sampling resolution)를
높여**, 이미 오른 뒤 1회 스캔으로 놓치던 종목을 조기·즉시 포착 가능하게 하고, 그 포착이 평가
지표(recall)에 올바르게 반영되도록 same-day 지평 귀속을 보장한다. 단, 기존 T-1→T 배치·탐지기·매매
로직은 불변으로 유지한다.

---

## 2. Environment & Assumptions (환경 및 가정)

- Backend: Python 3.13+, FastAPI, SQLAlchemy 2.0, PostgreSQL(프로덕션)/SQLite(테스트). APScheduler
  기반 크론/인터벌 잡. 개발 방법론: DDD(ANALYZE-PRESERVE-IMPROVE, `.moai/config/sections/quality.yaml`).
  검증 명령: `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"` (CLAUDE.local.md).
- 운영 모드: **예측 기록 모드**(SPEC-AI-043) — 실매수/포트폴리오 실행 비활성, `surge_trades` 0건.
  본 SPEC의 모든 변경은 예측 기록만 확장한다.

### 코드 검증 완료 (2026-07-21, read-only)

- [E-1] **장중 스캔 잡 = 10:00 단일, 15:20 배치와 동일 콜백.**
  `scheduler.py:2386-2397`(15:20 `id="surge_signal_generate"`)와 `:2401-2412`(10:00
  `id="surge_signal_generate_intraday"`)는 **동일 함수 `_run_surge_signal_generate`**를 잡으로 등록한다.
  두 잡 모두 `max_instances=1, coalesce=True, replace_existing=True`. 콜백 내부
  `run_surge_signal_generation(db)`(`:1189`) 1회 호출뿐.
- [E-2] **BUY_CUTOFF = time(11, 0)**, `MARKET_OPEN <= current_time <= BUY_CUTOFF`(`<=` 포함 비교,
  `surge_trading_service.py:31`/`:137`). 단, 예측 기록 모드라 실제 매수는 비활성이므로 BUY_CUTOFF는
  "신호 실행 가능 창"의 의미만 남고 후보 **기록**을 제한하지 않는다.
- [E-3] **gather 1회 소요 = 최대 20분.** `_gather_surge_candidates()`(`fund_manager.py`)가 감싸는
  `gather_surge_candidates`(종목당 다중 동기 HTTP 순차 루프)의 글로벌 타임아웃이 SPEC-AI-082로
  `_GATHER_TIMEOUT_S: float = 1200`(모듈 상수, `fund_manager.py:60`)으로 상향됐다. 같은 파일이 정상
  실행을 "12~15분"(`:3106` 주석)으로 문서화한다. → **재스캔 간격은 이 소요를 겹치지 않게 산정해야
  한다**(핵심 설계 제약, REQ-AI083-002/003/013).
- [E-4] **[정정-1] `immediate_surge`는 이미 활성.** `surge_detection.yaml:287-291`
  `immediate_surge.enabled: true`(2026-07-16 배포, min_impact=40.0, batch_cutoff 15:20).
  `process_disclosure_impact`(`disclosure_impact_scorer.py:458-468`)가 DART 수집 시점에 고확신 이벤트
  클래스 + `impact_score>=40` 공시를 30분 반영-갭 게이트 없이 `surge_candidate`로 즉시 발화한다.
  same_day/next_day 지평 분류(`_classify_disclosure_horizon` `:519`)와 평가측 배제/서브지표 처리
  (`_is_same_day_event_horizon_signal` `surge_evaluation_service.py:506-524`)도 **이미 배선 완료**.
  → 방향 B의 공시 절반은 완료 상태이며, 본 SPEC은 회귀 보호만 한다(REQ-AI083-007).
- [E-5] **뉴스 기반 이벤트 재스캔 인프라는 구현됨, 플래그만 OFF.** `_maybe_trigger_event_rescan`
  (`scheduler.py:107-163`)이 `keyword_matching` 완료 훅(`:220-223`)에서 호출되며,
  `catalyst.event_rescan_enabled`(현재 `false`, `surge_detection.yaml:262`) 스위치 + 종목당 쿨다운
  (`event_rescan_cooldown_minutes=30`) + 일일 상한(`max_daily_event_triggers=20`) 가드를 이미 갖췄다.
  → 방향 B의 뉴스 절반 = 이 플래그의 활성화(REQ-AI083-008).
- [E-6] **[정정-2] `surge_check_exits` 5분 잡은 비활성.** `_run_surge_check_exits`(`scheduler.py:1304`)는
  존재하나 그 잡 등록은 **SPEC-AI-043으로 주석 처리**됐다(`:2428-2439`, `minute='*/5'`). 인터벌 패턴은
  검증된 APScheduler 구문이나 현재 실행되지 않는다. → 본 SPEC의 재스캔 잡은 이 패턴을 참고하되
  신규 등록하며, 예측 기록 모드와 정합하게 매수/청산 잡은 건드리지 않는다.
- [E-7] **DART 크롤 주기 = 30분(인터벌).** `DART_CRAWL_INTERVAL_MINUTES: int = 30`(`config.py:57`),
  잡은 인터벌형(`scheduler.py:2028-2035`, 시작 시 즉시 실행). 따라서 공시 즉시발화는 공시 접수 후
  최대 ~30분 내에 발화한다(예: 09:30 공시 → ~10:00 발화). 이 주기 변경은 뉴스/브리핑 등 타 시스템에
  영향이 크므로 본 SPEC 범위 밖(§4 [X-5], §7 [OQ-3]).

### 가정

- [A-1] 예측 기록 모드(SPEC-AI-043)가 유지되므로 BUY_CUTOFF는 후보 **기록**의 하드 리밋이 아니다.
  당일 급등 실현 시간대(09:00~10:30)를 커버하는 조기·고빈도 스캔이 recall 개선의 핵심 레버다.
- [A-2] 장중 재스캔이 생성하는 당일 후보는 same-day 지평으로 귀속되지 않으면 표준 T-1→T 버킷에서
  하루 늦은 날과 비교되어 recall을 못 움직인다 — 따라서 same-day 귀속은 방향 A의 필수 부속
  요구사항이다(REQ-AI083-005).
- [A-3] gather는 순차 HTTP 구조라 1회 12~20분 소요된다(SPEC-AI-082 [E-4]). 이 구조의 동시/배치
  재작성은 본 SPEC 범위 밖이므로, 재스캔 간격은 이 소요를 전제로 설계해야 한다(진짜 "5분 단위
  고빈도"는 gather 재구조화 없이는 불가).

---

## 3. Requirements (EARS)

### 방향 A — 장중 고빈도 재스캔

#### REQ-AI083-001 (Event-Driven, P0) — 09:05~BUY_CUTOFF 구간 고빈도 재스캔 추가

**WHEN** 평일 장 초반(09:05 이후 ~ BUY_CUTOFF 11:00 이전) 구간이면, the system **SHALL** 기존 10:00
단일 스캔에 더해 당일 후보 생성 스캔(`run_surge_signal_generation` 재사용)을 N분 간격으로 추가
실행해야 한다.

- 기존 콜백(`_run_surge_signal_generate`) 또는 그와 동등한 신규 잡을 재사용하되, 스케줄(호출 빈도)만
  확장한다. 정확한 N 및 잡 등록 방식(인터벌형 vs 다중 cron)은 plan.md에서 확정하고, 최소 수용
  기준은 AC-083-001에 고정한다.

#### REQ-AI083-002 (State-Driven, P0) — 중복 실행 방지 (gather 소요 대비 겹침 없음) [HARD]

**WHILE** 직전 재스캔의 gather가 아직 실행 중이면, the system **SHALL** 다음 트리거의 중복 실행을
방지해야 한다(`max_instances=1` + `coalesce=True` 패턴, [E-1] 계승). 즉 재스캔 간격은 gather 최악
소요([E-3], `_GATHER_TIMEOUT_S=1200`=20분)에 대해 실행 겹침이 발생하지 않도록 산정되어야 한다.

#### REQ-AI083-003 (Unwanted, P0) — 자원 경쟁/누적 금지 [HARD]

the system **SHALL NOT** gather 소요보다 짧은 간격으로 스캔을 무한 누적시키거나 Naver/DART 크롤
부하를 병리적으로 가중시켜서는 안 된다. 재스캔 간격 하한은 gather 정상 소요(12~15분) + 헤드룸으로
**유계**여야 하며, 그 근거를 spec/plan에 명시한다(REQ-AI083-013).

- 근거: 진짜 "5분 단위" 고빈도는 순차 gather 재구조화([X-6]) 없이는 불가하므로, 본 SPEC의 "고빈도"는
  gather 소요에 의해 자연히 상한이 잡히는 현실적 재스캔을 의미한다.

#### REQ-AI083-004 (Event-Driven, P0) — 장 초반(09:00~10:00) 사각지대 처리

**WHEN** 09:00~10:00 사이에 이미 실현된 급등을 다룰 때, the system **SHALL** 조기 스캔(예: 09:05~09:15
구간)을 최소 1회 추가해 사각지대를 축소하거나, 그 구간에 이미 실현된 급등을 명시적으로 "미탐(miss)"으로
정확히 집계해야 한다. 둘 중 어느 정책을 채택하는지는 AC-083-004에서 확정한다.

#### REQ-AI083-005 (Ubiquitous, P0) — 당일 후보의 same-day 지평 귀속 [HARD]

장중 재스캔이 **당일(same-day) 급등을 예측**하는 후보를 생성할 때, the system **SHALL** 그 후보를
same-day 평가 지평으로 귀속시켜(SPEC-AI-080의 `horizon` 메타데이터 + `_is_same_day_event_horizon_signal`
평가 경로 재사용) 평가가 올바른 날의 실제 급등과 비교되도록 해야 한다.

- 근거([A-2]): 당일(T) 생성 후보에 지평 태깅이 없으면 표준 `date(created_at)==T-1` 버킷이 T 대신 T+1
  실제 급등과 비교되어, 재스캔을 추가해도 recall이 구조적으로 움직이지 않는다(SPEC-AI-075/080이
  교정한 지평 불일치와 동일 함정). 구체 태깅 메커니즘은 Run 확정이나, "올바른 날 귀속"이라는 결과는
  본 REQ로 고정한다.

#### REQ-AI083-006 (Ubiquitous, P0) — 방향 A 범위 한정 (탐지/앙상블/유니버스/매매 불변) [HARD]

the system **SHALL NOT** 재스캔 확장 과정에서 탐지기 알고리즘, 앙상블 점수/가중치/임계값, 스캔
유니버스 구성, 매수·매매 로직(예측 기록 모드)을 변경해서는 안 된다. 방향 A의 변경은 **스케줄(후보
생성 호출 빈도) 확장 + same-day 지평 귀속 배선**으로 국한한다.

### 방향 B — 이벤트드리븐 즉시발화 (재범위화)

#### REQ-AI083-007 (Ubiquitous, P0) — 활성화된 공시 즉시발화의 회귀 보호 [HARD]

the system **SHALL** 이미 활성인 공시 즉시발화(`immediate_surge.enabled=true`, [E-4])와 그 same_day
평가 경로(`_is_same_day_event_horizon_signal`)를 불변 계약으로 보존해야 한다 — 본 SPEC은 이를
재활성화(재플립)하지 않으며, 관련 코드/설정을 변경하지 않는다.

- 근거([E-4], 정정-1): 작업 지시가 전제한 "플래그 재플립"은 2026-07-16에 이미 완료됨. 본 REQ는 그
  상태가 방향 A 변경으로 회귀하지 않음을 보장한다.

#### REQ-AI083-008 (Event-Driven, P1) — 뉴스 기반 이벤트 재스캔 활성화 [확정·승인됨 2026-07-21]

**WHEN** 고확신 뉴스가 도착하면(`keyword_matching` 완료 훅), the system **SHALL** 뉴스 기반 이벤트
재스캔(`_maybe_trigger_event_rescan`, [E-5])을 발화해야 한다 — 즉
`catalyst_conviction.event_rescan_enabled`를 `false→true`로 활성화한다.

- **[결정 확정 2026-07-21]** 사용자가 방향 B 범위에 REQ-AI083-008(뉴스 재스캔 활성화)까지 포함하는
  권장안을 **승인**했다. 본 요구사항은 조건부/보류가 아닌 **정식 확정 요구사항**이며 Run 대상에
  포함된다. (P1은 방향 A의 P0 핵심 recall 레버 대비 상대적 우선순위일 뿐 "선택 사항"을 의미하지
  않는다.)
- 사전조건: 인프라(`scheduler.py:107-163`, 가드 포함)가 이미 구현됨(SPEC-AI-066 REQ-007). 활성화는
  설정 플립 + 사전조건 검증이며, 인프라 신규 구현이 아니다. 회귀 리스크(뉴스 트리거 정밀도 미검증,
  precision 일시 저하, LLM 예산)는 §5 [R-3]에 고지하고, staged rollout 관례(SPEC-AI-079)를 따른다.

#### REQ-AI083-009 (State-Driven, P1) — 이벤트 재스캔 LLM 예산/자원 가드 준수 [HARD]

**WHILE** 뉴스 이벤트 재스캔이 활성인 동안, the system **SHALL** 기존 가드(종목당 쿨다운
`event_rescan_cooldown_minutes=30`, 일일 상한 `max_daily_event_triggers=20`)를 준수해 정기 스캔·서버
자원을 침해하지 않아야 한다. 가드 값 자체는 본 SPEC에서 변경하지 않는다.

#### REQ-AI083-010 (Unwanted, P0) — 실매매 미트리거 (예측 기록 모드) [HARD]

the system **SHALL NOT** 방향 A·B의 어떤 경로에서도 `execute_signal_trade`를 호출하거나 실제 매수를
트리거해서는 안 된다 — 예측 기록 전용(SPEC-AI-043 계승).

### 공통 제약

#### REQ-AI083-011 (Unwanted, P0) — 기존 T-1→T 배치 파이프라인 불변 [HARD]

the system **SHALL NOT** 기존 15:20 T-1→T 배치 스캔의 크론 시각, 표준 평가 지평(`date(created_at)==T-1`
버킷), 배치 후보 생성 로직을 변경해서는 안 된다 — 회귀 방지. 본 SPEC의 재스캔/즉시발화는 이 배치를
**보완(additive)**할 뿐 대체하지 않는다.

#### REQ-AI083-012 (Unwanted, P0) — BUY_CUTOFF 로직 불변 (재검토만) [HARD]

the system **SHALL NOT** BUY_CUTOFF(11:00) 로직 자체를 변경해서는 안 된다. 재스캔 창의 종료 경계로
BUY_CUTOFF를 참조(read-only)할 수는 있으나, BUY_CUTOFF 값/비교 로직의 변경은 본 SPEC 범위 밖이며 필요
시 별도 SPEC으로 분리한다(§7 [OQ-2]).

#### REQ-AI083-013 (State-Driven, P1) — 최소 간격 산정 근거 명시

**WHILE** 재스캔 간격 N을 산정하는 동안, the system **SHALL** gather 정상 소요(12~15분, 최악 20분,
[E-3])와 Naver/DART 크롤 부하([E-7])를 근거로 최소 간격을 결정하고 그 근거를 spec.md/plan.md에 명시해야
한다. 실측 프로파일링은 Run 단계 선택이나 값 결정을 막지 않는다(블로커 아님).

---

## 4. Exclusions (What NOT to Build) [HARD]

본 SPEC은 다음을 **명시적으로 범위에서 제외**한다:

- [X-1] **공시 즉시발화(`immediate_surge`) 재활성화/로직 변경 금지** — 이미 활성(2026-07-16). 본
  SPEC은 회귀 보호만(REQ-AI083-007). `disclosure_impact_scorer`·`_classify_disclosure_horizon`·
  `_create_immediate_surge_signal` 로직 불변.
- [X-2] **탐지기·앙상블·가중치·임계·스캔 유니버스 구성·후보 소싱 필터 무변경** (REQ-AI083-006). 재스캔은
  기존 탐지 경로를 더 자주 호출할 뿐 탐지 자체를 바꾸지 않는다.
- [X-3] **매수·매매·포트폴리오 로직 무변경** (예측 기록 모드, SPEC-AI-043). `execute_signal_trade`
  미호출(REQ-AI083-010). 비활성된 `surge_execute_buys`/`surge_check_exits`/`force_max_holding_exit`
  잡을 되살리지 않는다.
- [X-4] **기존 15:20 T-1→T 배치 파이프라인/표준 평가 지평 무변경** (REQ-AI083-011).
- [X-5] **DART 크롤 주기(30분) 변경 금지** ([E-7]) — 뉴스/브리핑 등 타 시스템 영향이 커 별도 판단
  필요(§7 [OQ-3]). BUY_CUTOFF 값/로직 변경 금지(REQ-AI083-012).
- [X-6] **`gather_surge_candidates`의 순차 HTTP → 동시/배치 재구조화 금지** — 진짜 "5분 단위" 고빈도를
  가능케 하는 성능 근본 수정이지만 블라스트 반경이 크다(SPEC-AI-082 §8(b) 후속 후보). 본 SPEC은
  gather 소요를 **주어진 제약**으로 두고 재스캔을 설계한다.
- [X-7] **신규 테이블/스키마/마이그레이션/과거 데이터 백필 금지** — 전진 적용만
  (SPEC-AI-071/079/080/082 관례 계승). same-day 지평 귀속은 기존 `surge_metadata`(JSON) + SPEC-AI-080
  평가 경로 재사용으로 스키마 변경 없이 달성한다.
- [X-8] **뉴스 이벤트 재스캔 가드 값(쿨다운 30분/일일 20회) 변경 금지** — 플래그 활성화만
  (REQ-AI083-008/009).

---

## 5. Risks (리스크)

- [R-1] **재스캔 간격 vs gather 소요 겹침 리스크.** N < gather 소요면 `max_instances=1`이 후속 트리거를
  건너뛰어(misfire) 실효 빈도가 gather 소요로 자연 수렴한다 — 무해하나 "고빈도"가 명목에 그친다.
  완화: 간격을 gather 정상 상단(15분)+헤드룸으로 산정(REQ-AI083-013), `coalesce=True`로 다중 미스파이어를
  1회로 접음. 근본 상향(진짜 고빈도)은 [X-6] 후속 SPEC.
- [R-2] **서버 자원/크롤 부하 리스크.** 각 재스캔이 12~20분 gather(종목당 다중 Naver/DART HTTP)를
  수행하므로, 재스캔 횟수가 늘면 크롤 트래픽·CPU가 증가한다. 완화: 09:05~11:00 창 + 유계 간격으로
  제한(REQ-AI083-003), 예측 기록 모드라 매수 사이드 부하는 없음.
- [R-3] **[확정 범위의 잔존 위험] 뉴스 이벤트 재스캔 트리거 품질 미검증 + precision 일시 저하 + LLM
  예산 소모.** 사용자가 REQ-AI083-008 활성화를 **승인(2026-07-21)**했으나, **활성화만으로 당일 추가
  커버리지는 보장되는 반면 뉴스 트리거 자체의 정밀도(고확신 뉴스 → 실제 급등 상관)는 아직 라이브로
  검증되지 않았다.** 촉매 유니버스 확장으로 후보가 늘면 precision이 일시 하락할 수 있고(자금 리스크 0,
  예측 기록 모드), catalyst conviction 산출이 LLM을 호출할 수 있다. 완화: 기존 가드(쿨다운 30분/일일
  20회) 준수(REQ-AI083-009), staged rollout(SPEC-AI-079 관례), 롤백=플래그 `false` 복귀, 활성화 후 첫
  수 거래일간 이벤트 재스캔 발화 로그·precision을 관측해 트리거 품질을 사후 검증한다. **결정 상태:
  확인 완료(승인됨) — 오케스트레이터의 사용자 고지·확인 절차 종료.**
- [R-4] **same-day 지평 귀속 누락 리스크(방향 A 최상위).** 재스캔 후보에 same-day 귀속을 배선하지
  않으면 recall이 전혀 움직이지 않아 SPEC 목적이 무효화된다. 완화: REQ-AI083-005를 P0 [HARD]로 고정,
  acceptance에서 same-day 서브지표 편입을 관찰 가능 증거로 검증.
- [R-5] **비활성 잡 오복구 리스크.** 재스캔 잡 등록 시 주석 처리된 `surge_execute_buys`/
  `surge_check_exits`를 실수로 되살리면 예측 기록 모드가 깨진다. 완화: [X-3] 명시, 재스캔 잡은 후보
  생성(`run_surge_signal_generation`)만 호출하고 매수/청산 콜백을 참조하지 않음(코드 리뷰 게이트).

---

## 6. Related SPECs (관련 SPEC)

- **SPEC-AI-013 (선행)**: `_run_surge_signal_generate`/`run_surge_signal_generation` 원 소유(급등 시그널
  독립 생성). 본 SPEC은 그 잡의 스케줄(빈도)만 확장.
- **SPEC-AI-038 (인접)**: 10:00 장중 재탐지 잡(`surge_signal_generate_intraday`, REQ-038-003)을 도입한
  SPEC. 본 SPEC은 그 단일 잡을 고빈도 재스캔으로 확장(대체가 아닌 확장).
- **SPEC-AI-080 (재사용·회귀 보호 대상)**: 공시 즉시발화 + same_day 지평 평가 경로
  (`_is_same_day_event_horizon_signal`) 소유. 방향 A는 이 same_day 인프라를 재사용(REQ-AI083-005),
  방향 B는 이 활성 상태를 회귀 보호(REQ-AI083-007).
- **SPEC-AI-066 (활성화 대상)**: 뉴스 기반 이벤트 재스캔(`_maybe_trigger_event_rescan`, REQ-007)
  인프라 소유. 방향 B는 이 인프라의 플래그(`event_rescan_enabled`)를 활성화(REQ-AI083-008).
- **SPEC-AI-079 (참고 패턴)**: 이미 구현된 기능의 설정 플립 활성화 + staged rollout 관례 —
  REQ-AI083-008 활성화에 계승.
- **SPEC-AI-082 (제약 출처)**: `_GATHER_TIMEOUT_S=1200`(gather 최대 20분). 재스캔 간격 설계의 핵심
  제약([E-3]). 로직 무변경.
- **SPEC-AI-043 (계승)**: 예측 기록 모드(실매매 비활성) — 매매 무변경(REQ-AI083-010, [X-3]).

---

## 7. Open Questions (열린 질문 — Run/Annotation 단계 확정)

- [OQ-1] **재스캔 잡 등록 방식.** (a) 인터벌형 단일 잡(장 초반 창에서 N분마다), (b) 다중 cron 잡(09:10/
  09:40/10:10 등 고정 시각), (c) 기존 10:00 잡을 창 인터벌로 대체. gather 소요·`max_instances`
  상호작용 관점에서 plan.md가 권고안을 제시하되, 최종 확정은 annotation 단계.
- [OQ-2] **BUY_CUTOFF 재검토 결론.** 예측 기록 모드에서 BUY_CUTOFF는 후보 기록을 제한하지 않으므로
  재스캔 창을 11:00 이후(예: 15:20까지)로 넓힐지 여부. 본 SPEC은 09:05~11:00으로 보수적으로 시작하고,
  창 확장은 별도 판단(REQ-AI083-012는 코드 변경만 금지, 창 상한 선택은 열림).
- [OQ-3] **DART 크롤 주기(30분)가 공시 즉시발화 시의성에 충분한가.** 09:00~10:00 공시 즉시발화의
  지연(최대 30분)을 줄이려면 장 초반 한정 크롤 주기 단축이 필요할 수 있으나, 타 시스템 영향이 커
  본 SPEC 범위 밖([X-5]). 필요 시 별도 SPEC.
- [OQ-4] **same-day 귀속 트리거 조건.** 장중 재스캔이 생성한 후보 중 "당일 급등 예측"으로 same-day
  귀속할 대상을 어떻게 판정할지(전량 same_day vs 특정 조건). SPEC-AI-080의 `_classify_disclosure_horizon`
  시간 기반 규칙(09:00~batch_cutoff → same_day)을 재사용하는 안이 유력(Run 확정).

---

## 8. Follow-up Candidates (후속 후보 — 본 SPEC 범위 밖)

- (a) **`gather_surge_candidates` 동시/배치 HTTP 재구조화([X-6])** — 순차 per-stock fetch를 동시성/배치로
  전환해 진짜 분 단위 고빈도 재스캔을 가능케 하는 성능 근본 수정(SPEC-AI-082 §8(b)와 동일 후보).
- (b) **장 초반 한정 DART 크롤 주기 단축([OQ-3])** — 09:00~10:00 공시 즉시발화 지연 축소.
- (c) **BUY_CUTOFF 재설계 / 재스캔 창 15:20 확장([OQ-2])** — 예측 기록 모드 전제에서 후보 기록 창을
  넓히는 별도 SPEC.
- (d) **재스캔 시의성 실측 프로파일링** — 조기 스캔(09:10)이 실제로 09:00~10:00 급등을 얼마나 조기
  포착하는지 라이브 계측(관측 전용).
