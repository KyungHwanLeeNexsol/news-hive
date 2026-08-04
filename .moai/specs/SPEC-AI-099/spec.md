---
id: SPEC-AI-099
title: "급등예측 피처 스냅샷 데이터 인프라 (모델 학습 미포함)"
version: "0.1.0"
status: in-progress
created: 2026-08-03
updated: 2026-08-04
author: Nexsol
priority: Medium
phase: "backend surge-detection v0.1.0"
module: "backend/app/services"
lifecycle: spec-anchored
tags: "surge-detection, ml-infrastructure, feature-store, data-pipeline, backend"
tier: M
related_specs: [SPEC-AI-012, SPEC-AI-017, SPEC-AI-018, SPEC-AI-025, SPEC-AI-036, SPEC-AI-041, SPEC-AI-065]
---

# SPEC-AI-099: 급등예측 피처 스냅샷 데이터 인프라 (모델 학습 미포함)

## HISTORY

- 2026-08-03 v0.1.0 (draft): 급등예측 최종 후보 점수가 학습된 분류기/랭커가 아닌
  수동 튜닝 가중합(hand-tuned weighted sum)이고, 그 뒤에 미래 모델을 학습시킬 종목별/
  시각별 피처 데이터셋 자체가 존재하지 않는 문제를 범위로 정의한다. 이 SPEC의 목적은
  모델을 만들거나 학습시키는 것이 **아니라**, 데이터가 충분히 축적된 이후 미래의 모델링
  SPEC이 필요로 할 **데이터 인프라(피처 스냅샷 저장소)**를 구축하는 것이다.
  research.md에서 위임 프롬프트의 "개별 원시 피처가 이미 계산되어 재사용 가능하다"는
  전제가 부분적으로 과대 서술되어 있음을 코드 대조로 확인해 §Decisions D3에 반영했다.

## 선행 SPEC

- **SPEC-AI-012/017/018**: `compute_ensemble_score()`의 가중합 공식, 레짐별 임계값,
  컨센서스 배율, 우회(bypass) 임계값의 소유 SPEC. 본 SPEC은 이 계산 로직 자체를
  전혀 수정하지 않는다 — 그 결과값을 읽어 저장하는 병렬 데이터 경로만 추가한다.
- **SPEC-AI-025**: `ml_feature_engineering.py`(`capture_daily_features`,
  `MLFeatureSnapshot`) — 일 단위 집계 피처 스냅샷의 소유 SPEC. 본 SPEC은 이 파이프라인을
  대체하지 않고, 종목별/사이클별 원자 단위 스냅샷이라는 **다른 그레인**을 신설한다.
- **SPEC-AI-036**: isotonic 캘리브레이터(`surge_calibrator.py`) + `composite_score`/
  `factor_scores` — `confidence`의 사후 보정. 본 SPEC의 스냅샷은 보정 전(raw)
  `surge_score`를 저장 대상으로 하며, 캘리브레이터 자체는 무수정이다.
- **SPEC-AI-041**: `SurgeActualOutcome`/`SurgePredictionEvaluation` 모델의 소유 SPEC.
  본 SPEC은 `SurgeActualOutcome`을 스냅샷의 정답 라벨 조인 대상으로만 참조하며, 두
  모델 모두 스키마를 변경하지 않는다.
- **SPEC-AI-065**: Pool A/B/C 스캔 유니버스 확장 및 `momentum_continuation` 탐지기
  (8번째 탐지기) — `SurgeCandidate` 데이터클래스의 현재 필드 구성 근거. 본 SPEC은 이
  구조를 무수정으로 소비만 한다.

### amendment 여부

본 SPEC은 어떤 선행 SPEC의 amendment도 아니다. `amendment_of:` 없이 `related_specs`로만
참조하는 통상적 신규 SPEC이다.

## Context / Problem

### 문제 1 — 최종 후보 점수가 학습된 모델이 아닌 수동 튜닝 가중합이다

`backend/app/surge_config/surge_detection.yaml:67-86`은 8개 탐지기 가중치
(`theme_cluster: 0.19, volume_news_combo: 0.25, disclosure_pattern: 0.14,
news_delayed: 0.11, weekend_gap_up: 0.08, volume_breakout: 0.11,
momentum_continuation: 0.12`)와 레짐별 고정 임계값(`BULL: 0.38, SIDEWAYS: 0.45,
BEAR: 0.42`)을 하드코딩한다. `compute_ensemble_score()`(`surge_detector.py:1538-1608`)는
이 가중치의 단순 곱셈-합산 + 컨센서스 배율만 수행한다 — 이 값들은 SPEC-AI-017/018/039/
050/065를 거치며 사람이 손으로 재조정해 온 이력이 코드 주석에 그대로 남아 있다.
`surge_calibrator.py`(isotonic 회귀, PAV 알고리즘)는 이 점수의 신뢰도를 사후 보정할
뿐, 가중합 자체를 대체하는 학습된 모델이 아니다(모듈 docstring: "numpy / scikit-learn
의존성 없이 순수 Python만 사용한다").

### 문제 2 — 미래 모델을 학습시킬 종목별/시각별 피처 데이터셋이 존재하지 않는다

`ml_feature_engineering.py:24-94`(`capture_daily_features`)는
`MLFeatureSnapshot.date`에 `unique=True` 제약이 걸려 있어 **하루에 정확히 1행**만
생성하며, 그 컬럼은 당일 시그널 전체의 4-factor 평균·추세 분포·`recent_5_accuracy`
같은 **집계값**이다 — 종목별/스캔사이클별 원자 단위 레코드가 아니다. 지도학습
분류기/랭커를 학습시키려면 "이 종목이 이 시각에 이런 피처 값을 가졌고, 이런 점수를
받았고, 실제로는 이렇게 되었다"는 행 단위 데이터가 필요하지만, 현재 어떤 테이블도 이
그레인을 저장하지 않는다.

### 문제 3 — `ML_READINESS_THRESHOLD_DAYS=90` 카운터가 소비처 없이 방치되어 있다

`check_ml_readiness()`(`ml_feature_engineering.py:97-120`)는 `MLFeatureSnapshot`
축적 일수를 90일 기준과 비교해 로그 메시지("REQ-AI-011 활성화를 검토하세요")만 남긴다.
이 반환값을 소비해 실제로 무언가를 트리거하는 코드는 존재하지 않는다 — 카운터만 있고
카운터가 가리키는 목적지(모델 학습 파이프라인)가 없다.

## Goals

1. 종목별·스캔사이클별(per-stock, per-timestamp) 불변(immutable) 피처 스냅샷을
   저장하는 신규 테이블/모델을 설계한다 — 기존 일 단위 집계(`MLFeatureSnapshot`)와는
   다른 그레인이며, 이를 대체하지 않는다.
2. 이 스냅샷을 어디서, 어떻게(배치 삽입 vs 개별 commit) 쓸지 쓰기 경로를 정의한다 —
   스캔 사이클의 체감 지연을 늘리지 않는 것을 제약으로 한다.
3. 보존 정책을 결정한다 — 이 테이블은 "미래의 학습 데이터셋"이라는 목적 자체가 짧은
   보존과 상충하므로, 스토리지 증가 트레이드오프를 문서화한 뒤 명시적으로 결정한다.
4. 기존 `ML_READINESS_THRESHOLD_DAYS=90` 카운터와의 관계를 정의한다 — 신규 테이블
   전용의 병렬 카운터를 추가할지, 기존 카운터를 확장할지 결정한다.
5. "이 SPEC의 Definition of Done"을 모델 학습 이전 단계에서 명확히 멈춘다 — 인수
   기준은 데이터가 캡처되고 조회 가능한지에 대한 것이며, 학습된 모델의 정확도에 대한
   것이 아니다.

## Non-Goals

### Out of Scope — 모델 학습/서빙

- **어떤 형태의 실제 모델 학습, 평가, 서빙도 포함하지 않는다**: LightGBM/XGBoost/
  scikit-learn 모델을 본 SPEC에서 도입하지 않는다 — 데이터 인프라만 구축한다.
- **`compute_ensemble_score()`의 수동 튜닝 가중합 로직 교체**: 그대로 유지한다 —
  본 SPEC은 병렬 데이터 캡처 경로만 추가할 뿐, 어떤 점수도 후보 승격/매매 실행에
  영향을 주는 방식으로 변경하지 않는다.
- **`ML_READINESS_THRESHOLD_DAYS`/`check_ml_readiness()`의 기존 로직 변경**:
  REQ-025 소유 함수는 무수정으로 둔다 — REQ-AI099-006이 병렬 카운터를 추가할 뿐
  기존 함수를 대체하지 않는다.

### Out of Scope — 원시 피처 확장

- **탐지기 함수 내부의 원시 지역변수(`volume_ratio` 등)를 반환값/객체 필드로 노출시키는
  작업**: research.md §2 정정에 따라, 이는 탐지기 함수 시그니처 변경을 요구하므로
  후속 SPEC으로 이월한다. 본 SPEC은 `SurgeCandidate`에 이미 존재하는 필드와
  `compute_ensemble_score`가 이미 계산하는 중간값만 스냅샷 대상으로 삼는다.
- **섹터 모멘텀, 시장 대비 상대수익률, 뉴스 기사 수 원시값 신규 조인**: 위와 동일한
  이유로 후속 SPEC 대상이다.

### Out of Scope — 이번 배치 형제 SPEC 영역

- **스캔 유니버스(Pool A/B/C/D) 구성 변경**: SPEC-AI-096/097 대상이다.
- **배치 시세 조회 최적화**: SPEC-AI-097 대상이다.
- **뉴스-종목 매칭 경계 가드**: SPEC-AI-098 대상이다.

### Out of Scope — 지평(horizon) 분리

- **T-1/same-day 지평 분리 재정의**: 다음 형제 SPEC으로 별도 계획될 예정이며, 본
  SPEC의 스냅샷은 지평 구분 없이 스캔 시점 자체를 `scanned_at`으로 기록하는 데 그친다.

## Decisions

### D1 — 캡처 지점은 `surge_detector.py`의 앙상블 스코어링 메인 루프다,
`fund_manager.py`의 `FundSignal` 생성 지점이 아니다

research.md §3-4가 확인했듯 `fund_manager.py`의 `FundSignal` 쓰기 경로는 (a) 스캔
사이클 간 **가변(mutable)**이고(5영업일 중복 시 기존 행 UPDATE), (b) 오직 임계값을
통과하거나 우회 조건을 만족한 **승격된 후보만** 본다. 반면 `surge_detector.py:2192-2199`
의 메인 루프(`for candidate in merged.values(): score = compute_ensemble_score(...)`)는
그 사이클에 고려된 **모든** 후보에 대해 정확히 1회씩 점수를 계산한다.

이 지점에서 캡처하면 최종 승격 여부(양성/음성)와 무관하게 그 사이클의 전체 스코어링
결과를 확보하게 되어, 향후 지도학습 시 필요한 양성/음성 예시를 모두 갖춘 데이터셋이
된다 — `FundSignal` 생성 지점에서 캡처하면 양성 예시만 남는다.

기각한 대안 — `fund_manager.py`의 `FundSignal` 생성 지점 재사용. 위 이유로 기각.
추가로 `FundSignal` 행 자체가 가변적이므로, 스냅샷을 그 위에 얹으면 "불변 피처
레코드"라는 요구사항과 충돌한다.

### D2 — 배치 삽입(batch insert)을 신설한다, 기존 개별 flush 패턴을 답습하지 않는다

research.md §3이 확인했듯 이 코드베이스의 스코어링 핫루프(`fund_manager.py`)는
후보마다 개별 `db.flush()`를 호출하는 패턴이며, 배치 삽입 선례는
`surge_universe_pool_service.py` 1곳뿐이다. 본 SPEC은 그 사이클에서 캡처된 모든
스냅샷 행을 리스트에 모아 두었다가 스코어링 루프(메인 루프 + 3개 우회 루프) 종료
직후 **1회의 `db.add_all()` + `db.commit()`**으로 기록한다. 이는 SQLAlchemy가 이미
제공하는 표준 API이며 신규 의존성이 필요 없다(Simplicity Ladder 3단계).

기각한 대안 — 후보마다 개별 `db.add()` + `db.flush()`. 기존 `FundSignal` 경로가
이미 이 패턴을 쓰고 있으나, 사용자가 명시적으로 "배치 삽입, 개별 commit 아님"을
요구했고, 스코어링 루프가 처리하는 후보 수(수십~수백 개/사이클)를 고려하면 배치
삽입이 스캔 사이클 체감 지연에 미치는 영향이 더 적다.

### D3 — 필드 범위는 이미 존재하는 값으로 한정한다, 신규 비용 계산을 발명하지 않는다

research.md §2 정정에 따라, 본 SPEC의 피처 스냅샷은 다음 세 그룹만 저장한다 —
(a) `SurgeCandidate` 데이터클래스에 이미 존재하는 필드 전체(탐지기별 스코어,
`price_5d_trend`, `entry_pool`, `active_detectors` 등), (b) `compute_ensemble_score`가
이미 계산하는 중간값(`best_disclosure_score`, `active_groups`, `weighted_sum`,
최종 `surge_score`), (c) 스코어링 루프 인접 코드가 이미 조회해 둔 컨텍스트
(`Stock.market_cap`, `price_at_signal` 후보용 현재가 — `fund_manager.py`가 이미
호출하는 `fetch_current_price_with_change_sync` 재사용). 원시 미노출 피처(거래량/
거래대금 비율, 뉴스 기사 수, 섹터 모멘텀, 시장 대비 상대수익률)는 §Out of Scope에
따라 이번 SPEC에서 제외한다.

기각한 대안 — 탐지기 함수 내부를 수정해 원시 지역변수를 노출. 범위가 본 SPEC의
"데이터 인프라 구축"이라는 목적을 넘어 탐지기 로직 자체를 건드리게 되어 기각.

### D4 — 보존 정책은 무기한 보존(자동 삭제 없음)으로 결정한다, 스토리지 증가는 후속
관찰 대상이다

research.md §6이 확인했듯 예측/결과 계열 테이블(`fund_signals`,
`surge_actual_outcome`, `surge_prediction_evaluation`)에는 애초에 정리 잡이 없으며,
5일 보존은 공시(disclosures)에만 적용되는 별개 정책이다. 본 SPEC이 신설하는 테이블은
그 정의 자체가 "90일 이상 축적되어야 학습을 검토할 수 있는" 미래 학습 코퍼스이므로,
5일 또는 짧은 보존은 테이블의 존재 목적과 정면으로 상충한다. 따라서 **자동 삭제
없음**으로 결정하고, 사이클당 예상 행 수(그 사이클의 `merged` 후보 수, 수십~수백 개
× 1일 재스캔 사이클 수, SPEC-AI-083 기준 다회)를 근거로 스토리지 증가 추정치를
plan.md에 기록한다. 행 수가 관리 임계치를 초과하면 별도 SPEC에서 보존 정책을
재검토한다(Open Question 1).

기각한 대안 — 공시와 동일한 5일 보존. 학습 코퍼스로서의 목적 자체를 무력화하므로
기각.

### D5 — 기존 `ML_READINESS_THRESHOLD_DAYS` 카운터는 무수정 보존한다, 신규 병렬
카운터를 추가한다

`check_ml_readiness()`는 REQ-025 소유이며 `MLFeatureSnapshot`(일 단위 집계) 축적을
계측하는 것이 그 함수의 정의된 책임이다. 본 SPEC의 신규 테이블은 다른 그레인
(종목별·사이클별)이므로 같은 함수를 확장해 두 그레인을 섞기보다, 신규 함수
(예: `check_feature_snapshot_readiness()`)를 추가해 신규 테이블의 축적 상태를
독립적으로 계측한다 — 기존 함수의 시그니처/반환값/로그 메시지는 완전히 무수정이다.

기각한 대안 — `check_ml_readiness()`에 신규 테이블 카운트를 추가 파라미터로 병합.
서로 다른 그레인의 축적 상태를 하나의 함수/메시지에 섞으면 두 지표 중 하나가 90일을
채워도 다른 하나가 아직이면 오해를 유발할 수 있어 기각.

## Requirements

### REQ-AI099-001: 종목별·사이클별 불변 피처 스냅샷 모델

**When** 급등예측 앙상블 스코어링 사이클이 그 사이클에 고려된 각 후보에 대해 점수를
계산하면, the system **shall** 그 후보의 종목코드, 스캔 시각, 탐지기별 스코어
(§Decisions D3 (a)), 최종 앙상블 점수, 최종 승격 여부(임계값 통과 또는 우회 경로 포함)를
불변(immutable) 레코드로 영속화해야 한다. 이미 영속화된 스냅샷 레코드는 후속 사이클에
의해 **shall not** 갱신되거나 덮어써져서는 안 된다(§Decisions D1의 불변성 요구사항).

필수 조건:

- 신규 레코드는 매 사이클 새 행으로 추가된다 — 동일 종목이 여러 사이클에 걸쳐
  재스캔되면 사이클마다 별도 행이 생긴다(`FundSignal`의 갱신형 UPDATE 패턴과 다름).
- 저장 필드는 §Decisions D3에서 정의한 세 그룹(이미 존재하는 값)으로 한정한다.

### REQ-AI099-002: 배치 삽입 쓰기 경로

**When** 앙상블 스코어링 사이클(메인 루프 + 3개 우회 루프)이 완료되면, the system
**shall** 그 사이클에서 캡처된 모든 피처 스냅샷 행을 단일 배치 쓰기(`db.add_all()`
+ 1회 `db.commit()` 또는 동등한 배치 API)로 영속화해야 하며, 후보마다 개별
`db.flush()`/`db.commit()`을 호출해서는 **shall not** 안 된다.

필수 조건:

- 배치 쓰기 실패가 이미 완료된 앙상블 스코어링 결과(`FundSignal` 생성 등)를 되돌리지
  않는다 — 스냅샷 쓰기는 부가 관측 경로이며 실패해도 기존 시그널 생성 흐름을 막지
  않는다(`try/except` + 로그로 격리).

### REQ-AI099-003: 정답 라벨 조인 가능성

**Where** `SurgeActualOutcome`에 해당 종목·해당 거래일의 실제 결과가 존재하면, the
system **shall** 피처 스냅샷 레코드가 `(stock_code, 다음 거래일)` 키로
`SurgeActualOutcome.(trading_date, stock_code)`와 조인 가능해야 한다. **While**
아직 그 거래일의 실제 결과가 영속화되지 않은 상태이면, the system **shall** 정답
라벨 필드를 명시적으로 미확정(`NULL`)으로 남겨두어야 하며 **shall not** 0이나
임의값으로 채워서는 안 된다.

필수 조건:

- 정답 라벨 백필은 본 SPEC의 배선 범위이며, 실제 백필 잡의 실행 주기는 매일
  새벽 1회로 확정되었다(§Open Questions 2 확정, plan.md TASK-003).
- `SurgePredictionEvaluation`(일별 집계)은 조인 대상이 아니다 — research.md §5.

### REQ-AI099-004: 보존 정책 배선

**While** 본 SPEC이 적용되는 동안, the system **shall not** 신규 피처 스냅샷 테이블에
자동 삭제/정리 잡을 등록해서는 안 된다(§Decisions D4 — 무기한 보존).
행 수 증가 추정치는 plan.md에 문서화되어야 한다.

### REQ-AI099-005: 신규 병렬 축적 상태 카운터

**When** 신규 피처 스냅샷 테이블의 축적 상태를 조회하면, the system **shall** 기존
`check_ml_readiness()`와 독립된 신규 함수로 해당 테이블의 누적 행 수(또는 고유
스캔 사이클 수)를 90일 상당 기준과 비교해 반환해야 하며, 기존
`check_ml_readiness()`의 시그니처·반환값·로그 메시지를 **shall not** 변경해서는
안 된다.

### REQ-AI099-006: 모델 학습/서빙 경계 보존

**While** 본 SPEC이 적용되는 동안, the system **shall not** 어떤 학습된 분류기/
랭커/앙상블 모델도 도입하거나 `compute_ensemble_score()`의 가중합 결과를 사용해
후보 승격/매매 실행 로직을 변경해서는 안 된다. 본 SPEC이 캡처하는 데이터는 저장·조회
가능한 상태로만 존재해야 한다.

## Open Questions

정책 판단(캡처 지점 D1 / 배치 삽입 D2 / 필드 범위 D3 / 보존 정책 D4 / 카운터 분리 D5)과
정답 라벨 백필 잡의 실행 주기(구 Open Question 2)는 확정되었다. 남은 항목(1, 3)은
구현 시 또는 데이터 축적 후 확정할 사항이다.

1. 행 수 관리 임계치 — D4가 "무기한 보존"으로 결정했으나 구체적인 "관리 임계치를
   초과하면 재검토"의 정량 기준(예: 100만 행, 1GB)은 아직 미정이다. plan.md TASK
   단계에서 대략적인 사이클당 행 수 추정을 바탕으로 잠정치를 제시하되, 최종 확정은
   실제 축적 데이터를 관찰한 후로 미룬다.
2. ~~정답 라벨 백필 잡의 실행 주기~~ — **확정**: 매일 새벽 1회
   (`SurgeActualOutcome`이 장 마감 후 채워지는 시점과 정렬). plan.md TASK-003 참고.
3. `surge_calibrator.py`의 보정 후 confidence와의 관계 — 본 SPEC은 보정 전(raw)
   `surge_score`만 저장 대상으로 삼았다. 보정 후 값도 병행 저장할 필요가 있는지는
   향후 모델링 SPEC 설계 시 재판단한다(현재는 저장하지 않음).
