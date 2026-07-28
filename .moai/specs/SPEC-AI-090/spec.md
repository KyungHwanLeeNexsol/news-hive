---
id: SPEC-AI-090
title: "연속성 계열 탐지기 평가 기준 재검토 측정 스파이크 (Continuation-Detector Evaluation-Bar Recalibration Measurement Spike)"
version: "0.1.1"
status: draft
created: 2026-07-28
updated: 2026-07-28
author: Nexsol
priority: Medium
phase: "backend surge-detection v0.1.0"
module: "backend/app/services"
lifecycle: spec-anchored
tags: "surge-detection, evaluation-methodology, momentum-continuation, near-limit-up-carry, measurement-only, backend"
tier: S
related_specs: [SPEC-AI-065, SPEC-AI-023, SPEC-AI-072, SPEC-AI-070, SPEC-AI-089]
---

# SPEC-AI-090: 연속성 계열 탐지기 평가 기준 재검토 측정 스파이크

## HISTORY

- 2026-07-28 v0.1.0 (draft): 초안 작성. 오케스트레이터가 프로덕션 DB(`surge_detector_contribution`,
  `surge_prediction_evaluation`)를 직접 조회하여 확인한 값(본 세션 인수인계 데이터, 아래 §Context
  참조)에 근거해, `momentum_continuation`/`near_limit_up_carry` 두 "연속성(continuation)" 계열
  탐지기의 `solo_tp`가 관측 구간(07-20~07-27) 전일 0으로 지속됨을 SPEC화한다. 이 결과가 탐지
  가설 자체의 실패인지, 평가 기준(`was_surge`)이 "연속" 주장에 부적합한 바(bar)인지 아직
  근본원인 분리가 안 되어 있으므로, 본 SPEC은 **측정 전용**으로 이 둘을 분리한다.
- 2026-07-28 v0.1.1 (draft, plan-auditor iteration 1 반영): iteration 1 FAIL(0.87, MP-2) 대응.
  감사 보고서 `.moai/reports/plan-audit/SPEC-AI-090-review-1.md`의 지적사항을 반영.
  - **(MP-2, critical)** AC-090-001~006 전부를 `**Given**/**When**/**Then**` 단독 서술에서 **볼드
    EARS/GEARS 정규 문장**(the system **shall**/**shall NOT** + 단일 트리거)으로 전환하고, 기존
    Given/When/Then 내용은 "재현 시나리오(비규범)"로 명확히 구분해 각 AC 아래에 병기. SPEC-AI-089
    (`acceptance.md`, plan-audit PASS 확인)의 GEARS-AC + 별도 비규범 GWT 블록 구조를 그대로 따른다 —
    각 EARS 문장은 트리거 키워드 1개(**WHEN**/**WHILE**/**IF**/**WHERE**) + SHALL/SHALL NOT 절 1개만
    포함하며, 복합 2-절 문장·em-dash 결합 2차 정규 절·볼드 SHALL과 비형식 한국어 모달 혼용을 금지한다
    (SPEC-AI-081 iteration 2/3 교훈).
  - **(D2, major)** plan.md §D 사전 점검 3단계가 존재하지 않는 `tests/test_surge_contribution_service.py`를
    참조하던 오류를 실제 존재하는 `tests/test_spec_ai_070.py`로 정정.
  - **(D3, major)** §선행 SPEC의 SPEC-AI-089 상태 서술("완료")을 실제 frontmatter `status: in-progress`
    (plan-audit만 PASS, run-phase 미완료)에 맞게 정정.
  - **(D4, minor)** §선행 SPEC의 SPEC-AI-070 상태 서술("완료")을 실제 frontmatter `status: draft`에 맞게
    정정(함수 자체는 구현·운영 중이나 SPEC 문서는 draft로 남아있음을 명시).
  - **(D5, minor)** §Out of Scope 6개 하위 섹션 전부를 프로즈 단락에서 `-` bullet 형식으로 전환
    (`OutOfScopeRule` 린트 컨벤션 + SPEC-AI-089 컨벤션 정합).
  - **(D6, minor)** REQ-AI090-001/002의 정규문에 직접 노출되어 있던 DB 테이블/필드 식별자를
    REQ-003~006과 동일하게 `> 구현 참고:` 블록으로 이동, 정규문은 WHAT 수준으로 유지.

## 선행 SPEC (전제 조건 / Assumptions)

- **SPEC-AI-065 REQ-3** (완료): `detect_momentum_continuation()`(`surge_detector.py:4371`) —
  전일(T-1) `change_rate`가 `[5.0, 15.0)`% 범위인 종목을 익일 재발행하는 탐지기. 앙상블
  `weighted_sum` 항에 `momentum_continuation` 가중치(운영 설정값 `0.12`,
  `surge_detection.yaml:74`)로 편입되어 있다(`DETECTOR_REGISTRY`의
  `ensemble_weighted_sum` 분류, `surge_contribution_service.py:81`). 본 SPEC은 이 탐지기의
  후보 선정 로직(범위 `[5,15)`%, `base_score`/`max_score`, BEAR 감쇠)을 변경하지 않는다.
- **SPEC-AI-023 / SPEC-AI-072 / SPEC-AI-077** (완료): `detect_near_limit_up_carries()`
  (`surge_detector.py:2722`) — 전일(T-1) 종가-대-종가 `change_rate`가
  `[near_limit_up_min_pct(15.0), near_limit_up_max_pct(29.99)]`% 범위인 종목에 직접
  `FundSignal`(`signal_type="surge_candidate"`, `paper_executed=True`)을 발행한다.
  **[HARD 사실]** 이 탐지기는 `compute_ensemble_score`의 `weighted_sum`에 편입되지 **않는다** —
  `DETECTOR_REGISTRY`에서 `standalone_bypass`로 분류된다(`surge_contribution_service.py:90`).
  즉 momentum_continuation과 달리 "앙상블 가중치"라는 조정 레버 자체가 존재하지 않으며,
  조정 가능한 레버는 confidence 공식(`change_rate/30.0*0.5`)과 임계 범위·활성화 플래그뿐이다.
  본 SPEC은 이 구분을 §Goal/§Out of Scope에서 명시적으로 반영한다.
- **SPEC-AI-070** (기능 구현·운영 중, SPEC 문서 자체는 draft): `evaluate_detector_contribution()`
  (`surge_contribution_service.py:254`)이 매일 T-1 `surge_basis` 멤버십 × T당일 "scannable"
  실제급등 결과로 탐지기별 `emission_count`/`solo_count`/`solo_tp`/`coincident_hit_rate`/
  `unique_catch`를 산출해 `surge_detector_contribution` 테이블에 upsert한다. "scannable"
  실제급등 판정은 `SurgeActualOutcome.surge_type == "scannable"`이며, 이는
  `was_surge(change_rate >= 10.0)` **그리고** T-1 스캔 유니버스 소속(SPEC-AI-068)을 모두
  요구하는 결합 조건이다(`surge_evaluation_service.py:913`,
  `row.surge_type = "scannable" if row.stock_code in universe_set else "non_scannable"`).
  본 SPEC은 이 함수·테이블·집계 정의를 변경하지 않고 별도 부가 분석 경로로만 재활용한다.
- **SPEC-AI-089** (in-progress, plan-audit PASS): 유니버스↔탐지망 간극을 측정 스파이크(M1)+결정
  게이트(M2) 2단계로 분리한 선행 사례 — plan-audit만 통과했고 run-phase는 아직 완료되지 않았다.
  본 SPEC은 동일한 "측정 먼저, 조정은 후속 SPEC" 패턴을 따른다. 문제 영역은 다르다(유니버스 배선
  vs 평가 기준 적합성) — 서로의 산출물을 전제하지 않는다.
- **SPEC-AI-043** (전제): 급등예측은 예측 기록 모드(매수/청산 비활성)다. 본 SPEC은 이 모드를
  유지하며 매매 로직을 다루지 않는다.

## Context / Problem

이번 세션에 오케스트레이터가 `surge_detector_contribution` 테이블을 직접 조회하여, 관측된 모든
`run_date`(2026-07-20 ~ 2026-07-27)에서 `momentum_continuation`과 (거의 항상 함께)
`volume_breakout`/`theme_cluster`가 `emission_count > 0`이면서 `solo_tp = 0`임을 확인했다:

| run_date | momentum_continuation emission_count | momentum_continuation solo_tp |
|----------|--------------------------------------|--------------------------------|
| 07-20 | 1 | 0 |
| 07-21 | 1 | 0 |
| 07-22 | 2 | 0 |
| 07-24 | 5 | 0 |
| 07-27 | 2 | 0 |

같은 기간 일별 종합 평가(`surge_prediction_evaluation`)도 recall이 거의 매일 0%에 가깝다(예:
07-27 `predicted_count=7`, `actual_surge_count=38`, `true_positive=0`). 이 데이터는 이번 세션
오케스트레이터의 직접 조회 결과이며, 본 SPEC 작성 과정에서 재실행·독립 검증되지 않았다 —
plan-audit/run-phase에서 동일 쿼리 재현이 필요하다(§Requirements REQ-AI090-001 참고).

### 아직 분리되지 않은 가설 (근본원인 미확정)

"전일 크게 움직인 종목이 익일에도 계속 움직인다"는 연속성 가설이, 현재 파라미터·게이팅
기준으로 이 종목 유니버스·평가 방법론에서 실증적으로 성립하지 않는 것으로 보이지만, 다음 중
무엇이 원인인지 아직 분리되지 않았다:

1. **평가 기준 부적합 가설**: `solo_tp` 판정에 쓰이는 "scannable 실제급등"(`was_surge>=10%`
   **그리고** 유니버스 소속)이라는 바(bar)가, "새로 발견"(first-discovery) 유형 탐지기와
   "연속/이월"(continuation) 유형 탐지기에 동일하게 적용되고 있다. 연속성 주장은 "어제 5~15%
   또는 15~29.99% 움직인 종목이 오늘도 10%+ 신규 급등을 낸다"는 훨씬 강한 주장이 아니라
   "어제 오른 만큼 유지하거나 소폭 추가 상승한다"는 약한 주장일 수 있는데, 현재 평가는 후자를
   구분해 채점하지 않는다.
2. **범위/파라미터 miscalibration 가설**: `momentum_continuation`의 `[5,15)`% 범위,
   `near_limit_up_carry`의 `[15,29.99]`% 범위, 또는 confidence 스코어링 곡선 자체가 이
   유니버스·시기에 부적합할 수 있다.
3. **앙상블 편입 비중 가설**: `momentum_continuation`의 앙상블 가중치(`0.12`)가 실증된 적중률
   대비 과대·과소할 수 있다(단, `near_limit_up_carry`는 애초에 앙상블에 편입되지 않으므로
   이 가설이 적용되지 않는다 — §선행 SPEC 참고).
4. **시장/기간 가설**: 연속성 효과 자체가 이 시장·구간에서 관측되지 않을 수 있다.

본 SPEC은 위 4개 가설 중 **가설 1**을 측정으로 검증 가능하게 만드는 것에 좁게 집중한다.
가설 2/3/4는 가설 1의 측정 결과가 나온 뒤에야 유의미하게 판단 가능하며, 본 SPEC의 plan-phase
범위 밖이다.

### Goal

이 SPEC은 파라미터·가중치·평가 로직을 **변경하지 않는다.** 대신:

1. `momentum_continuation`/`near_limit_up_carry`의 solo-attributed 시그널에 대해, 기존
   `was_surge(>=10%)` 바 외에 "연속성에 적합한" 대안 성공 기준을 **최소 2가지** 정의하고
   (예: "T당일 change_rate가 음수로 반전하지 않았다" / "시그널 시점 가격 대비 T당일 추가로
   +X% 이상 상승했다"), 표본 거래일에 대해 기존 기준과 대안 기준 각각으로 재채점한 hit-rate를
   병렬로 산출한다.
2. 이 결과를 사용자에게 보고하고, (a) 대안 기준을 두 탐지기의 기여도 평가에 채택할지,
   (b) `momentum_continuation` 앙상블 가중치를 조정할지(near_limit_up_carry는 해당 없음 —
   confidence 공식/임계 조정이 대안), (c) 추가 조치 없이 현행 유지할지를 결정 게이트(M2)에서
   재확인받는다.
3. M2에서 승인된 조정만 후속 SPEC(또는 본 SPEC의 후속 마일스톤, M2에서 함께 결정)에서
   구현한다. 가중치·공식·임계값 변경 자체는 본 SPEC의 plan-phase 범위 밖이다.

### Run-phase 범위 (Implementation Kickoff Approval의 적용 범위)

**본 SPEC의 run-phase 실행 범위는 M1(측정 스파이크)로 한정된다.** Implementation Kickoff
Approval은 M1(측정 계측 구현 + 표본 재채점 + 리포트 산출) 실행만을 승인한다. M2(대안 기준
채택 여부 및 조정 방향 결정)는 M1 완료 후에만 존재하는 별도의 AskUserQuestion 라운드이며,
본 SPEC의 Implementation Kickoff Approval에 의해 사전 승인되지 않는다. M1 완료 + 측정
리포트 제출만으로 본 SPEC은 유효하게 완료되며, 조정 없이 완료되는 것이 valid한 결과다.

## Requirements (GEARS)

### REQ-AI090-001 (Ubiquitous, P0) — 기존 관측치 재현 검증

The system **shall** run-phase 진입 전, §Context에 인용된 관측치를 표본 거래일에 대해
재조회하여 재현 여부를 확인하고, 그 결과(재현/불일치 포함)를 M1 리포트에 원본 쿼리·출력과
함께 기록한다. 재현되지 않는 경우 본 SPEC의 §Context 전제가 무효화될 수 있으므로, 그 사실
자체를 리포트에 명시하고 M1의 나머지 단계 진행 여부는 M1 리포트 시점에 재판단한다.
> 구현 참고: 대상 테이블은 `surge_detector_contribution`(`run_date`, `detector`,
> `emission_count`, `solo_count`, `solo_tp`)과 `surge_prediction_evaluation`
> (`predicted_count`, `actual_surge_count`, `true_positive`). 이 검증은 §Context에 나열된
> `run_date` 값들(2026-07-20~2026-07-27) 중 데이터가 남아있는 만큼을 대상으로 한다(5일 보존
> 정책상 일부는 이미 소실됐을 수 있다 — `.moai/memory` 급등예측 미탐 근본원인 disclosure flat
> scoring 기록 참고).

### REQ-AI090-002 (Ubiquitous, P0) — 연속성 적합 대안 성공 기준 정의

The system **shall** 다음 두 가지 대안 성공 기준을 정의하고, 각 기준의 판정 로직을 순수
함수로 문서화한다:

- **기준 B ("미반전", floor 기준)**: 시그널의 근거가 된 T-1 변화율이 양수였던 종목에 대해,
  T당일 변화율이 사전 정의된 하한(기본 후보값 `0.0`%, 즉 "전일 상승분을 당일 마이너스로
  반납하지 않음") 이상인 경우를 성공으로 판정한다.
- **기준 C ("추가 상승", incremental-gain 기준)**: T당일 변화율이 사전 정의된 임계(기본
  후보값 `+3.0%`와 `+5.0%` 두 가지를 모두 산출) 이상인 경우를 성공으로 판정한다 — 기존
  `was_surge`(`>=10.0%`)보다 완화된 바(bar)다.

**IF** 기준 B/C 계산에 필요한 T당일 관측치가 해당 종목·날짜에 존재하지 않으면,
**THEN** the system **shall** 그 종목을 두 기준 모두에서 "측정불가"로 분류하고 분모에서
제외하며(0으로 간주하지 않음), 측정불가 건수를 리포트에 별도 집계한다.
> 구현 참고: T-1 변화율은 momentum_continuation의 경우 `SurgeActualOutcome.change_rate`,
> near_limit_up_carry의 경우 `surge_metadata.yesterday_change_pct`를 사용하며, T당일 변화율은
> 두 탐지기 모두 `SurgeActualOutcome.change_rate`를 사용한다. 기준 B/C 모두 REQ-001의 두 테이블
> 외에 신규 데이터 수집을 요구하지 않는다 —
> `SurgeActualOutcome`은 T-1/T 양쪽 날짜에 대해 이미 매일 수집되는 테이블이다
> (`surge_actual_outcome_service.py`).

### REQ-AI090-003 (Event-driven, P0) — solo-attributed 시그널 재채점

**When** REQ-002에서 정의한 기준이 확정되면, the system **shall**
`momentum_continuation`/`near_limit_up_carry` 각각에 대해, `evaluate_detector_contribution()`
과 동일한 attribution 방식(T-1 `surge_basis == [해당 탐지기]`인 solo 시그널 집합)으로 표본
거래일의 solo 시그널을 식별하고, 각 시그널을 (a) 기존 `was_surge`(scannable) 기준, (b) 기준
B, (c) 기준 C(두 임계값) 4가지로 병렬 재채점하여 탐지기별·기준별 hit-rate를 산출한다.
> 구현 참고: attribution 로직은 `_compute_detector_metrics`
> (`surge_contribution_service.py`)의 solo 판별 방식을 참고하되, 신규 함수는 기존 함수를
> 호출·수정하지 않고 별도 모듈에서 동일 로직을 재현하는 읽기 전용 파생 계산으로 구현한다
> (기존 `surge_detector_contribution` 테이블 upsert 경로와 완전히 분리).

### REQ-AI090-004 (State-driven, P0) — 탐지 로직·평가 파이프라인 무영향 불변식 [HARD]

**While** 본 SPEC의 측정(REQ-001~003)이 실행되는 동안, the system **shall NOT** 다음을
어떤 방식으로도 변경한다:

- `detect_momentum_continuation()`/`detect_near_limit_up_carries()`의 후보 선정 범위,
  confidence 공식, BEAR 감쇠, 활성화 플래그.
- `compute_ensemble_score()`의 가중치(`momentum_continuation: 0.12` 포함) 및
  `SurgeDetectionConfig.ensemble.weights` 합=1.0 불변식.
- `evaluate_detector_contribution()`/`surge_detector_contribution` 테이블의 기존
  `was_surge`/`scannable` 기반 집계 정의·upsert 경로(REQ-002/003의 대안 기준 계산은 별도
  파생 경로이며 기존 테이블에 쓰지 않는다).
- `SurgeActualOutcome`/`SurgeUniverseMember` 등 기존 테이블 스키마 및 그 값.

### REQ-AI090-005 (Event-driven, P1) — 결정 게이트 산출물

**When** M1 측정이 완료된 것이 감지되면, the system **shall** REQ-001~003의 결과를 단일 리포트
(재현 검증 결과, 탐지기별·기준별 hit-rate 비교표, 측정불가 건수, 표본 거래일 목록 포함)로
통합하여 사용자에게 제시하며, M2 결정 게이트(대안 기준 채택 여부·조정 방향 선택 또는 현행
유지 결정)를 통과하기 전까지 어떠한 탐지 로직·가중치·평가 정의 변경도 진행하지 아니한다.
> 구현 참고: M2는 orchestrator의 AskUserQuestion을 통한 human 결정 지점이다 —
> `.claude/rules/moai/core/askuser-protocol.md` § Report-Before-Ask Gate 준수. 리포트 옵션은
> `momentum_continuation`(앙상블 가중치 레버 존재)과 `near_limit_up_carry`(confidence 공식/
> 임계 레버만 존재, 앙상블 가중치 레버 없음)를 별도로 구분하여 제시한다(§선행 SPEC의
> standalone_bypass 분류 반영).

### REQ-AI090-006 (Where, P2) — 관측성

**Where** 로깅이 유효한 경우, the system **shall** 측정 실행 여부·표본 거래일 수·기준별
hit-rate 요약을 단일 로그 라인으로 기록하며, 신규 DB 스키마를 도입하지 아니하고 종목별
상세 로그를 영구 저장 테이블에 남기지 아니한다(리포트 파일에는 종목별 상세를 포함할 수 있다).

## Acceptance Criteria (인라인, Tier S)

### AC-090-001 (REQ-001) — 재현 검증 리포트 존재

**When** REQ-001의 재조회가 실행되면, the system **shall** M1 리포트에 §Context 표의 각
`run_date`에 대한 실제 재조회 결과를 원본 쿼리와 함께 기록하고, 재현 여부(일치/불일치)를
명시적으로 판정한다.

**재현 시나리오(비규범)**:
**Given** M1 실행 환경에서 프로덕션(또는 동등한 최신 스냅샷) DB 접근이 가능하다
**When** REQ-001의 재조회를 수행한다
**Then** M1 리포트에 §Context 표의 각 `run_date`에 대한 실제 재조회 결과가 원본 쿼리와 함께
기록되고, 재현 여부(일치/불일치)가 명시적으로 판정되어 있다.

### AC-090-002 (REQ-002) — 대안 기준 정의의 재현성

**When** 기준 B/C 판정 함수에 임의의 T-1 변화율 값과 T당일 변화율 값 쌍이 입력되면, the
system **shall** 동일 입력에 대해 항상 동일한 성공/실패/측정불가 판정을 반환하며(순수
함수), 판정 로직 코드에 두 기준의 임계값(0.0% / +3.0% / +5.0%)을 하드코딩이 아닌 명명된
상수로 포함한다.

**재현 시나리오(비규범)**:
**Given** 임의의 T-1 change_rate 값과 T당일 `SurgeActualOutcome.change_rate` 값 쌍
**When** 기준 B/C 판정 함수에 입력한다
**Then** 동일 입력에 대해 항상 동일한 성공/실패/측정불가 판정을 반환하며(순수 함수), 판정
로직 코드에 두 기준의 임계값(0.0% / +3.0% / +5.0%)이 하드코딩이 아닌 명명된 상수로 존재한다.

### AC-090-003 (REQ-003) — 4-기준 병렬 hit-rate 산출

**When** REQ-003의 재채점이 표본 거래일(§Requirements REQ-001에서 재현 확인된 날짜 중
`solo_count > 0`인 날짜, 최소 3일 이상)의 solo 시그널 집합에 대해 실행되면, the system
**shall** 탐지기별로 (기존 was_surge, 기준 B, 기준 C@+3%, 기준 C@+5%) 4개 hit-rate 값을
산출하고, 측정불가로 분류된 건수를 분모에서 제외하여 리포트에 명시한다.

**재현 시나리오(비규범)**:
**Given** 표본 거래일(§Requirements REQ-001에서 재현 확인된 날짜 중 `solo_count > 0`인 날짜,
최소 3일 이상)의 `momentum_continuation`/`near_limit_up_carry` solo 시그널 집합
**When** REQ-003의 재채점을 실행한다
**Then** 탐지기별로 (기존 was_surge, 기준 B, 기준 C@+3%, 기준 C@+5%) 4개 hit-rate 값이
모두 산출되며, 측정불가로 분류된 건수가 분모에서 제외되어 있음이 리포트에서 확인 가능하다.

### AC-090-004 (REQ-004, HARD) — 무영향 불변식 회귀 테스트

**While** 본 SPEC 적용 전/후의 `detect_momentum_continuation`/`detect_near_limit_up_carries`/
`compute_ensemble_score`/`evaluate_detector_contribution` 관련 기존 테스트 스위트가
재실행되는 동안, the system **shall NOT** 기존 테스트 결과(pass/fail 목록)를 변경하거나
`surge_detection.yaml` 가중치 값과 `surge_detector_contribution` 테이블 upsert 로직에 diff를
발생시킨다.

**재현 시나리오(비규범)**:
**Given** 본 SPEC 적용 전/후의 `detect_momentum_continuation`/`detect_near_limit_up_carries`/
`compute_ensemble_score`/`evaluate_detector_contribution` 관련 기존 테스트 스위트
**When** 전체 스위트를 재실행한다
**Then** 기존 테스트 결과(pass/fail 목록)가 바이트 동등하며, `surge_detection.yaml`
가중치 값과 `surge_detector_contribution` 테이블 upsert 로직에 diff가 없다.

### AC-090-005 (REQ-005) — M2 없이 M3+ 진행 금지

**When** M1 리포트가 사용자에게 제시되고 M2 AskUserQuestion 라운드가 아직 진행되지 않은
상태이면, the system **shall NOT** 어떤 탐지기 파라미터·앙상블 가중치·평가 정의 변경
커밋도 생성한다.

**재현 시나리오(비규범)**:
**Given** M1 리포트가 사용자에게 제시된 상태
**When** M2 AskUserQuestion 라운드가 아직 진행되지 않았다
**Then** 어떤 탐지기 파라미터·앙상블 가중치·평가 정의 변경 커밋도 존재하지 않는다(M1
완료 커밋만 존재).

### AC-090-006 (REQ-006) — 로깅 및 스키마 무변경

**Where** 로깅이 유효한 경우, the system **shall** M1 실행 완료 후 측정 실행 여부·표본
수·기준별 hit-rate 요약을 단일 로그 라인에 기록하며, `alembic`/마이그레이션 diff를
발생시키지 아니한다.

**재현 시나리오(비규범)**:
**Given** M1 실행 완료 후 로그
**When** 로그를 확인한다
**Then** 측정 실행 여부·표본 수·기준별 hit-rate 요약이 단일 로그 라인에 포함되어 있고,
`alembic`/마이그레이션 diff가 0이다.

## Out of Scope (What NOT to Build)

### Out of Scope — 가중치/공식/임계값 변경 자체 (M2 결정 이전)

- 본 SPEC의 M1은 **측정 전용**이다. M2 사용자 승인 없이 `momentum_continuation`의 앙상블
  가중치(`0.12`), `near_limit_up_carry`의 confidence 공식(`change_rate/30.0*0.5`)이나 임계
  범위(`near_limit_up_min_pct`/`max_pct`), 두 탐지기의 후보 선정 범위(`[5,15)`%/`[15,29.99]`%)
  중 어느 것도 수정하지 않는다.
- M2 승인이 없으면 본 SPEC은 측정 리포트 산출로 완료된다.

### Out of Scope — 가설 2/3/4 (miscalibration / 앙상블 비중 / 시장·기간)

- §Context에서 나열한 4개 가설 중 가설 1(평가 기준 부적합)만 측정한다.
- 가설 2(범위/파라미터 miscalibration), 가설 3(앙상블 편입 비중), 가설 4(시장/기간 효과
  부재)의 직접 검증은 본 SPEC의 범위 밖이며, M2 결정 결과에 따라 별도 후속 SPEC 후보로 남긴다.

### Out of Scope — `evaluate_detector_contribution()`/기존 집계 정의 변경

- `surge_detector_contribution` 테이블의 `solo_tp`/`coincident_hit_rate` 등 기존 필드가
  표상하는 "scannable(`was_surge` AND 유니버스 소속)" 정의는 변경하지 않는다.
- REQ-002/003의 대안 기준은 완전히 별도의 읽기 전용 파생 계산이며, 기존 테이블에 쓰지 않고
  기존 집계를 대체하지 않는다.

### Out of Scope — 매매 실행

- SPEC-AI-043 예측기록모드(매수/청산 비활성)를 유지한다.
- 본 SPEC은 측정에만 관여하며 `SurgePortfolio`/`SurgeTrade` 실행 로직을 다루지 않는다.

### Out of Scope — 다른 탐지기

- `theme_cluster`/`volume_breakout` 등 §Context에서 함께 언급된 다른 solo_tp=0 탐지기는 본
  SPEC의 측정 대상이 아니다 — 이들은 "새로 발견"(first-discovery) 유형이라 §Context 가설 1
  (연속성 평가 기준 부적합)이 적용되지 않는다.
- 이들의 solo_tp=0 원인은 별도 조사가 필요하며 본 SPEC의 범위 밖이다.

### Out of Scope — 과거 데이터 백필/재채점 영속화

- REQ-002/003의 재채점 결과를 과거 `FundSignal`/`surge_detector_contribution` 행에 백필하거나
  영구 저장하지 않는다(리포트 파일에만 기록).
- 신규 DB 마이그레이션은 요구되지 않는다.

## Ownership

- **본 SPEC**: 연속성 계열 탐지기 평가 기준 대안 측정(REQ-001~003) + 결정 게이트 산출물
  (REQ-005) + M2 승인 시 후속 SPEC 분리 여부 결정(REQ-005의 일부).
- **SPEC-AI-065**: `momentum_continuation` 탐지기 본체(후보 범위, 점수 공식, 앙상블 가중치
  키) 소유자 — 본 SPEC은 읽기 전용으로 그 산출물(solo 시그널, `surge_metadata`)만 소비한다.
- **SPEC-AI-023/072/077**: `near_limit_up_carry` 탐지기 본체 소유자 — 동일하게 무변경.
- **SPEC-AI-070**: `evaluate_detector_contribution()`/`surge_detector_contribution` 테이블
  소유자 — 본 SPEC의 대안 재채점은 이 소유권을 침범하지 않는 별도 파생 경로다.
