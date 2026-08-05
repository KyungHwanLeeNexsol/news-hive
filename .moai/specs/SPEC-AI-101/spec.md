---
id: SPEC-AI-101
title: "급등예측 정답 라벨 재정의(신호가 대비 EOD 최대수익률) + SPEC-AI-100 섀도우 전환 게이트 실행"
version: "0.1.0"
status: completed
created: 2026-08-04
updated: 2026-08-05
author: Nexsol
priority: High
phase: "backend surge-detection v0.1.0"
module: "backend/app/services"
lifecycle: spec-anchored
tags: "surge-detection, evaluation-metric, outcome-label, horizon-aware-threshold, shadow-mode, backend"
tier: L
related_specs: [SPEC-AI-095, SPEC-AI-100, SPEC-AI-075, SPEC-AI-083, SPEC-AI-093, SPEC-AI-099, SPEC-AI-072]
---

# SPEC-AI-101: 급등예측 정답 라벨 재정의(신호가 대비 EOD 최대수익률) + SPEC-AI-100 섀도우 전환 게이트 실행

## HISTORY

- 2026-08-04 v0.1.0 (draft): 2026-08-04 GPT 급등예측 구조 비평(외부 진단, 오케스트레이터가
  코드 대조로 교차검증 완료)이 제기한 두 문제를 범위로 정의한다. (1) `SurgeActualOutcome.was_surge`가
  종가 기준(T close ≥ +10%) 단일 라벨이라 "장중에는 잡았으나 종가에 반납한" 정당한 예측 적중을
  거짓음성으로 오분류한다는 지적, (2) SPEC-AI-100이 완성한 지평 인식 임계값 아키텍처가
  `enabled=false, shadow_mode_enabled=false`로 완전히 비활성 상태라는 지적. research.md §2
  조사에서 원 비평이 제안한 30/60/120분 세분 지평 라벨은 분봉 시계열 수집 인프라 부재로 이번
  SPEC 범위를 벗어남을 확인했고, 대신 이미 수집된 `price_at_signal`(FundSignal) +
  `high_change_rate`(SPEC-AI-093)만으로 신규 데이터 수집 없이 계산 가능한 EOD(장마감) 지평
  근사를 v1 범위로 채택했다(design.md §B).

## 선행 SPEC

- **SPEC-AI-095**: `high_change_rate`를 `high_based_recall/precision/coverage` 병렬 보조지표로
  노출한 선행 SPEC. `was_surge`는 그대로 동결(REQ-AI095-002)했다. 본 SPEC은 이 "동결 + 병렬 추가"
  선례를 그대로 따른다 — `was_surge`/`SurgeActualOutcome`을 재정의하지 않고 신규 신호 단위
  테이블을 추가한다.
- **SPEC-AI-100**: 지평 인식 임계값 선택 아키텍처(`compute_horizon_signature`,
  `select_effective_threshold`), 섀도우 비교 로깅(`run_horizon_shadow_comparison`, 메인 루프에
  이미 배선됨, `enabled=false/shadow_mode_enabled=false`로 조기 반환), 섀도우→프로덕션 전환
  게이트 3요건(REQ-AI100-009/AC-100-011: 관측 거래일 ≥10일, 3개 레짐 전량 관측, qualified 집합
  변화폭 ±30% 이내)의 소유 SPEC. 본 SPEC은 이 아키텍처를 재구현하지 않고 (a) 섀도우 관측을
  켜고 (b) 3요건 판정을 로그 스크래핑이 아닌 SQL 쿼리로 만드는 실행 SPEC이다(SPEC-AI-100
  Open Question 4가 예견한 "정량 분석이 필요해지면 전용 비교 테이블 신설을 재검토"의 실행).
- **SPEC-AI-075/083**: 평가 계층 지평 분리 선례(`surge_metadata` 기반 predicted_set 배제
  패턴, `horizon` 메타데이터 필드). 본 SPEC의 신규 라벨은 이 배제 패턴과 독립이며 재구현하지
  않는다 — `_is_near_limit_up_carry_signal`/`_is_same_day_event_horizon_signal`은 무수정 PRESERVE.
- **SPEC-AI-093**: `high_change_rate` 실측 수집(장중 고가 기준 등락률, T-1 종가 대비 %).
  본 SPEC은 이 컬럼을 절대가 환산의 입력으로 재사용한다 — 수집 로직 자체는 무수정.
- **SPEC-AI-072**: `fetch_stock_price_history_sync`를 날짜 매칭(인덱스 아님)으로 T-1 종가를
  조회하는 기법의 최초 선례. 본 SPEC은 동일 기법을 재사용해 T-1 종가 절대가를 조회한다.
- **SPEC-AI-099**: `SurgeFeatureSnapshot` 인프라 + `check_feature_snapshot_readiness()`(90일
  고유 스캔일수 기준). 본 SPEC의 신규 라벨은 향후 이 피처 스냅샷과 결합해 모델 학습 입력이
  될 수 있으나, 모델 학습 자체와 90일 축적 판단은 본 SPEC의 범위 밖이다(§Non-Goals).

### amendment 여부

본 SPEC은 어떤 선행 SPEC의 amendment도 아니다. `amendment_of:` 없이 `related_specs`로만
참조하는 신규 SPEC이다.

## Context / Problem

### 문제 1 — `was_surge` 종가 라벨이 신호가 대비 정당한 장중 적중을 거짓음성으로 오분류한다

`SurgeActualOutcome.was_surge`(`change_rate >= 10.0`, T당일 **종가** 기준)는
`evaluate_surge_predictions()`의 `actual_set`(recall/precision 분모)을 정의하는 유일한
기준이다(`surge_evaluation_service.py:775-784`). 그러나 급등예측의 실사용 시나리오는
"신호 발행 시점에 매수 가능했는가, 그 이후 장중 어느 시점에 이익 실현이 가능했는가"이며
종가는 그 실현 가능 시점 중 하나일 뿐이다. 다음 두 경우 모두 실질적으로는 예측이 적중했으나
현재 라벨은 거짓음성(FN)으로 집계한다:

1. 장중 고점 +15%까지 갔다가 매도 물량에 종가 +7%로 마감 — 종가 기준 `was_surge=False`.
2. 신호가(매수 가능가) 대비 +3%에서 시작해 장중 +12%까지 상승했다가 +8% 종가로 반납 —
   시그널가 대비로는 명확히 목표 수익률(+10%)을 초과 달성했으나 종가 기준으로는 실패.

`high_change_rate`(SPEC-AI-093, T-1 종가 대비 장중 고가 등락률)가 이미 실측 수집되고 있으나,
`high_based_recall/precision/coverage`(SPEC-AI-095)라는 **T-1 종가 기준** 병렬 보조지표로만
쓰이며 **신호 발행가(시그널 시점 매수 가능가) 대비** 수익률은 어느 지표에도 반영되지 않는다.
T-1 종가와 신호 발행가는 다른 기준점이다 — 신호는 T-1 15:20 배치뿐 아니라 장중에도 발행되며
(SPEC-AI-083 이벤트 재스캔), 신호 발행 시점의 실제 매수 가능가가 실사용 관점의 올바른 기준점이다.

### 문제 2 — SPEC-AI-100이 완성한 지평 인식 임계값 아키텍처가 완전히 비활성 상태로 방치되어 있다

`surge_detection.yaml`의 `ensemble.horizon_aware_thresholds.enabled`와
`.shadow_mode_enabled`가 모두 `false`다. 관련 함수(`compute_horizon_signature`,
`select_effective_threshold`, `run_horizon_shadow_comparison`)는 모두 구현되어 메인 루프에
배선까지 완료됐으나, `shadow_mode_enabled=false`로 인해 관측 자체가 시작되지 않는다.
SPEC-AI-100 plan.md §D는 전환 게이트 3요건(REQ-AI100-009)을 이미 계획 단계에서 구속력
있게 확정했으나, "확인 절차(로그 조회 방법, 판정 기준)는 구현 시 명문화되어야 한다"는
요건은 아직 실행되지 않았다 — 관측을 시작하고, 관측 결과를 3요건에 맞춰 판정하는 절차
자체가 존재하지 않는다.

## Goals

1. 신호 발행가(`FundSignal.price_at_signal`) 대비 그날 고점까지의 실현 가능 수익률을
   근사하는 **신규 additive 지표**를 신규 테이블로 도입한다 — `SurgeActualOutcome.was_surge`는
   재정의하지 않고 동결한다(SPEC-AI-095 선례).
2. 이 신규 지표를 `evaluate_surge_predictions()`의 병렬 보조지표(recall/precision/coverage)로
   노출한다 — 표준 T-1→T 지표(legacy_recall, scannable_recall) 산출 로직은 무수정.
3. SPEC-AI-100의 섀도우 관측(`shadow_mode_enabled`)을 활성화하고, 섀도우 비교 결과를
   경량 신규 테이블에 영속화한다.
4. SPEC-AI-100의 전환 게이트 3요건(REQ-AI100-009)을 SQL 쿼리 1개로 판정 가능한 함수로
   구현한다 — 자동 CI 게이트가 아닌 수동 검토 지원 도구(REQ-AI100-009가 이미 이렇게 설계).
5. `horizon_aware_thresholds.enabled`를 `true`로 전환하는 결정 자체는 본 SPEC의 범위에
   포함하지 않는다 — 그 결정은 관측 데이터 축적 후 별도로 이루어진다(§Non-Goals).

## Non-Goals

### Out of Scope — 세분 장중 지평(30/60/120분) 라벨

- **분/시간 단위 forward return, 최대 역행폭(MAE), 체결가능가(슬리피지 반영) 라벨의 구현**:
  research.md §2가 확인했듯 이 코드베이스에는 분봉/장중 시계열 가격 수집 인프라가 존재하지
  않는다. 이를 만들려면 신규 주기적 폴링 파이프라인 + 신규 영속 테이블이 필요하며, 이는
  "라벨 재정의"가 아닌 별도 데이터 수집 인프라 SPEC 규모다. 본 SPEC은 EOD(장마감) 지평
  근사만 다룬다.

### Out of Scope — 모델 학습/서빙

- **어떤 형태의 실제 모델 학습, 평가, 서빙도 포함하지 않는다**: 신규 라벨은 향후 모델
  학습 입력 후보가 될 수 있으나, 학습 자체와 SPEC-AI-099의 90일 축적 판단은 별도 후속
  SPEC의 결정 대상이다.

### Out of Scope — `was_surge`/`SurgeActualOutcome` 파괴적 재정의

- **기존 `was_surge`, `change_rate` 컬럼의 의미·계산 방식 변경**: SPEC-AI-095 선례를 따라
  동결하고 병렬 추가만 한다. 기존 소비자(`diagnose_non_scannable_causes`,
  `evaluate_surge_predictions` legacy/scannable recall 경로 등 7곳 이상)는 완전히 무수정이다.

### Out of Scope — SPEC-AI-100 스코어링/게이팅 로직 자체

- **`compute_ensemble_score`, `compute_horizon_signature`, `select_effective_threshold`의
  내부 계산 로직 수정**: 본 SPEC은 이 함수들을 호출·확장(섀도우 결과 영속화)만 하며 판정
  로직 자체는 SPEC-AI-100 소유로 무수정 유지한다.
- **`horizon_aware_thresholds.enabled`를 `true`로 전환하는 실제 결정**: 이 결정은 본 SPEC이
  구축하는 관측 인프라가 ≥10 거래일 + 3개 레짐 데이터를 축적한 이후, 별도 세션에서
  판정 함수의 출력을 사람이 검토해 내린다. 본 SPEC의 완료 조건이 아니다.

### Out of Scope — 매매 실행 로직

- **`surge_trading_service.py`, `fund_manager.py`의 실제 매매 실행 경로 변경**: 본 SPEC은
  라벨링/평가/전환게이트 관측 영역이며 매매 실행에 관여하지 않는다.

## Decisions

design.md에서 상세 분석을 완료했다. 이 절은 결정 사항만 요약하고, 근거는 design.md의
해당 절을 참조한다.

### D1 — EOD 지평 근사를 신규 additive 테이블로 도입한다, `SurgeActualOutcome` 파괴적
재정의는 기각한다

design.md §B. `SurgeActualOutcome`의 PK는 `(trading_date, stock_code)`이며 신호 단위가
아니다 — 같은 종목이 같은 날 여러 번(T-1 배치 + 장중 재스캔) 신호를 받을 수 있으므로,
신호가 대비 수익률은 **신호 단위**로 계산해야 한다. 신규 테이블
`SurgeSignalForwardOutcome`(가칭, PK 후보: `fund_signal_id`)을 신설해 각 `surge_candidate`
신호별로 `price_at_signal`, 파생 `day_high_price`, `forward_max_return_pct`를 저장한다.

기각한 대안 — `SurgeActualOutcome`에 컬럼 추가. 신호 단위가 아닌 (날짜, 종목) 단위
테이블에 신호 단위 값을 강제로 밀어넣으면 동일 종목 복수 신호 시 마지막 값으로 덮어써지는
데이터 손실이 발생해 기각한다.

### D2 — 절대가는 `fetch_stock_price_history_sync` 재사용으로 도출한다, 신규 가격 수집
인프라는 도입하지 않는다

design.md §B. `day_high_price = prev_close_price × (1 + high_change_rate/100)`,
`prev_close_price`는 SPEC-AI-072 선례와 동일하게 날짜 매칭으로 조회한다. 신규 외부 API
호출 경로를 만들지 않는다 — 평가 잡(`evaluate_surge_predictions`) 실행 시점에 기존 함수를
재사용한다.

기각한 대안 — 분봉 시계열 신규 수집. research.md §2가 확인했듯 인프라 규모가 본 SPEC의
범위를 벗어나 기각한다(별도 후속 SPEC 후보로 남김).

### D3 — 섀도우 비교 결과를 경량 신규 테이블에 영속화한다, 로그 스크래핑에 의존하지 않는다

design.md §F. `run_horizon_shadow_comparison()`(SPEC-AI-100 소유)에 `db: Session` 인자를
추가해, 매 스코어링 사이클 결과를 신규 테이블 `SurgeHorizonShadowObservation`에 한 행씩
적재한다(레짐, 기존/신규 qualified 건수, added/removed 건수, 변화폭). 기존 `logger.info`
로그는 그대로 유지한다(제거하지 않음, 회귀 없음).

기각한 대안 — 로그 파일을 파싱해 3요건을 판정. 로그는 `added or removed`가 있을 때만
찍히므로(`surge_detector.py:1769`) "변화 없는 날"이 관측 거래일 수에서 누락되는 구조적
버그가 있다 — 관측 거래일 카운트가 실제보다 적게 집계된다. 영속화 테이블은 매 사이클
1행씩 무조건 적재해 이 문제를 원천 차단한다.

### D4 — `run_horizon_shadow_comparison` 시그니처 확장은 SPEC-AI-100 소유 코드에 대한 정당한
확장이다, PRESERVE 위반이 아니다

design.md §F. SPEC-AI-100 plan.md §A.6 PRESERVE 목록은 `compute_ensemble_score`의 가중합
본체, 3개 bypass 루프, `combo_chase_guard`, `sector_contagion` 게이트,
`surge_threshold_service.py`, 평가 계층, 재스캔 메커니즘을 무수정 대상으로 명시했다 —
`run_horizon_shadow_comparison`은 이 목록에 없으며, 오히려 SPEC-AI-100 자신의 Open
Question 4("영속화 여부... 재검토")가 명시적으로 확장을 예견한 함수다. 시그니처에 `db`
인자를 추가하는 것은 함수의 판정 로직(qualified 집합 비교)을 전혀 건드리지 않는 순수
관측 채널 확장이다.

### D5 — 전환 게이트 3요건 판정은 SQL 쿼리 함수로 구현한다, 자동 CI 블로킹 게이트는
도입하지 않는다

design.md §G. `check_horizon_transition_readiness(db)` 함수가
`SurgeHorizonShadowObservation`을 집계해 (관측 고유 거래일수, 관측된 레짐 집합, 관측
기간 중 최대 변화폭 %) 3개 값을 반환한다. REQ-AI100-009 자체가 "자동화된 CI 게이트를
요구하지 않는다"고 명시했으므로, 이 함수의 결과는 사람이 검토해 전환 여부를 결정하는
입력으로만 쓰인다 — 함수가 `true`를 반환해도 `enabled` 플래그를 자동으로 전환하지 않는다.

기각한 대안 — 3요건 충족 시 자동으로 `enabled=true`로 전환. 2026-07-28
`theme_news_carry` 자기강화 피드백 루프 사고(오탐률 77%까지 자동 확산된 뒤에야 발견) 이후
이 프로젝트는 스코어링 아키텍처 변경의 자동 전환을 명시적으로 경계해왔다(SPEC-AI-100
D6) — 동일 원칙을 적용해 기각한다.

## Requirements

### REQ-AI101-001: 신호 단위 EOD 최대수익률 근사 테이블 신규 도입

**When** T당일 평가 잡(`evaluate_surge_predictions`)이 실행되면, **Where** 해당 신호가
`surge_candidate` 타입이고 `price_at_signal`이 NULL이 아니면, the system **shall** 그
신호에 대해 `day_high_price`(T-1 종가 절대가 × (1 + `high_change_rate`/100))와
`forward_max_return_pct`((`day_high_price` − `price_at_signal`) / `price_at_signal` ×
100)를 계산해 신규 테이블에 저장해야 한다. `price_at_signal`이 NULL이거나 T-1 종가 조회에
실패하면, the system **shall** 해당 신호의 파생값을 NULL로 남겨야 하며 평가 잡 전체를
실패시켜서는 **shall not** 안 된다.

필수 조건:

- 신규 테이블은 `SurgeActualOutcome`과 독립된 신규 테이블이며, 기존 `SurgeActualOutcome`
  스키마(컬럼)는 무수정이다.
- 계산 실패는 SPEC-AI-095의 `high_based_*` 격리 패턴(try/except + db.rollback())을
  재사용해 격리한다.

### REQ-AI101-002: 신호가 기준 병렬 recall/precision/coverage 노출

**When** `evaluate_surge_predictions()`가 실행되면, **Where** REQ-AI101-001의 신규 테이블에
`forward_max_return_pct >= 10.0`인 신호가 존재하면, the system **shall** 이 신호가 기준
집합을 기존 `predicted_set`과 비교해 병렬 recall/precision을 산출하고
`SurgePredictionEvaluation`(또는 그 확장)에 노출해야 한다. 이 계산은 SPEC-AI-095가
확립한 "predicted_set은 2단계에서 이미 확정, 재조회 금지" 원칙을 그대로 준수해야 한다.

필수 조건:

- 표준 T-1→T `legacy_recall`/`scannable_recall`/`coverage` 산출 로직은 이 REQ의 구현으로
  인해 **shall not** 변경되어서는 안 된다.
- 분모가 0인 경우 NULL 처리 원칙(SPEC-AI-095 AC-095-008/009 패턴)을 재사용한다.

### REQ-AI101-003: SPEC-AI-100 섀도우 관측 활성화

**Where** 본 SPEC의 REQ-AI101-004(영속화)가 구현 완료되면, the system **shall**
`surge_detection.yaml`의 `ensemble.horizon_aware_thresholds.shadow_mode_enabled`를
`true`로 전환해야 한다. **While** 이 전환이 적용된 상태에서도, the system **shall not**
`horizon_aware_thresholds.enabled`를 변경해서는 안 된다(SPEC-AI-100 REQ-AI100-003 바이트
동일 동작 보장 유지).

### REQ-AI101-004: 섀도우 비교 결과 영속화

**When** `run_horizon_shadow_comparison()`이 매 스코어링 사이클마다 실행되면, **Where**
`shadow_mode_enabled`가 `true`이면, the system **shall** 그 사이클의 비교 결과(시장
레짐, 기존 qualified 건수, 신규 qualified 건수, added/removed 종목 코드, 변화폭)를 신규
테이블 `SurgeHorizonShadowObservation`에 한 행 적재해야 한다 — `added`와 `removed`가
모두 빈 경우(변화 없음)에도 반드시 한 행을 적재해야 한다(D3 — 관측 거래일 누락 방지).
기존 `logger.info` 로그 출력은 the system **shall not** 제거해서는 안 된다.

필수 조건:

- `run_horizon_shadow_comparison()`의 예외 격리(REQ-AI100-007, try/except)는 영속화 실패도
  포함하도록 확장되어야 한다 — 영속화 실패가 기존 시그널 생성 흐름에 영향을 주어서는
  **shall not** 안 된다.
- `compute_ensemble_score`, `compute_horizon_signature`, `select_effective_threshold`의
  판정 로직 자체는 이 REQ의 구현으로 인해 **shall not** 변경되어서는 안 된다(D4).

### REQ-AI101-005: 전환 게이트 3요건 판정 함수

**When** 사용자 또는 오케스트레이터가 SPEC-AI-100의 전환 게이트(REQ-AI100-009) 충족
여부를 확인하려 하면, the system **shall** `SurgeHorizonShadowObservation`을 집계해
(1) 관측된 고유 거래일 수, (2) 관측된 시장 레짐 집합(BULL/SIDEWAYS/BEAR), (3) 관측 기간
중 qualified 집합 최대 변화폭(%)을 반환하는 조회 함수를 제공해야 한다. 이 함수는 3요건
충족 여부를 참고 정보로만 반환해야 하며, `horizon_aware_thresholds.enabled`를 the system
**shall not** 자동으로 전환해서는 안 된다(D5).

### REQ-AI101-006: `enabled=true` 전환은 본 SPEC의 완료 조건이 아니다

**While** 본 SPEC이 완료되는 시점에도, the system **shall not**
`horizon_aware_thresholds.enabled`가 `true`로 전환되어 있는 것을 요구하지 않는다. 본
SPEC의 Definition of Done은 관측 인프라(REQ-AI101-003~005)가 정상 동작하는 상태까지이며,
실제 전환 결정은 관측 데이터 축적 후 별도로 이루어진다.

## Open Questions

1. **`SurgeSignalForwardOutcome`의 정확한 PK/컬럼명** — `fund_signal_id`를 FK로 쓸지,
   `(trading_date, stock_code, signal_created_at)` 복합키를 쓸지는 구현 시
   `FundSignal.id`의 인덱스/조회 패턴을 확인 후 확정한다(design.md §C).
2. **`price_at_signal`의 실측 채움률** — nullable 컬럼이므로 실제 surge_candidate 신호
   중 몇 %가 NULL인지 구현 착수 전 프로덕션 데이터로 확인이 필요하다. 채움률이 낮으면
   REQ-AI101-001의 실효성이 제한된다(design.md §C, plan.md TASK-001에서 도메인 검증).
3. **`SurgeHorizonShadowObservation`의 보존 기간** — 무한 누적 방지를 위한 보존 정책
   (예: 90일 롤링 삭제)은 구현 시 결정한다. 전환 게이트 판정에는 최근 관측 구간만 필요하므로
   장기 보존이 필수는 아니다.
