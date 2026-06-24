---
id: SPEC-AI-063
version: "1.0.0"
status: completed
created: "2026-06-24"
updated: "2026-06-24"
author: Nexsol
priority: P1
issue_number: 0
---

# SPEC-AI-063: volume_breakout 소형주 독립 시그널 우회 경로 추가

## HISTORY

- 2026-06-24 (v1.0.0): 최초 작성. SPEC-AI-062가 추가한 `volume_breakout` 탐지기가 앙상블 수학적 한계로 단독 시그널을 생성하지 못하는 문제를 해결하기 위한 우회 경로(bypass path) 정의.

## 배경 (Background)

급등 예측 시스템은 7개 탐지기 앙상블로 한국 주식시장 급등 후보를 탐지한다. SPEC-AI-062에서 추가된 `volume_breakout` 탐지기는 Naver 거래량 순위 데이터를 기반으로 뉴스/공시 없이 소형주를 포착하기 위한 목적으로 도입되었다.

그러나 `volume_breakout` 탐지기는 앙상블 점수 계산의 수학적 한계로 인해 **단독 시그널을 생성할 수 없다.**

```
volume_breakout 최대 기여 = weight(0.12) × max_score(0.50) = 0.06
min_score_for_signal (임계값)                                = 0.43
격차(Gap)                                                    = 0.37
```

`volume_breakout` 단독 후보는 0.43 임계값에 절대 도달하지 못한다. 현재 이 탐지기는 다른 탐지기가 이미 발동한 후보의 점수를 보강(boost)하는 역할만 수행할 뿐, 새로운 소형주를 독립적으로 수면 위로 올리지(surface) 못한다.

이는 SPEC-AI-062의 도입 목적("뉴스 없이 거래량만으로 소형주 탐지")을 사실상 무력화한다.

## 해결 전략 (Solution Strategy)

이미 검증된 우회 경로 패턴(`immediate_disclosure_bypass_threshold`, `strong_single_bypass_threshold`)과 동일한 구조로 `volume_breakout` 전용 우회 경로를 추가한다. 후보의 `volume_breakout_score`가 설정 가능한 임계값(기본 0.30) 이상이면 앙상블 임계값을 우회하여 독립 시그널로 저장한다.

## 환경 및 가정 (Environment & Assumptions)

- 대상 시스템: news-hive 백엔드 급등 예측 엔진 (`backend/app/services/surge_detector.py`)
- 운영 모드: 예측 기록 모드(SPEC-AI-043). 실제 매수는 비활성 상태이며 본 SPEC은 시그널 생성/기록 경로만 다룬다.
- 기존 우회 경로 패턴이 동일 함수(`compute ensemble + threshold filter loop`) 내에 이미 2종 존재하며, 본 SPEC은 이를 reference로 삼는다.
- `detect_volume_breakout()`는 각 후보에 `volume_breakout_score`와 `active_detectors=["volume_breakout"]`를 부여하여 `list[SurgeCandidate]`를 반환한다(SPEC-AI-062 완료).
- 단독 `volume_breakout` 후보는 병합 루프(`merged[candidate.stock_code] = candidate`)를 통해 `merged` 딕셔너리에는 정상 진입하나, 앙상블 스코어링 단계에서 임계값에 도달하지 못해 `qualified`에서 탈락한다.
- `FundSignal`은 `volume_breakout_score` 컬럼을 이미 보유한다(SPEC-AI-062 완료).
- 시그널 메타데이터의 `surge_basis`는 `candidate.active_detectors`로부터 자동 파생된다(`surge_candidate_to_signal_metadata`).

## 요구사항 (Requirements — EARS 형식)

### Ubiquitous Requirements (상시 활성)

**REQ-063-002**: 시스템은 `volume_breakout` 우회 임계값(`volume_breakout_bypass_threshold`)을 `surge_detection.yaml`의 `volume_breakout` 설정 블록에서 **shall** 설정 가능하게 노출한다. 기본값은 0.30이다.

**REQ-063-007** (Optional/도출): `volume_breakout` 설정 블록의 `enabled: false`인 경우, 시스템은 우회 경로를 **shall not** 실행한다(탐지기 자체가 비활성이므로 후보가 없음).

### Event-Driven Requirements (트리거-응답)

**REQ-063-001**: **When** 후보의 `volume_breakout_score >= volume_breakout_bypass_threshold`(설정 가능, 기본 0.30)이고 해당 후보가 앙상블 임계값을 통과하지 못했을 **때**, 시스템은 해당 후보를 앙상블 `min_score_for_signal` 임계값을 우회시켜 `surge_basis=["volume_breakout"]`를 가진 `FundSignal`로 **shall** 저장한다.

**REQ-063-003**: **When** 후보가 우회 경로를 통해 자격을 획득(qualify)할 **때**, 시스템은 해당 후보의 `composite_score`를 앙상블 점수가 아닌 **자신의 `volume_breakout_score`로 shall** 설정하여 매수 실행 시점의 신뢰도를 정확히 반영한다.

### State-Driven Requirements (조건부 동작)

**REQ-063-006**: **While** `SurgePredictionEvaluation`의 precision/recall 평가가 수행되는 동안, 시스템은 `volume_breakout` 우회 시그널을 예측 후보(predicted candidates)로 **shall** 정확히 집계한다(제외하지 않는다).

### Unwanted Behavior Requirements (금지 동작)

**REQ-063-004**: **If** 후보가 이미 메인 앙상블 경로를 통해 자격을 획득한 상태라면, **then** 우회 경로는 해당 후보에 대해 **shall not** 중복 추가(double-count)하거나 점수를 인플레이션(inflation)시킨다.

**REQ-063-008** (Unwanted/도출): 우회 경로는 이미 다른 기존 우회 경로(immediate_disclosure / strong_single)를 통해 `qualified_codes`에 등록된 후보를 **shall not** 재처리한다.

### Optional Requirements (선택적 향상)

**REQ-063-005**: **Where** 자동 개선 루프(`surge_auto_improver.py`)가 동작하는 환경에서, 시스템은 `volume_breakout_bypass_threshold`를 `min_score_for_signal`과 유사한 방식으로 자동 개선 가능 파라미터로 **shall** 추적하며, 그 범위는 `[0.20, 0.45]`로 제한한다.

## 제외 사항 (Exclusions — What NOT to Build)

- `detect_volume_breakout()` 탐지 로직 자체의 변경 (거래량 비율 계산, baseline_days, confidence_denominator 등은 SPEC-AI-062 영역으로 동결).
- 앙상블 가중치(`ensemble.weights.volume_breakout = 0.12`) 변경. 본 SPEC은 우회 경로만 추가하며 가중치 재배분은 하지 않는다.
- 다른 탐지기(theme_cluster, volume_news_combo, disclosure_pattern, legacy, news_delayed, weekend_gap_up)의 우회 임계값 변경.
- 실제 매수 실행 활성화. 본 SPEC은 예측 기록 모드(SPEC-AI-043)를 유지한다.
- 새로운 DB 마이그레이션. `FundSignal.volume_breakout_score` 컬럼은 SPEC-AI-062에서 이미 추가됨.
- `composite_score` 컬럼의 스케일 정의 변경 또는 isotonic 캘리브레이션 도입(SPEC-AI-036 영역).
- 앙상블 합산 검증(`validate_ensemble_weights`) 로직 변경. 우회 경로는 가중치 합산과 무관하다.

## 의존성 및 영역 분리 (Dependencies & Ownership Boundaries)

- **선행 의존**: SPEC-AI-062 (volume_breakout 탐지기 + `FundSignal.volume_breakout_score` 컬럼).
- **참조 패턴**: SPEC-AI-018 (`immediate_disclosure_bypass_threshold`, `strong_single_bypass_threshold` 우회 경로) — 본 SPEC의 구현 reference.
- **영역 분리**: 본 SPEC은 우회 경로(bypass path)만 소유한다. 앙상블 가중치 자동 보정은 SPEC-AI-041, 확률 임계값은 SPEC-AI-029/038, 탐지기 로직은 SPEC-AI-062가 소유한다.
- **충돌 없음**: 본 SPEC이 추가하는 자동 개선 파라미터(`volume_breakout_bypass_threshold`)는 SPEC-AI-041이 소유한 `min_score_for_signal` 및 앙상블 가중치와 별개의 키이므로 충돌하지 않는다.

## 성공 기준 (Success Criteria)

- `volume_breakout_score >= 0.30`인 단독 후보가 최소 1건 이상 `surge_basis=["volume_breakout"]`로 `FundSignal` 저장됨이 확인된다.
- 메인 앙상블 경로 통과 후보의 시그널 수 및 점수가 우회 경로 추가 전후로 변동 없음(REQ-063-004 검증).
- `volume_breakout` 우회 시그널이 `SurgePredictionEvaluation` 분모(predicted)에 포함됨이 확인된다.
- 테스트 커버리지 85% 이상, 기존 surge 테스트 스위트 전량 통과.
