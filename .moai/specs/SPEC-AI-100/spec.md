---
id: SPEC-AI-100
title: "급등예측 스코어링 아키텍처: 탐지기 지평(horizon) 분리"
version: "0.1.0"
status: in-progress
created: 2026-08-03
updated: 2026-08-03
author: Nexsol
priority: High
phase: "backend surge-detection v0.1.0"
module: "backend/app/services"
lifecycle: spec-anchored
tags: "surge-detection, scoring-architecture, horizon-separation, ensemble, backend"
tier: L
related_specs: [SPEC-AI-096, SPEC-AI-097, SPEC-AI-098, SPEC-AI-099, SPEC-AI-012, SPEC-AI-017, SPEC-AI-018, SPEC-AI-030, SPEC-AI-066, SPEC-AI-075, SPEC-AI-083, SPEC-AI-092]
---

# SPEC-AI-100: 급등예측 스코어링 아키텍처: 탐지기 지평(horizon) 분리

## HISTORY

- 2026-08-03 v0.1.0 (draft): 급등예측 앙상블이 서로 다른 예측 지평(당일 즉시 발화,
  48시간 뉴스 윈도우, 전일 T-1 가격 모멘텀, 당일 장중 이벤트)을 가진 탐지기를 단일
  가중합 + 단일 레짐별 임계값으로 게이팅하는 문제를 범위로 정의한다. 평가 계층
  (SPEC-AI-075/080/083)은 이미 same-day 시그널을 표준 T-1→T 정확도 지표에서 별도
  분리했으나, 스코어링/게이팅 아키텍처 자체(하나의 앙상블 함수, 하나의 점수, 하나의
  임계값 집합)는 무수정이었다. 본 SPEC은 5-SPEC Epic(스캔 유니버스 SPEC-AI-096,
  배치 시세 SPEC-AI-097, 뉴스-종목 매칭 SPEC-AI-098, 피처 스냅샷 SPEC-AI-099가 이미
  plan-phase 완료 상태로 의도적으로 이 아키텍처 질문을 본 SPEC에 이월함)에서 가장
  아키텍처적으로 근본적인 조각이다. research.md에서 위임 프롬프트의 "SPEC-AI-083이
  event_rescan을 이미 구현했다"는 서술이 부분적으로 부정확함(SPEC-AI-066이 최초
  구현, SPEC-AI-083이 활성화·확장)을 코드 대조로 확인해 정정했고, "8개 탐지기 모두
  라이브 매매 시그널에 기여한다"는 위임 프롬프트의 암묵적 전제가 틀렸음(weekend_gap_up,
  bollinger_squeeze는 완전한 고아 탐지기)을 신규 발견해 §Decisions D5에 반영했다.
- 2026-08-03 v0.1.0 (draft, 1차 개정): plan-auditor 1차 감사(iteration 1) FAIL
  판정을 시정했다. (D1) REQ-AI100-004와 AC-100-005가 동일 단일 행위(Gate 4
  판정 로직 변경)에 `**shall**`과 `**shall not**`을 동시에 볼드 처리한
  자기모순적 이중 modal이었던 GEARS 형식 위반(Must-Pass MP-2)을 두 개의 독립된
  GEARS 문장으로 분리해 수정했다(acceptance.md는 AC-100-005a/AC-100-005b로
  분리). (D2) 섀도우 모드 → 프로덕션 전환 게이트가 "이상 징후 관찰" 수준의
  개방형 판단 기준에 그친다는 지적(Must-Pass는 아니나 2026-07-28
  `theme_news_carry` 자기강화 피드백 루프 사고 이력과 직결)을 반영해
  REQ-AI100-009/AC-100-011(전환 게이트 구조적 최소 요건 3가지)을 신설했다.

## 선행 SPEC

- **SPEC-AI-012/017/018**: `compute_ensemble_score()`의 가중합 공식, 레짐별 임계값,
  컨센서스 배율, 우회(bypass) 임계값의 소유 SPEC. 본 SPEC은 이 가중합 수식 자체를
  전혀 수정하지 않는다 — design.md §E에서 결정했듯, 기존 가중합·컨센서스 배율 로직
  위에 지평 인식 임계값 선택 단계만 추가한다.
- **SPEC-AI-030**: `combo_chase_guard` Gate 4(REQ-AI030-004) — combo 단독 신호
  buy-pool 배제의 소유 SPEC. 본 SPEC은 이 게이트의 판정 로직을 무수정으로 유지하며,
  평가 순서(게이트 실행 → 지평 시그니처 계산 → 임계값 선택)만 명문화한다
  (design.md §F).
- **SPEC-AI-066**: `_maybe_trigger_event_rescan()`(고임팩트 뉴스 이벤트 구동 재스캔)의
  최초 구현 소유 SPEC(research.md §1-6에서 위임 프롬프트의 SPEC-AI-083 귀속을 정정).
  본 SPEC은 이 재스캔 메커니즘을 무수정으로 유지하며 소비하지 않는다 — 스코어링
  아키텍처와는 독립적인 관심사다.
- **SPEC-AI-075/080/083**: 평가 계층의 same-day 지평 분리(`_is_same_day_event_horizon_signal`,
  `surge_metadata.horizon` 필드) 및 SPEC-AI-083의 재스캔 활성화·확장의 소유 SPEC.
  본 SPEC은 이 평가 계층 로직을 재구현하지 않는다 — 그 위에 구축하며, `horizon`
  필드 개념을 일반화한다(현재는 즉각 공시 탐지기 1개 경로에만 존재, design.md §B
  옵션 (b)).
- **SPEC-AI-092**: 예측 생성 게이트(`effective_threshold`)와 매수 실행 게이트
  (`surge_threshold_service`)의 명명·로그 분리 확정 SPEC. 본 SPEC은 이 분리를
  유지하며 두 게이트를 병합하지 않는다(design.md §G).
- **SPEC-AI-096/097/098/099**: 이번 배치의 형제 SPEC — 스캔 유니버스 확장, 배치
  시세 조회, 뉴스-종목 매칭 경계, 피처 스냅샷 인프라. 본 SPEC은 이들의 구현을
  전제하지 않으나, SPEC-AI-099의 피처 스냅샷이 완료되면 본 SPEC의 사후 검증
  (plan.md §D)이 섀도우 모드에서 스냅샷 기반 백테스트로 강화될 수 있다(연구
  참고, research.md §6).

### amendment 여부

본 SPEC은 어떤 선행 SPEC의 amendment도 아니다. `amendment_of:` 없이
`related_specs`로만 참조하는 통상적 신규 SPEC이다.

## Context / Problem

### 문제 1 — 이질적 지평의 탐지기 점수가 단일 가중합으로 결합된다

`surge_detector.py:1538-1608`(`compute_ensemble_score`)는 `theme_cluster_score`(48시간
뉴스 윈도우 스캔), `combo_score`, `best_disclosure_score`(당일/즉시 공시 반응),
`legacy_score`, `news_delayed_score`(24-72h 지연 반응), `volume_breakout_score`(당일
장중 거래량), `momentum_continuation_score`(전일 T-1 등락률 5-15% 기반) 7개 항을
`config.ensemble.weights`의 고정 가중치로 곱해 합산한 뒤, 활성 탐지기 그룹 수 기반
컨센서스 배율(1.00/1.30/1.55)을 곱한다. 메인 루프(2192-2199행)는 이 단일 점수를
`effective_threshold`(레짐별 고정값, 2184-2186행) 하나와 비교해 게이팅한다. 이 값들은
SPEC-AI-017/018/039/050/065를 거치며 사람이 손으로 재조정한 이력이 코드 주석에
그대로 남아 있다.

### 문제 2 — 탐지기들은 실제로 서로 다른 예측 지평을 갖는다

theme_cluster(48시간 뉴스 윈도우), disclosure_pattern(당일/즉시 공시), 
momentum_continuation(전일 가격 행동), volume_breakout/near_limit_up_carry(당일 장중)는
근본적으로 다른 시간축의 신호다. 그럼에도 이들은 동일 가중치·동일 임계값 집합으로
게이팅된다. 평가 계층(`surge_evaluation_service.py:506-524`
`_is_same_day_event_horizon_signal`, 738-762행)은 이미 same-day 지평 시그널을 표준
T-1→T 정확도 지표에서 별도 서브지표로 분리했으나 — 이는 사후 **측정** 방식을 바꿨을
뿐, 후보가 **생성/게이팅되는 시점**의 스코어링·임계값 로직은 전혀 변경하지 않았다.

### 문제 3 — 기존 `horizon` 메타데이터 필드는 좁은 개념으로만 존재한다

`disclosure_impact_scorer.py:466`(`_classify_disclosure_horizon`)이 설정하는
`horizon`(`same_day`/`next_day`) 필드는 **즉각 공시 탐지기 1개 경로에서만** 존재한다
(research.md §2-4). theme_cluster, momentum_continuation, volume_breakout 등 나머지
6개 라이브 탐지기는 이 필드를 전혀 설정하지 않는다. 즉 "탐지기 지평 taxonomy"라는
일반 개념은 아직 코드베이스에 존재하지 않으며, 본 SPEC이 설계하는 것은 이 좁은 개념의
**일반화**다.

### 문제 4 — `surge_threshold_service`의 적응형 임계값은 매수 실행 전용이며 예측 생성
게이트와 무관하다

`surge_threshold_service.py` 모듈 docstring이 명시한다: 이 서비스가 산출하는 적응형
임계값은 매수 실행 게이트(`surge_trading_service.execute_buy_orders()`) 전용이며,
예측 생성 게이트(`gather_surge_candidates()`의 `effective_threshold`)와는 완전히
독립적이다(SPEC-AI-092로 확정). 본 SPEC이 지평 인식 임계값 체계를 도입할 때, 이
독립성을 유지할지 재고할지 결정이 필요하다.

### 문제 5 — `combo_chase_guard`는 지평 무관 단일 게이트이며, 이미 서로 다른 지평의
탐지기를 corroboration 신호로 혼용한다

`surge_detector.py:2158-2174`(Gate 4)는 `combo_score > 0`이고 `theme_cluster_score`/
`immediate_disclosure_score`/`pattern_score`가 모두 0이면 후보를 완전히 제거한다.
이 companion 조건은 이미 48시간 지평(theme_cluster)과 당일 지평(immediate_disclosure)
을 동등한 corroboration 신호로 취급한다 — 지평 분리 아키텍처 도입이 이 게이트를
어떻게 다뤄야 하는지 명시적 결정이 필요하다.

### 문제 6 — 8개 명목상 탐지기 중 2개는 라이브 파이프라인에 전혀 배선되지 않았다
(신규 발견)

research.md §2-1/§2-2가 코드 대조로 확인했다: `weekend_gap_up` 탐지기는 후보를
계산하지만 `fund_manager.py:4112-4113` 주석이 명시하듯 "FundSignal 미생성 — 앙상블
외부 커버리지 정보"이며, `bollinger_squeeze` 탐지기는 `scheduler.py`의 독립된 잡에서
실행되어 결과를 로그로만 남기고 폐기한다(`fund_manager.py` 전체에서 호출 0건). 이
두 탐지기의 가중치(`weekend_gap_up: 0.08`)와 스코어 필드(`squeeze_score`)는 config와
데이터클래스에 존재하나 `compute_ensemble_score`의 실제 계산에는 전혀 사용되지 않는다.
지평 분리 아키텍처를 설계할 때 이 고아 탐지기들의 처리 범위를 명시적으로 결정해야
한다.

## Goals

1. 탐지기의 예측 지평(당일 vs 다일)을 명시적으로 분류하고, 이 분류를 스코어링/게이팅
   아키텍처에 반영하는 방식을 최소 2개 설계 옵션으로 평가한 뒤 하나를 선택한다
   (design.md §B-E).
2. `combo_chase_guard`의 companion-detector 요구사항이 지평 인식 아키텍처 도입
   이후에도 단일 전역 게이트로 유지될지, 지평별 변형이 필요한지 결정한다
   (design.md §F).
3. 지평 인식 임계값 체계와 `surge_threshold_service`의 적응형 임계값(매수 실행
   전용)의 관계를 정의한다 — 통합할지 독립 유지할지(design.md §G).
4. 마이그레이션/롤아웃 계획을 정의한다 — 기존 평가 지표(SPEC-AI-095 `high_based_*`,
   표준 T-1→T recall/precision) 대비 신규 아키텍처를 완전 전환 전에 어떻게
   검증할지, 롤백 경로는 무엇인지(design.md §I-J).
5. 고아 탐지기(weekend_gap_up, bollinger_squeeze) 배선 여부를 본 SPEC 범위에
   포함할지 명시적으로 결정한다(design.md §H).
6. 형제 SPEC(SPEC-AI-096 유니버스 커버리지, SPEC-AI-099 피처 스냅샷)이 더 많고
   더 잘 라벨링된 후보를 생산하게 될 것이라는 의존 관계를 plan.md에 명시한다 —
   구현하지는 않되 인터페이스 가정만 기록한다.

## Non-Goals

### Out of Scope — 모델 학습/서빙

- **어떤 형태의 실제 모델 학습, 평가, 서빙도 포함하지 않는다**: 학습된 분류기/랭커
  도입은 이 Epic에서 사용자 결정으로 배제되었다 — 본 SPEC은 규칙 기반/수동 튜닝
  스코어링 아키텍처의 재설계만 다룬다.

### Out of Scope — 탐지기 신규 배선

- **`weekend_gap_up`, `bollinger_squeeze`를 라이브 파이프라인(앙상블/FundSignal)에
  신규 배선하는 작업**: design.md §H에 따라 별도 SPEC 대상으로 이월한다. 본 SPEC의
  지평 시그니처 메커니즘은 이들을 향후 편입 가능하도록 확장 가능하게 설계하되,
  실제 배선은 하지 않는다.

### Out of Scope — 평가 계층 재구현

- **SPEC-AI-075/080/083의 same-day 지평 배제 로직(`_is_same_day_event_horizon_signal`)
  재구현 금지**: 그 위에 구축하며, `horizon` 필드 개념을 일반화할 뿐 기존 평가
  로직 자체를 변경하지 않는다.
- **SPEC-AI-083의 `event_rescan` 재스캔 메커니즘 재구현 금지**: 무수정으로 유지하며
  소비하지 않는다.

### Out of Scope — 이번 배치 형제 SPEC 영역

- **스캔 유니버스(Pool A/B/C/D) 구성 변경**: SPEC-AI-096 대상이다.
- **배치 시세 조회 최적화**: SPEC-AI-097 대상이다.
- **뉴스-종목 매칭 경계 가드**: SPEC-AI-098 대상이다.
- **피처 스냅샷 데이터 인프라**: SPEC-AI-099 대상이다.

### Out of Scope — 구체적 임계값 수치 확정

- **신규 지평별 임계값의 정확한 숫자(예: same_day BULL=?, next_day BULL=?) 확정**:
  기존 `regime_thresholds`(BULL=0.38 등)는 현재의 혼합 지평 가중합을 전제로
  튜닝되었으므로 그대로 재사용할 수 없다 — 섀도우 모드 관찰 후 확정한다(Open
  Question 2).

## Decisions

design.md에서 이미 상세 분석을 완료했다. 이 절은 결정 사항만 요약하고, 근거는
design.md의 해당 절을 참조한다.

### D1 — 옵션 (b) 지평 태깅형 단일 파이프라인을 채택한다, 완전 분리형(옵션 a)은
기각한다

design.md §B-E 전체가 근거다. 요약: `compute_ensemble_score`의 가중합·컨센서스
배율 수식은 무수정 유지하고, (1) 탐지기별 지평 라벨 신규 설정(`ensemble.horizon_labels`),
(2) 기존 `detector_groups`/`active_groups` 메커니즘을 확장한 후보별 지평 시그니처
계산, (3) 레짐 × 지평 시그니처 2축 임계값 선택으로 `effective_threshold` 조회를
확장한다.

기각한 대안 — 옵션 (a) 완전 분리형(지평별 독립 가중치 세트 + 독립 임계값 세트).
5개 SPEC(017/018/039/050/065)의 수동 튜닝 이력을 무효화하고, 한 종목이 여러 지평의
시그널을 동시에 받을 때의 병합/중복제거 로직을 새로 발명해야 하며, 섀도우 모드
검증이 구조적으로 더 무겁다는 이유로 기각한다(design.md §C 트레이드오프 표).

### D2 — `combo_chase_guard`(Gate 4)의 판정 로직은 무수정 유지한다, 평가 순서만
명문화한다

design.md §F. Gate 4는 이미 서로 다른 지평의 탐지기를 지평 무관 corroboration
신호로 취급하도록 설계되어 있으며, 이는 지평 분리 아키텍처 도입으로 바뀔 이유가
없는 설계 의도로 판단한다. 게이트 실행(merged에서 제거) → 지평 시그니처 계산 →
임계값 선택의 순서를 REQ로 명문화한다.

기각한 대안 — Gate 4를 지평별 변형(same_day 전용 컴패니언 조건, next_day 전용
컴패니언 조건)으로 분기. 현재 코드에 이런 분기가 필요하다는 증거(예: 서로 다른
지평 간 상쇄 관계)가 발견되지 않아 불필요한 복잡도로 판단해 기각한다.

### D3 — `surge_threshold_service`(매수 실행 전용)와 신규 지평 인식 예측 생성
임계값은 독립 유지한다

design.md §G. SPEC-AI-092가 이미 확정한 "예측 생성 게이트 vs 매수 실행 게이트"
분리를 유지하며, 지평 인식 임계값은 전적으로 예측 생성 게이트 측 확장이다.

기각한 대안 — 두 임계값 체계 통합. SPEC-AI-092가 이미 명명·로그 분리까지 확정한
설계 결정을 되돌릴 근거가 없어 기각한다.

### D4 — 고아 탐지기(weekend_gap_up, bollinger_squeeze) 배선은 본 SPEC 범위에서
명시적으로 제외한다

design.md §H. 지평 시그니처 메커니즘은 확장 가능하게 설계하되(향후
`ensemble.horizon_labels`에 항목만 추가하면 편입 가능), 실제 배선은 별도
엔지니어링 과제로 이월한다.

기각한 대안 — 본 SPEC 범위에 두 탐지기 배선을 포함. Tier L SPEC의 범위를 인위적으로
확장해 검증 복잡도를 가중시킨다는 이유로 기각한다.

### D5 — 마이그레이션은 feature flag 게이팅 + 섀도우 모드 로그 비교로 진행한다,
DB 마이그레이션은 도입하지 않는다

design.md §I-K. `ensemble.horizon_aware_thresholds.enabled: false` 기본값 —
비활성 시 바이트 동일 동작(이 프로젝트의 기존 롤아웃 관례와 일치, 예:
`relative_threshold_enabled`, `theme_news_carry`). 섀도우 모드는 기존 임계값
경로와 신규 지평 인식 경로를 매 사이클 모두 계산해 qualified 집합 차이를 구조화
로그로 기록한다.

기각한 대안 — 신규 비교 전용 테이블 신설. 스키마 변경 없이 구조화 로그로 충분하다고
판단해 1단계에서는 기각하고, 필요 시 후속 SPEC의 판단으로 남긴다(Open Question).

### D6 — 섀도우 모드 → 프로덕션 전환 게이트는 구조적 최소 요건 3가지를 계획
단계에서 구속력 있게 확정한다(plan-auditor 1차 감사 반영)

REQ-AI100-009 / AC-100-011. plan-auditor 1차 감사(iteration 1)가 지적한 대로,
D5가 정의한 롤아웃 방식(feature flag + 섀도우 모드 로그 비교) 자체는 타당하나
전환 판단 기준을 "이상 징후 관찰" 수준의 개방형 서술로 남겨두면 2026-07-28
`theme_news_carry` 자기강화 피드백 루프 사고(오탐률 77% 도달 후 롤백, 유사한
규모의 스코어링 아키텍처 변경에서 발생)와 동일한 위험 패턴을 반복할 수 있다.
따라서 (1) 최소 관측 거래일 수, (2) 3개 레짐(BULL/SIDEWAYS/BEAR) 전량 관측,
(3) qualified 후보 집합 변화폭 상한을 계획 단계에서 게이트 구조로 확정한다 —
정확한 수치는 잠정값(Open Question 2, 3)이나, 게이트의 형태 자체는 확정한다.

기각한 대안 — 기존 D5의 "섀도우 모드 로그 관찰 후 판단"으로 그대로 유지. 이
대안은 개방형 판단 기준이 반복적으로 동일한 사고 패턴(사후에야 규모가 드러나는
회귀)을 재현할 위험이 있어 plan-auditor 지적을 반영해 기각한다.

## Requirements

### REQ-AI100-001: 탐지기별 지평 라벨 설정

**Where** `config.ensemble.horizon_aware_thresholds.enabled`가 활성화되어 있으면,
the system **shall** `config.ensemble.weights`의 각 탐지기 가중치 키에 대응하는
지평 라벨(`same_day` 또는 `next_day`/`multi_day`)을 신규 설정 섹션에서 조회할 수
있어야 한다. 지평 라벨이 설정되지 않은 탐지기 키가 존재하면, the system **shall**
안전한 기본값(`multi_day`, 보수적 — 기존 임계값 경로와 동일하게 취급)으로 처리해야
하며 예외를 발생시켜서는 **shall not** 안 된다.

필수 조건:

- 신규 설정 섹션은 `ensemble.weights`와 독립된 신규 필드이며, 기존 `weights` 구조
  자체는 무수정이다.
- 플래그가 비활성화된 상태에서는 이 필드를 전혀 조회하지 않는다(D5 바이트 동일
  동작 보장).

### REQ-AI100-002: 후보별 지평 시그니처 계산

**When** 앙상블 스코어링 사이클이 후보의 앙상블 점수를 계산하면(`compute_ensemble_score`
실행 직후), **Where** `horizon_aware_thresholds.enabled`가 활성화되어 있으면, the
system **shall** 그 후보에 대해 실제로 발화한 탐지기 그룹의 지평 라벨을 조합해
단일 지평 시그니처(예: `same_day_dominant`, `next_day_dominant`, `mixed`)를 산출해야
한다. 이 계산은 `compute_ensemble_score`의 `detector_groups`/`active_groups` 계산
로직을 재사용하거나 확장해야 하며, 완전히 별개의 신규 메커니즘을 발명해서는
**shall not** 안 된다.

### REQ-AI100-003: 지평 인식 임계값 선택

**When** 지평 시그니처가 산출되고 `horizon_aware_thresholds.enabled`가
활성화되어 있으면, the system **shall** 레짐과 지평 시그니처 조합으로 임계값을
조회해 기존 `effective_threshold` 단일 레짐 조회를 대체해야 한다. **While**
`horizon_aware_thresholds.enabled`가 비활성화되어 있으면, the system **shall**
기존 `effective_threshold`(레짐별 단일 표) 조회 경로만 사용해야 하며, 지평 시그니처
계산이나 신규 임계값 조회 로직을 **shall not** 실행해서는 안 된다.

필수 조건:

- `compute_ensemble_score`의 가중합·컨센서스 배율 계산 자체, 3개 bypass 루프
  (immediate_disclosure/강한 단일 신호/volume_breakout), `sector_contagion` 게이트는
  이 REQ의 구현으로 인해 **shall not** 변경되어서는 안 된다.

### REQ-AI100-004: `combo_chase_guard`(Gate 4) 평가 순서 명문화

**While** 본 SPEC이 적용되는 동안, the system **shall not** `combo_chase_guard`
Gate 4의 판정 로직(companion-detector 조건)을 변경해서는 안 된다.

**While** 본 SPEC이 적용되는 동안, the system **shall** Gate 4를 지평 시그니처
계산 및 임계값 선택보다 먼저 실행해야 한다(merged 딕셔너리에서 제거된 후보는
지평 시그니처 계산 대상에서 자연히 제외됨).

### REQ-AI100-005: 예측 생성 게이트와 매수 실행 게이트의 독립성 보존

**While** 본 SPEC이 적용되는 동안, the system **shall not** 지평 인식 예측 생성
임계값(`effective_threshold`의 지평 인식 확장)과 `surge_threshold_service`의
매수 실행 전용 적응형 임계값을 병합하거나 서로 참조하도록 만들어서는 안 된다. 두
게이트의 기존 명명·로그 분리(SPEC-AI-092)는 그대로 유지되어야 한다.

### REQ-AI100-006: 섀도우 모드 비교 로깅

**Where** `horizon_aware_thresholds.enabled`가 `false`(기본값, 아직 전환 전)이고
섀도우 모드 관측이 활성화되어 있으면, the system **shall** 매 스코어링 사이클마다
기존 임계값 경로의 qualified 집합과 신규 지평 인식 임계값 경로의 qualified 집합을
모두 계산하고, 두 집합의 차이(추가/제외된 종목 코드)를 구조화 로그로 기록해야
한다. 이 섀도우 계산의 실패가 기존 시그널 생성 흐름에 영향을 주어서는 **shall not**
안 된다(부가 관측 경로, `try/except` + 로그로 격리).

### REQ-AI100-007: 고아 탐지기 비배선 경계 보존

**While** 본 SPEC이 적용되는 동안, the system **shall not**
`weekend_gap_up`이나 `bollinger_squeeze` 탐지기의 결과를 앙상블 스코어링 대상
(`merged`) 또는 `FundSignal` 생성 경로에 신규로 편입시켜서는 안 된다. 이 두
탐지기는 본 SPEC 적용 전후 동일하게 고아(관측 전용) 상태를 유지해야 한다.

### REQ-AI100-008: 기존 평가 계층 및 재스캔 메커니즘 무변경

**While** 본 SPEC이 적용되는 동안, the system **shall not**
`_is_same_day_event_horizon_signal()`(평가 계층 same-day 배제 로직)이나
`_maybe_trigger_event_rescan()`(SPEC-AI-066 재스캔 메커니즘)의 판정 로직을
변경해서는 안 된다. 본 SPEC은 이 두 메커니즘을 소비하지 않는다.

### REQ-AI100-009: 섀도우 모드 → 프로덕션 전환 게이트의 구조적 최소 요건

**Where** `horizon_aware_thresholds.enabled`를 `false`에서 `true`로 전환하는
결정이 검토되면, the system **shall** 다음 세 요건이 모두 충족되었음을 전환
전 확인 절차의 일부로 요구해야 한다: (1) 섀도우 모드 관측 거래일 수가 최소
10 거래일(잠정값, Open Question 3) 이상일 것, (2) 관측 기간 동안
BULL/SIDEWAYS/BEAR 3개 시장 레짐이 각각 최소 1회 이상 관측되었을 것, (3) 신규
지평 인식 임계값 경로의 qualified 후보 집합이 기존 경로 대비 ±30%(잠정값,
Open Question 2) 이내로 유지될 것. **When** 세 요건 중 하나라도 미충족이면,
the system **shall not** 전환을 진행해서는 안 되며 추가 관측 또는 재검토를
요구해야 한다.

필수 조건:

- 세 요건의 정확한 수치(10 거래일, ±30%)는 잠정값이며, 섀도우 모드 관측
  데이터 축적 후 조정될 수 있다(Open Question 2, 3과 연계) — 단, "구조 자체가
  존재해야 한다"는 요건(3요건 체크 자체를 생략할 수 없다는 것)은 본 REQ로
  계획 단계에서 확정한다.
- 이 게이트는 수동 검토 절차(사람이 섀도우 로그를 확인하고 전환 여부를
  결정)로 구현되어도 무방하다 — 자동화된 CI 게이트를 요구하지 않는다. 단,
  세 요건의 충족 여부를 확인하는 절차(로그 조회 방법, 판정 기준)는 구현 시
  plan.md §D에 명문화되어야 한다.
- 본 REQ는 2026-07-28 `theme_news_carry` 자기강화 피드백 루프 사고(오탐률
  77% 도달 후 롤백)의 재발 방지 조치다 — 유사하게 개방형("이상 징후 관찰")
  기준으로 프로덕션 전환을 결정하지 않도록 구조적 최소 요건을 계획 단계에서
  구속력 있게 확정한다.

## Open Questions

정책 판단(아키텍처 옵션 선택 D1 / Gate 4 처리 D2 / 적응형 임계값 관계 D3 / 고아
탐지기 범위 D4 / 마이그레이션 방식 D5 / 전환 게이트 구조 D6)은 §Decisions에서
이미 확정했다. 남은 항목은 구현 시 또는 섀도우 모드 관측 데이터 축적 후 확정할
사항이다.

1. **탐지기별 지평 라벨의 정확한 값** — design.md §B가 예시 매핑(theme_cluster=
   multi_day, volume_news_combo=same_day, disclosure_pattern=same_day,
   news_delayed=multi_day, volume_breakout=same_day, momentum_continuation=
   next_day)을 제안했으나, 이는 plan.md TASK 단계에서 도메인 검증 후 확정한다 —
   특히 `volume_news_combo`(combo_score)가 온전히 same_day인지 아니면 mixed로
   분류해야 하는지는 실제 탐지 함수의 데이터 소스를 재확인해야 한다.
2. **지평별 임계값의 정확한 수치** — §Out of Scope에서 명시했듯 기존
   `regime_thresholds` 값을 그대로 재사용할 수 없다. 섀도우 모드 관측 데이터를
   기반으로 확정하며, 최종 확정 전까지는 보수적으로 기존 `regime_thresholds`와
   동일한 값으로 초기화해 "지평 인식이나 실질적으로 기존과 동일"한 상태에서
   시작하는 것을 제안한다(구현 시 확정). REQ-AI100-009(D6)가 qualified 후보
   집합 변화폭 상한(잠정 ±30%)을 전환 게이트 조건으로 이미 구속력 있게
   확정했으므로, 본 항목의 미확정은 그 상한 수치 자체가 아니라 상한 이내에서의
   세부 임계값 튜닝에 국한된다.
3. **섀도우 모드 관측 기간** — REQ-AI100-009(D6)가 최소 10 거래일(잠정값) **및**
   BULL/SIDEWAYS/BEAR 3개 레짐 전량 관측을 전환 전 구속력 있는 하한 요건으로
   이미 확정했다(2026-08-03, plan-auditor 1차 감사 반영). 남은 미확정 사항은
   이 하한을 넘어서는 실제 관측 기간의 상한/최적값이며, 관측 데이터의 변동성을
   보고 판단한다(구현 시 확정).
4. **섀도우 모드 로그의 영속화 여부** — 구조화 로그(JSON 라인)로 시작하되, 관측이
   길어지거나 정량 분석이 필요해지면 전용 비교 테이블 신설을 재검토한다(design.md
   §K, 미확정).
