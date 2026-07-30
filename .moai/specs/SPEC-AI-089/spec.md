---
id: SPEC-AI-089
title: "스캔 유니버스→탐지 배선 측정 스파이크 (Universe-to-Detection Wiring Measurement Spike)"
version: "0.1.1"
status: completed
created: 2026-07-27
updated: 2026-07-30
author: Nexsol
priority: High
phase: "backend surge-detection v0.1.0"
module: "backend/app/services"
lifecycle: spec-anchored
tags: "surge-detection, scan-universe, detection-wiring, coverage, recall, measurement, backend"
tier: L
depends_on: [SPEC-AI-086, SPEC-AI-087]
related_specs: [SPEC-AI-065, SPEC-AI-076, SPEC-AI-078, SPEC-AI-082, SPEC-AI-083, SPEC-AI-043]
---

# SPEC-AI-089: 스캔 유니버스→탐지 배선 측정 스파이크 (Universe-to-Detection Wiring Measurement Spike)

## HISTORY

- 2026-07-27 v0.1.0 (draft): 초안 생성. SPEC-AI-086이 확정한 "`build_scan_universe`는 측정 전용
  그림자 유니버스"라는 사실(Exclusion 1로 배선을 명시적으로 후속 SPEC에 위임)을 이어받아, 사용자
  승인(AskUserQuestion, "새 SPEC으로 정식 착수")에 따라 배선 작업의 **정식 착수 SPEC**으로 시작한다.
  이번 세션의 read-only 조사(코드 읽기 + line-range 매핑)로 사용자의 최초 작업 지시("탐지기별로
  유니버스를 배선하라")가 가정한 프레이밍이 부분적으로 부정확함을 확인 — 상세는 research.md
  Finding F-6/F-7. 이에 따라 본 SPEC의 실질 범위를 "즉시 배선 구현"에서 "측정 스파이크(M1) +
  사용자 재확인 결정 게이트(M2)"로 좁혔다. `[NEEDS CLARIFICATION: 배선 방식 A/B/C 중 선택]`
  마커가 plan.md에 존재 — Implementation Kickoff Approval 이전에 반드시 해소되어야 한다.
- 2026-07-27 v0.1.0 (draft, plan-auditor iteration 1 반영): iteration 1 FAIL(0.80, MP-7)의
  지적사항을 반영 — plan.md §A의 `[NEEDS CLARIFICATION]` 마커를 해소된 결정으로 대체하여
  Implementation Kickoff Approval을 M1 범위로 명시적으로 한정(M2/M3+는 본 SPEC의 자율 실행
  범위 밖·정보 제공용으로 재표기), REQ-001~004의 정규문에서 구현 식별자(함수명·딕셔너리명)를
  제거하고 "> 구현 참고:" 블록으로 이동, REQ-004/AC-089-004에 정량 임계값(비활성 대비 5%
  이내 증가 + 안전 상한 대비 최소 120초 여유) 추가, REQ-007(관측성)에 대응하는 AC-089-007 +
  시나리오 4 + DoD 항목 신설.
- 2026-07-27 v0.1.1 (draft, plan-auditor iteration 2 반영): iteration 2 FAIL(0.80, MP-7 미해소 —
  점수 정체)의 지적사항 5건을 반영 — (D2, major) REQ-AI089-003의 ACTIVE-state(계측 활성화 상태)
  불변식이 그동안 OFF/기본값 케이스만 검증되던 것을 시정하여 acceptance.md에 AC-089-008 + 시나리오
  5 + DoD 항목을 신설하고 REQ-003 traceability를 명시, (D1) design.md § M2 결정 게이트의
  `[NEEDS CLARIFICATION]` 잔존 서술(plan.md가 "현재" 그 마커를 갖고 있다는 오기)을 iteration 1에서
  이미 해소된 상태를 반영하도록 과거형으로 정정, (D3) plan.md §F의 비용 예산 증거 문구
  "유의미하게 증가하지 않음"을 REQ-004/AC-089-004의 정량 임계값(비활성 대비 5% 이내 증가 +
  1080초 이하)과 일치시킴, (D4) REQ-005/006의 GEARS 키워드를 정적 capability-gate 의미의
  **Where**에서 이벤트 감지 의미의 **When**으로 정정(두 REQ 모두 "M1 완료" / "M2 승인"이라는
  이벤트를 전제 조건으로 삼으므로), (D5) acceptance.md AC-089-006에 `(REQ-AI089-006)` 명시적
  인용 추가(기존 인용 패턴과 일치).

## 선행 SPEC (전제 조건 / Assumptions)

- **SPEC-AI-086** (완료): `build_scan_universe()`가 측정 전용 그림자 유니버스임을 확정하고, 유니버스→
  탐지 배선을 Exclusion 1로 명시적으로 후속 SPEC에 위임했다. 본 SPEC이 그 후속이다.
- **SPEC-AI-087** (완료): `volume_anomaly`/`group_cascade`/`gap_up_runners` 3개 탐지기의 NULL 시총
  후보 편입을 opt-in(기본 OFF)으로 도입. 본 SPEC은 이 3개 탐지기의 **NULL 시총 필터**가 아니라
  **유니버스 멤버십 자체**를 다룬다는 점에서 층위가 다르다(중복 아님, research.md F-6에서 경계 확인).
- **SPEC-AI-082**: `gather_surge_candidates()` 단일 호출의 안전 상한 `_GATHER_TIMEOUT_S=1200`(20분),
  정상 소요 12~15분. 본 SPEC의 측정 스파이크(M1)는 이 예산에 영향을 주지 않아야 한다(REQ-006).
- **SPEC-AI-083**: 평일 09:10/09:35/10:00/10:30/10:55/15:20 KST — `gather_surge_candidates()`가
  하루 6회 실행된다(핫 패스). 측정 로직을 이 경로에 직접 추가하면 6배로 비용이 곱해진다(research.md F-8).
- **SPEC-AI-065/076/078**: `max_scan_universe`(150, clamp [50,600]) 소유권, quota 배분, Pool A
  impact 정렬은 본 SPEC의 대상이 아니다 — 무변경.
- **SPEC-AI-043**: 급등예측은 예측 기록 모드(매수/청산 비활성)다. 본 SPEC은 이 모드를 유지한다.
- **SPEC-AI-088**(같은 세션 병행 작성, 별개 SPEC): same-day 시그널의 순환논리(price_at_signal이
  이미 급등한 뒤 태깅되는 문제) 측정 SPEC — 본 SPEC과 문제 영역이 다르다(호라이즌 측정 오염 vs
  유니버스-탐지 구조적 미배선). 상호 무관하며 겹치지 않는다.

## Context / Problem

이번 세션의 심층조사(직접 DB 조회 + 코드 읽기, 모두 독립 검증)로 급등예측 recall 근사 0%
(2026-07-24: TP=0/26)가 **스캔 유니버스(측정 대상)와 실제 탐지 후보 풀(탐지기가 실제로 고려하는
대상) 사이의 구조적 간극**에서 비롯됨을 확인했다. 26개 실제 급등 종목 중 2개(7.7%)만 T-1 스캔
유니버스 안에 있었고, 18개(69%)는 급등 당일 어떤 종류의 시그널도(surge_candidate/disclosure_impact/
volume_anomaly/gap_pullback_candidate/sector_ripple 전부) 받지 못했다.

### 이번 세션 조사로 확인된 사실 (read-only, 2026-07-27) — 상세는 research.md

- **[F-1, SPEC-086 계승 재확인]** `build_scan_universe()`(`surge_detector.py:4514`)는
  `gather_surge_candidates()` 내부에서 8개 1차 탐지기(theme_cluster/combo/pattern/immediate/
  delayed/breakout/momentum + 병합)가 **모두 실행된 뒤**(`:1934`, `existing_codes=merged.keys()`)
  호출된다. 반환된 `_universe_codes`는 entry_pool 태깅과 커버리지 지표 영속화에만 소비되고
  탐지 후보 목록(`merged`)에 재투입되지 않는다. 재검증 결과 SPEC-086 f-1은 여전히 유효하다.
- **[F-2, 신규]** 사용자 최초 작업 지시가 가정한 "탐지기별로 유니버스를 배선하라"는 프레이밍은
  탐지기 유형에 따라 성립하지 않는다:
  - `volume_anomaly`(`_detect_volume_anomaly_internal`)는 이미 `max_scan_universe`(150~600) 상한과
    무관하게 `market_cap >= 300억`인 **전체** 추적 종목을 스캔한다(쿼리에 LIMIT 없음, 코드 주석
    "무제한 유지" — `:2502-2506`). 이 탐지기의 배제 축은 "유니버스 밖"이 아니라 "시총 300억 미만
    또는 NULL"이다(SPEC-087이 NULL 경로만 opt-in으로 이미 다룸). 유니버스 배선이 이 탐지기의
    커버리지를 넓히지 않는다.
  - `group_cascade`/`gap_up_runners`는 "블랭킷 스캔"이 아니라 "**이미 탐지된** 시그널로부터의
    캐스케이드"다. `detect_group_cascade_signals`의 1차 루프 입력은 `surge_results`
    (`gather_surge_candidates`의 병합 결과, `:3620`) 그 자체이며, `Stock` 테이블 블랭킷 쿼리가
    아니다. 계열사/피어 후보 필터(SPEC-087 REQ-004/005 대상)는 대장주/리더가 **이미 시그널을
    받은 이후의** 2차 확장일 뿐이다. 유니버스 멤버십을 이 2차 확장 지점에 배선해도 애초에 대장주가
    탐지되지 못하면(F-1의 핵심 문제) 무의미하다.
- **[F-3, 신규]** `build_scan_universe`의 Pool B(거래량 200%+)와 Pool C(당일 등락률 5%+)는 "오늘
  이미 움직이는 종목" 시그널이지만, 8개 1차 탐지기 중 어느 것도 이를 후보 시드로 소비하지 않는다.
  `detect_volume_breakout`(앙상블 가중치 `w.volume_breakout` 보유, 8개 탐지기 중 하나)은 Pool B와
  **거의 동일한 로직**(`fetch_volume_leaders_sync` + 종목당 `fetch_stock_price_history_sync`,
  `:4245/:4269`)을 **독립적으로 재계산**한다 — Pool B와 병렬·중복 계산이며, 통합/교차 검증되지
  않는다.
- **[F-4, 신규]** `compute_ensemble_score()`(`:1533`)는 7개 탐지기 점수의 순수 가중합이다
  ("raw momentum" 같은 범용 점수 항목 없음). 따라서 Pool B/C 코드를 단순히 앙상블 스코어링에
  주입하는 것만으로는 점수가 0이 된다 — 최소 1개 탐지기가 실제로 그 종목에 대해 점수를 내야 한다.
  "유니버스를 배선한다"는 표현이 실제로 의미할 수 있는 구현은 최소 두 가지 서로 다른 형태
  (§design.md 참고)이며, 그 선택이 비용/리스크 프로파일을 크게 바꾼다.
- **[F-5]** `gather_surge_candidates()`는 평일 하루 6회(09:10/09:35/10:00/10:30/10:55/15:20 KST)
  실행되며, 단일 호출 안전 상한이 `_GATHER_TIMEOUT_S=1200`(20분)이다(SPEC-AI-082). 정상 소요
  12~15분. 탐지 경로에 종목당 네트워크 조회(`fetch_stock_price_history_sync`)를 추가하는 배선은
  이 예산을 6배로 곱해 소진할 위험이 있다 — 이것이 SPEC-086이 배선을 후속 SPEC으로 명시적으로
  분리한 근거였다(Exclusion 1).

### Goal

이 SPEC은 **배선을 즉시 구현하지 않는다.** 대신 (1) M1에서 측정 전용(탐지 로직 무변경) 계측을
추가해 "유니버스 풀(A/B/C)과 각 탐지기의 기존 후보망 사이에 실제로 얼마나 간극이 있는가"와
"69% 무시그널 실제급등 종목이 어느 풀에 있었고, 어느 탐지기가 그 풀 코드를 받았다면 시그널을
냈을 개연성이 있는가"를 소량 표본(수 거래일)에 대해 측정한다. (2) 그 결과를 사용자에게 보고하고,
어느 배선 방식(§design.md 옵션 A/B/C)을 택할지 — 혹은 배선이 실제로는 낮은 가치라는 결론에
도달할지 — 를 M2 결정 게이트에서 재확인받는다. (3) M2에서 승인된 방식만 후속 마일스톤(M3+,
본 SPEC 범위 내 조건부 또는 별도 후속 SPEC)에서 flag-gated(기본 OFF)로 구현한다.

### Run-phase 범위 (Implementation Kickoff Approval의 적용 범위)

**본 SPEC의 run-phase 실행 범위는 M1(측정 스파이크)로 한정된다.** Implementation Kickoff
Approval은 M1 실행만을 승인하며, M2(배선 방식 결정)는 M1 완료 후에만 존재하는 별도의
AskUserQuestion 라운드이고, M3+(조건부 배선 구현)는 M2 승인이 있을 때만 진행된다(plan.md
§A "해소된 결정" 및 §C 마일스톤 참고). M1 완료 + 측정 리포트 제출만으로 본 SPEC은 유효하게
완료되며, 배선 구현 없이 완료되는 것이 valid한 결과다.

## Requirements (GEARS)

### REQ-AI089-001 (Ubiquitous, P0) — 유니버스-탐지망 간극 측정 계측
The system **shall** 평가 가능한 각 거래일에 대해, 스캔 유니버스가 산출하는 풀별(A/B/C) 코드
집합과 그날 실제로 실행된 1차 탐지기들이 만들어낸 탐지 후보 코드 집합 사이의 차집합·교집합을
계산하고, 그 결과를 재현 가능한 형태(리포트 아티팩트)로 기록한다.
> 구현 참고: 측정 지점은 `gather_surge_candidates()` 내부 기존 `build_scan_universe()` 호출부
> (`surge_detector.py:1934`) 직후 — 이미 계산되어 있는 `_universe_codes`/`_entry_pool_map`과
> `merged.keys()`를 비교하는 순수 인메모리 집합 연산(신규 네트워크 조회 없음).

### REQ-AI089-002 (Ubiquitous, P0) — 무시그널 실제급등 종목 풀 귀속 분석
The system **shall** 표본 거래일 각각에 대해, 그날 무시그널(어떤 종류의 시그널도 발행되지
않은 상태)로 확인된 실제 급등 종목에 대해, 그 종목이 스캔 유니버스의 어느 풀(A/B/C/부재)에
속했는지, 그리고 그 풀 소속만으로 어느 탐지기가 후보로 고려했을 개연성이 있는지를 서술적으로
분류하여 기록한다.
> 구현 참고: 무시그널 판정 기준은 disclosure_impact/preday_disclosure/volume_anomaly/
> gap_pullback_candidate/sector_ripple/surge_candidate 전부 부재. `SurgeActualOutcome` ×
> `SurgeUniverseMember`(SPEC-AI-068) 조인 재사용 — 신규 테이블 없이 기존 두 테이블만으로
> 산출 가능(research.md 확인).

### REQ-AI089-003 (When undesired-detected, P0) — 측정 계측의 탐지 무영향 불변식 [HARD]
**When** 본 SPEC의 측정 계측(REQ-001/002)이 활성화된 상태로 급등 후보 수집 사이클이 실행되는
것이 감지되면, the system **shall NOT** 기존 1차 탐지기들의 후보 집합, 앙상블 점수, 발행
시그널 수, 또는 그날의 병합된 탐지 후보 내용을 어떤 방식으로도 변경한다. 측정은 순수
읽기·집계이며 탐지 파이프라인의 출력에 영향을 주지 않는다.
> 구현 참고: 급등 후보 수집 사이클은 `gather_surge_candidates()`, 병합된 탐지 후보는 그 함수
> 내부의 `merged` 딕셔너리를 가리킨다.

### REQ-AI089-004 (When undesired-detected, P0) — 스캔 사이클 비용 예산 불변식 [HARD]
**When** 측정 계측이 실행되는 것이 감지되면, the system **shall NOT** 급등 후보 수집 사이클의
단일 호출당 신규 외부 네트워크 조회(Naver 시세/거래량 API)를 추가하거나, 안전 상한에 근접시키는
지연을 유발한다. 구체적으로, 측정 계측 활성화 상태의 단일 호출 소요 시간은 (a) 계측 비활성화
상태 대비 **5% 이내 증가**하고, (b) 안전 상한보다 **최소 120초(2분) 낮은 수준**을 유지해야
한다. 측정은 이미 계산된 인메모리 결과에 대한 집합 연산과 DB 조인만 사용한다.
> 구현 참고: 급등 후보 수집 사이클은 `gather_surge_candidates()`, 인메모리 결과는
> `_universe_codes`/`merged`, 안전 상한은 `_GATHER_TIMEOUT_S`(1200초, SPEC-AI-082) —
> 즉 계측 활성화 시 단일 호출 소요는 1080초(1200초 − 120초) 이하를 유지해야 한다. 정상 소요는
> 12~15분(720~900초)이므로 이 기준은 기존 버퍼(약 300초) 내에서 충분히 달성 가능하다
> (research.md § 비용/스케줄 제약).

### REQ-AI089-005 (Event-driven, P1) — 결정 게이트 산출물
**When** M1 측정이 완료된 것이 감지되면, the system **shall** REQ-001/002의 측정 결과를 사용자가
검토 가능한 단일 리포트(간극 비율, 무시그널 종목별 풀 귀속 분류, 배선 방식 옵션별 예상 비용/리스크
정성 평가 포함)로 통합하여 제시하며, M2 결정 게이트(배선 방식 선택 또는 배선 보류 결정)를 통과하기
전까지 어떠한 탐지 로직 변경도 진행하지 아니한다.
> 구현 참고: M2는 orchestrator의 AskUserQuestion을 통한 human 결정 지점이다(에이전트가 자율
> 결정하지 않음) — `.claude/rules/moai/core/askuser-protocol.md` § Report-Before-Ask Gate 준수.
> GEARS 표기 참고: 본 REQ의 조건("M1 측정이 완료된 것")은 정적 capability/feature flag가 아니라
> 시간에 따라 발생하는 이벤트이므로, capability-gate 의미의 **Where**가 아니라 이벤트 감지 의미의
> **When**을 사용한다.

### REQ-AI089-006 (Event-driven, P2) — M2 승인 시 조건부 배선 구현 (flag-gated)
**When** M2에서 특정 배선 방식이 사용자 승인을 받은 것이 감지되면, the system **shall** 그 방식을
기본값 비활성(OFF)의 신규 설정 플래그로 구현하며, 플래그가 기본값일 때 본 SPEC 적용 이전과
바이트 동등한 탐지 후보 집합·시그널 생성 결과를 낸다(SPEC-AI-076/084/086/087 단계적 롤아웃
관례 계승).
> GEARS 표기 참고: 본 REQ의 조건("M2 승인을 받은 것")도 REQ-005와 동일하게 이벤트이며, 승인
> 이후에 구현되는 신규 설정 플래그 자체(기본값 OFF)는 REQ-006이 규정하는 **결과물**이지 본 REQ의
> 전제 조건이 아니다 — 따라서 이벤트 감지 의미의 **When**을 사용한다.

### REQ-AI089-007 (Where, P2) — 관측성
**Where** 로깅이 유효한 경우, the system **shall** 측정 실행 여부·소요 시간·간극 요약(풀별
raw/미탐지망 커버 개수)을 단일 로그 라인으로 기록하며, 신규 스키마를 도입하지 아니하고 종목별
상세 로그를 남기지 아니한다.

## Out of Scope (What NOT to Build)

### Out of Scope — 배선 구현 자체 (M2 결정 이전)
- 본 SPEC의 M1은 **측정 전용**이다. M2 사용자 승인 없이 어떤 탐지기의 후보 쿼리·병합 로직도
  수정하지 않는다. REQ-006의 "조건부 구현"은 M2 승인을 전제 조건으로 하며, 승인이 없으면
  본 SPEC은 측정 리포트 산출로 완료된다(구현 없이 완료되는 것이 유효한 결과다).

### Out of Scope — 매매 실행
- SPEC-AI-043 예측기록모드(매수/청산 비활성)를 유지한다. 본 SPEC은 시그널 생성·측정에만 관여하며
  `SurgePortfolio`/`SurgeTrade` 실행 로직을 다루지 않는다.

### Out of Scope — SPEC-AI-086/087 재개봉
- `max_scan_universe`/quota 배분/Pool A impact 정렬(SPEC-AI-065/076/078, SPEC-AI-086 소유)과
  NULL 시총 opt-in 편입(SPEC-AI-087 소유)은 무변경. 본 SPEC은 이들의 **출력**(유니버스 코드,
  기존 탐지 후보)을 읽기 전용으로 비교할 뿐이다.

### Out of Scope — SPEC-AI-088 범위
- same-day 시그널의 순환논리(price_at_signal 사전예측 여부 측정)는 SPEC-AI-088의 범위다. 본
  SPEC은 T-1→T 스캔 유니버스와 탐지망 간극이라는 다른 문제를 다룬다. 두 SPEC은 서로의 산출물을
  전제하지 않는다.

### Out of Scope — 탐지기 본체/앙상블 가중치 튜닝
- `compute_ensemble_score`의 가중치, `min_score_for_signal` 임계값, 개별 탐지기 파라미터
  (`volume_ratio_threshold` 등)는 본 SPEC의 대상이 아니다.

### Out of Scope — 과거 데이터 백필
- 과거 스캔 유니버스/탐지 결과의 소급 재계산·백필은 수행하지 않는다(SPEC-AI-076/086 관례
  계승 — 전진 적용 또는 표본 기간 한정 측정만).

### Out of Scope — 신규 DB 마이그레이션
- REQ-001/002는 기존 `SurgeUniverseMember`(SPEC-AI-068)/`SurgeActualOutcome`/`FundSignal` 테이블
  조인만으로 산출 가능하다고 판단된다(research.md 확인). M1 범위에서 신규 마이그레이션은
  요구되지 않는다. M2에서 특정 배선 방식이 신규 스키마를 요구한다고 판명되면, 그 요구사항은
  M2 리포트에 명시하고 별도 후속 SPEC으로 분리한다.

## Ownership

- **본 SPEC**: 유니버스↔탐지망 간극 측정 계측(REQ-001/002) + 결정 게이트 산출물(REQ-005) +
  M2 승인 시 조건부 flag-gated 배선(REQ-006, 승인 여부에 따라 실질 구현 범위가 달라짐).
- **SPEC-AI-086**: `build_scan_universe` 측정 전용 그림자 유니버스 소유자 — 본 SPEC이 소비하는
  풀 계산 로직 자체는 무변경.
- **SPEC-AI-087**: 3개 탐지기의 NULL 시총 opt-in 편입 소유자 — 본 SPEC의 유니버스 멤버십 배선과는
  다른 층위(§Context F-2 참고).
- **SPEC-AI-082/083**: gather 타임아웃(1200s)·인트라데이 재스캔 스케줄 소유자 — 본 SPEC의 비용
  예산 불변식(REQ-004)이 준수해야 할 제약 조건.
