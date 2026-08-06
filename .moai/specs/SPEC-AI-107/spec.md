---
id: SPEC-AI-107
title: "급등예측 confidence 캘리브레이터 — 섀도우 학습 배선(프로모션은 보류)"
version: "0.1.0"
status: completed
created: 2026-08-06
updated: 2026-08-06
author: Nexsol
priority: Medium
phase: "backend surge-detection v0.1.0"
module: "backend/app/services"
lifecycle: spec-anchored
tags: "surge-detection, calibration, isotonic-regression, shadow-mode, walk-forward-validation, backend"
tier: M
related_specs: [SPEC-AI-036, SPEC-AI-069, SPEC-AI-104, SPEC-AI-105, SPEC-AI-106]
---

# SPEC-AI-107: 급등예측 confidence 캘리브레이터 — 섀도우 학습 배선(프로모션은 보류)

## HISTORY

- 2026-08-06 v0.1.0 (draft): 위임 프롬프트("isotonic 캘리브레이터를 실제로 학습·배포해야
  하는가, 배포 비용 대비 가치가 있는가?")에 대한 응답으로 작성됐다. 위임 프롬프트는
  "보정된 confidence는 이미 선택된 시그널에 붙는 display/tracking 필드일 뿐이며,
  `compute_ensemble_score()` 이후·선택을 가르는 threshold 게이트 이후에 실행되므로
  선택 자체에는 영향을 주지 않는다"는 "검증된 사실"을 전제로 제시했다. 코드를 직접
  재확인한 결과 이 전제는 **부정확**했다 — `fund_manager.py:1439-1481`(SPEC-AI-036 M3
  "품질 floor 게이트")은 `calibrate_confidence(ensemble_score)`의 반환값을
  `min_calibrated_confidence`(0.35)와 직접 비교해 **후보를 완전히 배제(`continue`)할
  수 있는 두 번째 게이트**로 사용한다 — display 전용이 아니라 실제 선택(inclusion/
  exclusion) 입력값이다. 다만 세 가지 정정 사실을 함께 확인했다: (1) 이 게이트는
  `surge_detector.gather_surge_candidates()`가 이미 적용한 1차 임계값 게이트
  (`ensemble.min_score_for_signal`/`effective_threshold`, `surge_threshold_service.py`
  주석에서 재확인)와는 별개의, 이미 수집된 후보에 대한 2차 보조 게이트다. (2) 게이트
  통과 여부와 무관하게, 게이트 계산에 쓰인 `_calibrated_conf` 값 자체는 그 즉시 폐기된다
  — DB에 영속화되는 `FundSignal.confidence`는 `fund_manager.py:1521,1565`에서 항상
  `ensemble_score`(원시값)로 설정되며, 보정값이 저장되지 않는다. 즉 캘리브레이터를
  실제로 학습·배포해도 바뀌는 것은 오직 "이 2차 게이트를 통과하는 경계선상 후보의
  집합"뿐이다. Telegram 알림 문구와 `FundSignal.confidence`로 랭킹/정렬하는 다른 모든
  코드 경로는 영향받지 않는다. position sizing은 이와 다른 근거로 무관하다 —
  `_position_pct_by_confidence()`(`paper_trading.py:124-160`)는 실제로
  `FundSignal.confidence`를 읽어 포지션 비율을 4단계(confidence 0.60/0.70/0.80
  구간에 따라 0.10/0.15/0.20, 그 미만은 0.05)로 산정하는 confidence 참조
  로직이지만, 그 입력값인 `FundSignal.confidence`가 `fund_manager.py:1521,1565`에서
  항상 원시 `ensemble_score`로 설정되어 보정값이 저장되지 않으므로 캘리브레이터
  활성화의 영향을 받지 않는다. (3) `data/surge_calibrator.pkl` 미배포 상태에서
  `_calibrated_conf == ensemble_score`(identity fallback)이므로, 오늘 시점에 이 2차
  게이트는 사실상 "원시 앙상블 점수 ≥ 0.35"와 동일하게 동작 중이다. 본 SPEC은 이 정정된
  사실관계를 근거로, 원 질문("배포해야 하는가")에 대한 정직한 답을 다룬다: 이 세션은
  프로덕션 DB에 접근하지 않았으므로 현재 검증된 `(raw_confidence, is_correct)` 표본
  수·positive 비율을 확인하지 못했다(§Open Questions 1) — 데이터 충분성을 확인하지 않은
  채 "지금 배포한다"고 결정하는 것은 관찰되지 않은 근거로 검증 주장을 하는 것과 같은
  범주의 오류다. 따라서 SPEC-AI-104/105/106가 확립한 "wire → 관측 → 활성화는 별도 결정"
  패턴을 재사용해, 섀도우 모드로 매주 학습·검증만 수행하고 active
  `data/surge_calibrator.pkl`은 건드리지 않는 배선 작업까지만 다룬다.

## 선행 SPEC

- **SPEC-AI-036** (완료): isotonic PAV 캘리브레이터(`surge_calibrator.py`)와
  `fund_manager.py`의 품질 floor 게이트(`min_calibrated_confidence`/
  `min_composite_score`)를 원 구현한 SPEC. 본 SPEC은 `train_isotonic()`을 하위
  호환 방식으로 확장(§Requirements REQ-AI107-007)할 뿐, PAV 알고리즘 자체
  (`_run_pav`)는 재구현하지 않는다.
- **SPEC-AI-069** REQ-AI069-005: `data/surge_calibrator.pkl` 미배포 상태(identity
  fallback)를 "표면화만 하고 학습 파이프라인은 연결하지 않는다"고 명시적으로 결정한
  선행 REQ. 이 결정의 근거("표면화 우선, 배포는 별도 판단")를 본 SPEC이 계승한다 —
  본 SPEC은 이 REQ가 유보했던 "학습 파이프라인 연결" 자체를 다루되, 여전히 활성화까지는
  실행하지 않는다.
- **SPEC-AI-104/105/106**: Pool D canary / bridge 후보 정밀도 게이트 / 지평 인식
  임계값 전환 게이트. 세 SPEC 모두 "관측 인프라 배선 → 관측 기간 확보 → 실제 활성화는
  별도 SPEC/운영 판단" 패턴을 확립했다. 본 SPEC은 이 패턴을 캘리브레이터 도메인에
  재적용한다.

### amendment 여부

본 SPEC은 어떤 선행 SPEC의 amendment도 아니다. `amendment_of:` 없이 `related_specs`로만
참조하는 신규 SPEC이다.

## Context / Problem

### 문제 1 — 위임 프롬프트의 "display 전용" 전제가 부정확했다(§HISTORY 정정 참조)

`_calibrated_conf`는 `fund_manager.py`의 SPEC-AI-036 품질 floor 게이트에서 후보를
완전히 배제할 수 있는 입력값이다. 다만 그 영향 범위는 좁다 — 게이트 통과 여부에만
관여하며, 통과 이후에는 값 자체가 폐기되고 원시 `ensemble_score`만 영속화된다. 이
비대칭(좁지만 실재하는 영향)을 정확히 반영하지 않은 채 "캘리브레이터 배포"를 판단하면
잘못된 리스크 평가로 이어질 수 있다.

### 문제 2 — 재학습 진입점(`retrain_calibrator()`)이 이미 존재하지만 어디에서도 호출되지 않는다

`surge_calibrator.py`의 `retrain_calibrator(db)`는 SPEC-AI-036 REQ-036-005("주간
재학습 훅")를 위해 이미 구현되어 있으나, 백엔드 전체 트리(테스트 스위트 포함)를
grep으로 재확인한 결과 어디에서도 호출되지 않는다 — 스케줄러 잡, API, 리포트는
물론 `backend/tests/test_surge_calibrator.py`를 포함한 테스트 코드에서조차 호출부가
존재하지 않는다. 이 프로젝트의 반복된 실패 패턴("측정/학습 인프라는 존재하나 아무도 소비하지 않는
죽은 경로" — 예: SPEC-AI-070의 미소비 리포트, SPEC-AI-106의 미호출 판정 함수)을
재현할 위험이 있다.

### 문제 3 — 데이터 충분성이 이 세션에서 검증되지 않았고, `train_isotonic()`의 기존
저품질-데이터 가드는 표본 수 미달과 0%/100% 불균형만 막을 뿐 "표본은 충분하나
positive 클래스가 극소수"인 중간 상태를 막지 못한다

`train_isotonic()`(`surge_calibrator.py:123-186`)은 표본 50개 미만이거나 positive
비율이 정확히 0% 또는 100%일 때만 identity fallback으로 건너뛴다. 예컨대 50개 표본
중 positive가 2개(4%)인 경우도 현재 코드는 "학습"을 시도한다 — PAV는 이런 극단적
불균형에서 소수의 positive 지점 주변에 계단형 변곡을 만들 뿐이며, 신뢰할 수 있는
단조 보정 곡선을 산출하지 못한다. 이 프로젝트의 기록된 급등 커버리지("실제급등
52개중 시그널 5개(9.6%)")를 볼 때, positive 클래스 희소성은 가상의 위험이 아니라
관찰된 패턴이다.

## Goals

1. `retrain_calibrator()`가 이미 갖춘 학습 로직을 재사용하되, **시간순 walk-forward
   분할**(무작위 분할이 아님 — 시계열 금융 데이터의 lookahead bias 방지)로 학습/검증
   세트를 나누고, 검증(held-out) 세트에서 Brier 점수로 "보정이 원시값보다 실제로
   개선되는가"를 측정하는 **섀도우 학습**을 매주 1회 배선한다.
2. 섀도우 학습은 active `data/surge_calibrator.pkl`을 절대 덮어쓰지 않으며, 학습
   결과를 날짜별 candidate 아티팩트로 별도 저장한다 — 프로모션(활성화)은 이 SPEC의
   산출물이 아니다.
3. `train_isotonic()`에 최소 positive 표본 수 가드를 하위 호환 방식(옵션 인자,
   기본값은 기존 동작과 100% 동일)으로 추가해 문제 3을 완화한다.
4. 매 섀도우 학습 실행마다 (날짜, 표본 수, positive 수, 데이터 충분 여부, Brier
   점수 비교, 게이트 통과 여부)를 파일 기반 실행 로그(JSONL — 신규 DB 테이블 없이)에
   기록해 관측 가능하게 만든다.
5. 실제 프로모션(activation) 절차 — 게이트 통과 확인 방법, 프로모션 실행 방법, 롤백
   경로 — 를 plan.md §C에 문서화한다. 실제 프로모션 실행은 본 SPEC의 범위가 아니다.
6. `SurgeEnsembleConfig.min_calibration_samples`(이미 존재하나 어떤 코드에서도
   참조되지 않는 죽은 설정값, `surge_settings.py:583`)를 신규 게이트의 표본 수 floor로
   연결한다.

## Non-Goals

### Out of Scope — active pkl 자동 프로모션

- **섀도우 학습이 `data/surge_calibrator.pkl`을 자동으로 교체하거나 `save_calibrator()`를
  active 경로에 호출하는 것**: 데이터 충분성이 검증되지 않은 상태에서의 자동 배포는
  근거 없는 결정을 코드화하는 것과 같다. 프로모션은 항상 별도의, 명시적으로 트리거되는
  수동 절차(plan.md §C)로만 수행한다.

### Out of Scope — `fund_manager.py` 품질 floor 게이트 로직/임계값 변경

- **`min_calibrated_confidence`(0.35)/`min_composite_score`(0.60) 수치 변경,
  게이트 OR 조건 로직 변경**: 본 SPEC은 캘리브레이터 자체(학습·검증·영속화)만
  다루며, 이 값을 소비하는 게이트는 SPEC-AI-036 소유로 무수정 유지한다.

### Out of Scope — `signal_verifier.py`의 Bayesian `calibrate_confidence()` 변경

- **`signal_verifier.py:487-535`의 별개 Bayesian 신뢰도 보정 시스템(AI 분석
  buy/sell 시그널용, `fund_manager.py:2980`에서 호출) 수정**: 이는 isotonic
  캘리브레이터와 이름만 같을 뿐 완전히 다른 코드 경로다. 본 SPEC은 이 시스템을
  전혀 건드리지 않는다.

### Out of Scope — 신규 DB 테이블/마이그레이션

- **`SurgeCalibratorRun` 등 신규 SQLAlchemy 모델 또는 alembic 리비전 추가**: 실행
  로그는 기존 pickle-파일 기반 영속화 철학과 일관되게 파일 기반(JSONL)으로만
  구현한다.

### Out of Scope — numpy/scikit-learn 등 신규 의존성 도입

- **Brier 점수 계산이나 walk-forward 분할에 외부 통계 라이브러리 사용**:
  `surge_calibrator.py`의 기존 철학("numpy/scikit-learn 의존성 없이 순수 Python만
  사용한다", 모듈 docstring)을 그대로 유지한다.

## Decisions

### D1 — 섀도우 학습 + 명시적 수동 프로모션, 자동 배포는 기각한다

§Context 문제 1의 정정 사실(영향은 좁지만 실재함)과 문제 3(positive 희소성 위험)을
근거로, 데이터 충분성이 관측으로 확인되기 전까지 active 경로를 건드리지 않는다.

기각한 대안 — 지금 즉시 `retrain_calibrator()`를 스케줄러에 연결해 active pkl을
직접 갱신. 2026-07-28 `theme_news_carry` 자기강화 피드백 루프 사고(오탐률 77%
도달 후 발견) 이후 이 프로젝트는 스코어링 아키텍처 변경의 근거 없는 조기 전환을
명시적으로 경계해왔다 — 동일 원칙을 적용해 기각한다. (단, 본 SPEC의 재학습 루프는
그 사고와 근본적으로 다른 구조다 — §D5에서 순환 위험 부재를 확인한다.)

### D2 — 검증(holdout) 세트는 시간순 walk-forward 분할로 만든다, 무작위 분할은 기각한다

기각한 대안 — `sklearn.model_selection.train_test_split` 스타일의 무작위 분할.
시계열 금융 데이터에서 무작위 분할은 미래 시점의 표본이 학습 세트에 섞여 들어가는
lookahead bias를 유발한다 — 실제 배포 시나리오(과거 데이터로 학습, 미래 신호에
적용)를 재현하려면 `created_at` 기준 시간순 분할이 필수다.

### D3 — 실행 로그는 파일 기반 JSONL, 신규 DB 테이블은 기각한다

기각한 대안 — `SurgeCalibratorRun` SQLAlchemy 모델 + alembic 리비전. 캘리브레이터
자체가 이미 pickle 파일 기반으로 영속화되어 있고(`_CALIBRATOR_PATH`), 실행 로그도
같은 파일 기반 철학을 따르는 것이 일관적이며 마이그레이션 리스크(SPEC-AI-073에서
겪은 프로덕션 전용 마이그레이션 버그 사례)를 회피한다. JSONL은 append-only이므로
동시 쓰기 충돌 위험도 낮다(주 1회 단일 스케줄러 잡만 쓰기 수행).

### D4 — 최소 positive 표본 가드는 `train_isotonic()`에 신규 옵션 인자로 추가한다,
별도 함수 신설은 기각한다

기각한 대안 — `train_isotonic_v2()` 같은 별도 함수 신설. 기존 `train_isotonic()`의
시그니처에 `min_positive_samples: int | None = None`(기본값 `None` = 기존 동작과
완전 동일)을 추가하는 편이 더 단순하며, `test_surge_calibrator.py`의 기존 6개
AC(AC-1~AC-6) 테스트가 인자를 생략하는 한 무회귀로 통과한다.

### D5 — 순환 피드백 위험 부재 확인(2026-07-28 사고 재발 방지 점검)

`get_surge_calibration_pairs()`가 읽는 `FundSignal.confidence`는 §HISTORY에서
확인했듯 항상 원시 `ensemble_score`이며 보정값이 아니다 — 캘리브레이터가 자신의
과거 출력을 학습 입력으로 재섭취하는 구조가 아니다. 또한 PAV(`_run_pav`)는
결정론적 함수이므로 동일 입력에서 동일 출력을 낸다. 따라서 `theme_news_carry`
사고(자기강화 피드백 루프 — 태깅 결과가 다음 태깅의 입력이 되어 오염이 증폭)와
동일한 구조적 위험은 본 SPEC의 재학습 루프에 존재하지 않는다. 이 점검 결과 자체가
D1의 "섀도우 우선, 자동 배포는 아직 아님" 결정과는 독립적이다 — 순환 위험이 없다는
것이 데이터 충분성을 보장하지는 않는다.

## Requirements

### REQ-AI107-001 (P1, Event)

**When** 주 1회 예약된 캘리브레이터 섀도우 학습 잡이 실행되면, the system **shall**
최근 90일 내 검증 완료된 `(raw_confidence, is_correct, created_at)` 표본을 수집하고,
`created_at` 기준 시간순으로 정렬해 학습 구간과 검증(holdout) 구간으로 분할한 뒤,
학습 구간으로 isotonic 모델을 학습하고 그 결과를 날짜가 포함된 candidate 아티팩트로
저장해야 한다.

### REQ-AI107-002 (P0, Unwanted)

**While** 섀도우 학습 잡이 실행되는 동안, the system **shall not** active
`data/surge_calibrator.pkl` 파일을 덮어쓰거나 교체해서는 안 되며, **shall not**
프로세스 내 활성 캘리브레이터 싱글턴(`get_calibrator()`가 반환하는 인스턴스)을
변경해서는 안 된다.

### REQ-AI107-003 (P1, Event)

**When** candidate 모델 학습이 완료되면, the system **shall** 검증(holdout) 구간에서
원시(identity) 예측과 candidate 캘리브레이션 예측 각각의 Brier 점수를 계산하고,
그 비교 결과와 실행 메타데이터(날짜, 표본 수, positive 수, 게이트 통과 여부)를
파일 기반 append-only 실행 로그에 1개 행으로 기록해야 한다.

### REQ-AI107-004 (P1, State)

**While** 수집된 표본 수가 설정값(`SurgeEnsembleConfig.min_calibration_samples`)
미만이거나, positive 클래스 표본 수가 최소 positive 표본 floor 미만이면, the system
**shall** 해당 실행을 "데이터 부족(insufficient)"으로 실행 로그에 기록해야 하며,
**shall not** Brier 점수 비교나 candidate 아티팩트 저장을 시도해서는 안 된다.

### REQ-AI107-005 (P0, Unwanted)

the system **shall not** 본 SPEC 구현을 위해 신규 데이터베이스 테이블, 컬럼, 또는
alembic 마이그레이션을 도입해서는 안 된다. 실행 로그는 파일 기반(JSONL) 아티팩트로만
구현해야 한다.

### REQ-AI107-006 (P1, Ubiquitous)

the system's plan-phase 산출물 **shall** plan.md에 실제 프로모션(활성화) 시 사람이
따를 절차를 문서화해야 한다. 이 절차는 최소한 (1) 게이트 통과 확인 방법(실행 로그
조회), (2) 프로모션 실행 방법(candidate → active 경로 복사), (3) 롤백 경로(이전
candidate로 복원)를 포함해야 한다.

### REQ-AI107-007 (P2, Event)

**When** `train_isotonic()`이 신규 선택적 인자 `min_positive_samples`와 함께
호출되면, the system **shall** positive 클래스 표본 수가 그 값 미만인 입력을
identity fallback으로 처리해야 한다. **While** 이 인자가 생략되면(기본값), the
system **shall** 기존 `train_isotonic()` 호출부(테스트 포함)의 동작을 바이트 단위로
동일하게 유지해야 한다.

### REQ-AI107-008 (P1, Event)

**When** 섀도우 학습 잡의 표본 수집, 학습, 또는 로그 기록 단계에서 예외가
발생하면, the system **shall** 그 예외를 격리된 `try/except`로 잡아 경고 로그만
남겨야 하며, **shall not** 다른 예약된 스케줄러 잡의 실행에 영향을 주어서는 안 된다.

### REQ-AI107-009 (P2, Event)

**When** 섀도우 학습 잡이 표본 수 floor를 결정하면, the system **shall**
`SurgeEnsembleConfig.min_calibration_samples`(현재 어떤 코드에서도 참조되지 않는
설정값)를 그 floor 값으로 사용해야 한다.

## Open Questions

1. **프로덕션 DB의 실제 검증 완료 표본 수 및 positive 비율** — 이 세션은 프로덕션
   DB에 접근하지 않았으므로 `get_surge_calibration_pairs()`가 실제로 반환할
   `(raw_confidence, is_correct)` 표본 수와 positive 비율을 확인하지 못했다.
   REQ-AI107-001 배포 후 첫 실행 로그에서 실제 값을 확인할 수 있다 — 배포 자체가
   이 질문에 대한 관측 채널이다. `verify_signals()`(5일 후 검증, disclosure 유형은
   3일)를 통해 surge_candidate 시그널도 함께 라벨링되므로, 이 SPEC이 사용하는
   `is_correct`는 프로젝트 메모리의 "recall≈0%"(실제 급등 이벤트 재현율, 더 엄격한
   별개 지표)와 직접 같은 수치가 아니다 — 알파 기반 5일 forward-return 판정이라는
   더 관대한 기준이므로, 두 지표를 혼동해 정확한 표본 충분성을 미리 단정하지 않는다.
2. **최소 positive 표본 floor의 정확한 수치** — spec.md/plan.md는 잠정값(plan.md
   §A 참조)을 제안하지만, 실제 관측 데이터의 분포를 본 뒤 조정이 필요할 수 있다.
   조정은 후속 세션의 판단 대상이다.
3. **walk-forward holdout 비율(`holdout_fraction`)의 장기 적합성** — 현재 잠정값은
   plan.md §A에서 확정하나, 관측 항목이 늘어나면(예: 여러 holdout 구간에 대한
   교차 검증) 이 값의 재검토가 필요할 수 있다 — 이 SPEC의 결정 대상이 아니다.
