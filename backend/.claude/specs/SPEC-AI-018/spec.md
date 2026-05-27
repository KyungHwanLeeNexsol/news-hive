---
id: SPEC-AI-018
version: 0.1.0
status: implemented
created: 2026-05-27
updated: 2026-05-27
author: Nexsol
priority: high
issue_number: null
---

# SPEC-AI-018: 급등예측 신호 품질 개선

## HISTORY

- 2026-05-27 (v0.1.0): 최초 작성. SPEC-AI-017(앙상블 임계값 하이브리드 개선)의 후속.
  탐지기 상관성 문제, 과도한 우회 경로, 최근 급등 종목 재선정, 미사용 밸류에이션 데이터를
  5개 페이즈로 개선.

---

## Overview

급등예측 파이프라인은 매일 15:20 KST에 실행되어 `surge_candidate` 유형의 `FundSignal`
레코드를 생성하고, 다음 날 09:00 KST에 매매 서비스가 상위 5개 시그널을 매수한다.

본 SPEC은 신호 생성 단계(`surge_detector.py`, `fund_manager.py`)의 품질을 개선한다.
직전 SPEC인 SPEC-AI-017(앙상블 임계값 하이브리드 개선)은 레짐별 임계값,
강한 단일 신호 우회, 컨센서스 배율 강화를 도입했다. 이 과정에서 드러난 구조적
부작용 — 상관 탐지기의 컨센서스 과보상, 과도하게 낮은 우회 임계값, 최근 급등
종목의 재선정, 수집되었으나 미사용인 밸류에이션 데이터 — 를 교정한다.

이 SPEC은 **무엇을(WHAT)** 과 **왜(WHY)** 를 정의한다. 구체적인 함수 시그니처나
구현 세부는 Run 단계로 이연한다.

---

## Problem Statement

현재 시스템은 8개 탐지기로 구성된다.

- 1차 앙상블(4개): theme_cluster(35%), volume_news_combo(35%),
  disclosure_pattern(20%), legacy_detectors(10%)
- 컨센서스 배율: 활성 2개 = 1.30x, 활성 3개 이상 = 1.55x
- 우회 경로 2개: immediate_disclosure >= 0.70 임계 우회(하드코딩),
  strong_single_bypass >= 0.72 임계 우회
- 레짐별 임계값: BULL=0.38, SIDEWAYS=0.50, BEAR=0.52

식별된 문제는 다음과 같다.

1. **상관 탐지기 문제**: theme_cluster, volume_news_combo,
   (그리고 news_price_divergence 계열)는 모두 동일한 뉴스 이벤트에 반응한다.
   컨센서스 배율이 "독립성"이 아니라 "상관성"을 보상한다. 한 건의 핫뉴스가
   세 탐지기를 동시에 발동시켜 1.55x 배율을 받지만, 실제 신호의 독립적 근거는
   하나뿐이다.

2. **즉각 공시 우회 위험**: `_IMMEDIATE_BYPASS_THRESHOLD = 0.70` 이
   `surge_detector.py` 939행에 하드코딩되어 있다. 이 경로는 다른 어떤 탐지기의
   확인 없이도(zero confirmation) 시그널을 생성할 수 있다.

3. **강한 단일 신호 우회 임계값 과소**: `strong_single_bypass_threshold = 0.72`
   는 너무 낮아, 단일 theme/combo 신호가 모든 리스크 점검을 우회한다.

4. **최근 성과 페널티 부재**: 이미 급등한 종목(전일 상한가)이 다음 날 후보로
   선정된다. 급등 정점 직후 진입은 고점 매수 리스크가 크다.

5. **밸류에이션 데이터 미사용**: per, pbr, roe 값이 `fund_manager.py` 1684행
   부근에서 후보 dict에 수집되지만 필터로 전혀 사용되지 않는다. 극단적 고평가
   종목이 걸러지지 않는다.

6. **theme_cluster 가중치 과대**: 35% 가중치가 지배적이다. 핫테마 기간의
   뉴스 포화 시 과발화한다.

### 현재 코드 앵커 (검증 완료)

- `surge_detector.py:777` `compute_ensemble_score()` — 가중합 + 컨센서스 배율
- `surge_detector.py:795` `best_disclosure_score = max(pattern_score, immediate_disclosure_score)`
  — immediate_disclosure는 이미 가중합에 참여하면서 별도 우회 로직도 가짐(이중 참여)
- `surge_detector.py:805-812` 활성 탐지기 개수 계산(개별 탐지기 단위)
- `surge_detector.py:838` `gather_surge_candidates()` — 파이프라인 진입점
- `surge_detector.py:933` 앙상블 임계 통과 경로
- `surge_detector.py:939-944` 즉각 공시 우회 경로(하드코딩 0.70)
- `surge_detector.py:954-958` 강한 단일 신호 우회 경로(theme/combo >= 0.72)
- `fund_manager.py:1498` `_gather_leading_candidates()` — 레거시 탐지기, 재무 수집
- `fund_manager.py:1795` `candidate["price_5d_trend"]` 부착
- `fund_manager.py:1802-1803` `candidate["per"]`, `candidate["pbr"]` 부착
- `surge_detection.yaml:25` `min_news_sentiment: 0.3`
- `surge_detection.yaml:35-38` 앙상블 가중치
- `surge_detection.yaml:52` `strong_single_bypass_threshold: 0.72`

### 데이터 흐름 주의점

`compute_ensemble_score()`에 전달되는 `SurgeCandidate` 객체에는
`price_5d_trend`/`per`/`pbr` 필드가 없다. 이 값들은 레거시 후보 dict
(`legacy_candidates`)에 존재한다. `gather_surge_candidates()`는 레거시 후보를
인자로 받으므로(842행 `legacy_candidates`), 종목 코드 기준으로 dict 값을
조회하여 페널티 판정에 활용할 수 있다. Phase 2/3는 이 매핑을 사용한다.

---

## Requirements

### Phase 1 — 설정 조정 (저위험)

- **REQ-AI018-001**: `_IMMEDIATE_BYPASS_THRESHOLD` 를 하드코딩(0.70)에서
  설정값 `config.ensemble.immediate_disclosure_bypass_threshold` 로 이전하고,
  기본값을 0.85로 설정한다.

- **REQ-AI018-002**: `strong_single_bypass_threshold` 를 YAML에서 0.72 → 0.85로
  상향한다.

- **REQ-AI018-003**: `min_news_sentiment` 기본값을 YAML에서 0.3 → 0.5로 상향한다.

- **REQ-AI018-004**: 앙상블 가중치를 조정한다. `theme_cluster` 0.35 → 0.28,
  `legacy_detectors` 0.10 → 0.17. 가중치 합계는 반드시 1.00을 유지한다
  (volume_news_combo 0.35, disclosure_pattern 0.20 유지 → 0.28+0.35+0.20+0.17=1.00).

### Phase 2 — 최근 급등 페널티 (핵심 개선)

- **REQ-AI018-005**: `gather_surge_candidates()` 에서 후보를 `qualified` 목록에
  추가하기 **전에** `price_5d_trend` 기반 점수 페널티를 적용한다.
  - `price_5d_trend > 20.0%` → `score *= 0.6`
  - `price_5d_trend > 12.0%` (20.0% 이하) → `score *= 0.8`
  - 모든 자격 경로에 적용: 앙상블 통과, 즉각 공시 우회, 강한 단일 신호 우회.
  - `price_5d_trend` 가 None 또는 누락이면 페널티를 건너뛴다(자격 박탈하지 않음).

### Phase 3 — 밸류에이션 부적격 필터 (가산 필터)

- **REQ-AI018-006**: YAML에 신규 `valuation_disqualifiers` 키로 부적격 임계값
  설정을 추가한다(`max_per`, `max_pbr` 등).

- **REQ-AI018-007**: `_gather_leading_candidates()` (fund_manager.py)에서 재무
  데이터가 후보에 부착된 이후, `per > 500` 또는 `pbr > 30` 인 후보를 제외한다.

- **REQ-AI018-008**: per/pbr 데이터가 None 또는 0(미수집)이면 부적격 처리하지
  않는다. 데이터 누락은 고평가가 아니다(missing data != overvalued).

### Phase 4 — 컨센서스 독립성 교정 (구조적)

- **REQ-AI018-009**: `compute_ensemble_score()` 에서 컨센서스 카운트를 위해
  탐지기를 카테고리(그룹)로 묶는다.
  - "news" 그룹: theme_cluster_score + combo_score (둘 다 뉴스 기반)
  - "disclosure" 그룹: best_disclosure_score
  - "technical" 그룹: legacy_score
  - 개별 탐지기가 아니라 활성 **그룹** 수로 컨센서스 배율을 결정한다.
  - 그룹은 그룹 내 임의 점수가 0보다 크면 "활성"으로 간주한다.
  - 최대 3개 그룹 → 최대 배율 1.55x(현재와 동일하나, 3개의 독립 차원으로 획득).

### Phase 5 — 공매도/대차잔고 연동 (향후, 범위 외)

- **REQ-AI018-010**: 공매도/대차잔고(short interest) 연동은 향후 개선 항목으로
  추적한다. 후속 SPEC-AI-019로 분리한다. 본 SPEC에서는 구현하지 않는다.

---

## Acceptance Criteria

상세 시나리오는 `acceptance.md` 참조. 핵심 EARS 기준은 다음과 같다.

- WHEN 후보의 `price_5d_trend` 가 20%를 초과하면 THE SYSTEM SHALL 앙상블 점수에
  0.60 배율을 적용한다.
- WHEN 후보의 `price_5d_trend` 가 12% 초과 20% 이하이면 THE SYSTEM SHALL 앙상블
  점수에 0.80 배율을 적용한다.
- WHEN `immediate_disclosure_score` 가 0.85 미만이면 THE SYSTEM SHALL 즉각 공시
  우회 경로로 앙상블 임계값을 우회하지 않는다.
- WHEN per > 500 또는 pbr > 30 이고 해당 데이터가 존재하면 THE SYSTEM SHALL 해당
  후보를 자격 목록에서 제외한다.
- WHEN theme_cluster 와 combo_score 가 모두 활성이지만 disclosure 와 legacy 가
  비활성이면 THE SYSTEM SHALL 컨센서스 1.00 배율을 적용한다(단일 그룹 활성,
  1.30 배율이 아님).

---

## Implementation Notes

- **설정 우선 변경**: Phase 1은 YAML 값 조정과 Pydantic 모델 필드 추가
  (`surge_settings.py`)로 구성되며 위험도가 가장 낮다. 신규 키
  `immediate_disclosure_bypass_threshold`(REQ-001),
  `valuation_disqualifiers`(REQ-006)는 `surge_settings.py` Pydantic 모델에
  필드를 추가해야 한다.
- **가중치 합계 불변식**: REQ-004 적용 후 4개 가중치 합이 정확히 1.00 인지
  테스트로 검증한다(부동소수점 오차 허용 범위 내).
- **페널티 적용 위치**: REQ-005는 `gather_surge_candidates()` 의 세 자격 경로
  (933행 앙상블, 942행 즉각 공시 우회, 958행 강한 단일 신호 우회) 모두에서
  일관되게 적용되어야 한다. 정렬에 사용되는 점수(969행)와 metadata에 기록되는
  점수(`surge_candidate_to_signal_metadata`, 983행)도 페널티 반영 여부를
  Run 단계에서 결정한다.
- **데이터 매핑**: `price_5d_trend`/`per`/`pbr` 는 `SurgeCandidate` 가 아닌
  레거시 후보 dict에 있다. 종목 코드 기준 매핑(legacy_candidates → score lookup)이
  필요하다. Phase 3는 `_gather_leading_candidates()` 내부에서 제외하므로 별도
  매핑 없이 dict를 직접 사용한다.
- **컨센서스 그룹화 회귀**: REQ-009는 기존 SPEC-AI-014/017의 컨센서스 동작을
  변경한다. 단일 뉴스 이벤트가 1.55x를 받던 사례가 1.00x로 떨어지므로,
  기존 통과 후보 수가 감소할 수 있다. 회귀 테스트로 점수 변화 방향을 확인한다.
- **스테일 주석 정리**: `surge_detector.py:783` 의 `@MX:NOTE` 주석은
  "1.00/1.15/1.30"으로 남아 있으나 실제 값은 1.30/1.55(SPEC-AI-017)이다.
  REQ-009 구현 시 그룹 기반 컨센서스로 주석을 갱신한다.
- **검증 명령**: `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"`
  (CLAUDE.local.md 기준).

---

## Out of Scope (What NOT to Build)

- **공매도/대차잔고(short interest) 연동**: REQ-AI018-010. 후속 SPEC-AI-019로
  분리. 본 SPEC에서 구현하지 않는다.
- **레짐별 임계값 재조정**: BULL/SIDEWAYS/BEAR 임계값(0.38/0.50/0.52)은
  SPEC-AI-017에서 정의된 값을 그대로 유지한다. 본 SPEC에서 변경하지 않는다.
- **신규 탐지기 추가**: news_price_divergence 등 신규 탐지기 도입은 범위 외.
  기존 8개 탐지기의 가중치/그룹화/우회 로직만 교정한다.
- **매매 서비스 변경**: `surge_trading_service.py` 의 매수 로직(상위 5개 선정,
  position_pct, BUY_CUTOFF 등)은 변경하지 않는다. 신호 생성 단계만 다룬다.
- **roe 기반 필터**: 밸류에이션 부적격 필터는 per/pbr만 사용한다. roe는 향후
  검토 항목으로 남긴다.
- **백테스트 파이프라인 변경**: `backtest` 설정 및 평가 로직은 변경하지 않는다.

---

## References

- 직전 SPEC: SPEC-AI-017 (앙상블 임계값 하이브리드 개선) — 커밋 `a53c326`
- 관련 SPEC: SPEC-AI-014 (앙상블 파이프라인, 컨센서스 배율 도입)
- 후속 SPEC: SPEC-AI-019 (공매도/대차잔고 연동, 미생성)
- 주요 파일:
  - `backend/app/services/surge_detector.py`
  - `backend/app/services/fund_manager.py`
  - `backend/app/surge_config/surge_detection.yaml`
  - `backend/app/surge_config/surge_settings.py`
