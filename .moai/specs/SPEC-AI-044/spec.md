# SPEC-AI-044: 비테마 기술적 모멘텀 급등 탐지기

## Overview

**목표**: 뉴스/공시 촉매 없이 순수 수급·섹터순환·기술적 돌파만으로 급등하는 종목을 포착하는
6번째 탐지기 `detect_technical_momentum_surge()`를 추가한다. 기존 5개 탐지기가 구조적으로
포착할 수 없는 "비테마 급등"을 메우는 것이 핵심이다.

**Status**: DRAFT
**Date**: 2026-06-11
**Author**: manager-spec
**Priority**: High
**Depends on**: SPEC-AI-012 (탐지기/앙상블 기반), SPEC-AI-018 (그룹 컨센서스), SPEC-AI-039 (5번째 가중치 news_delayed 추가 선례)

---

## Problem / Motivation

### 현재 시스템의 사각지대

기존 `surge_detector.py`의 5개 탐지기는 모두 **뉴스 또는 공시 촉매**에 의존한다.

| 탐지기 | 가중치 | 발동 조건 (촉매) |
|--------|-------|-----------------|
| theme_cluster | 0.25 | 20개 테마 키워드 뉴스 클러스터 |
| volume_news_combo | 0.32 | 거래량 z-score 스파이크 + **긍정 뉴스** |
| disclosure_pattern | 0.18 | 과거 급등률 높은 공시 유형 발생 |
| news_delayed | 0.15 | 기술이전/임상/수주 등 고임팩트 뉴스 |
| legacy_detectors | 0.10 | 선행 기술 지표(_gather_leading_candidates) |

`volume_news_combo`는 거래량을 보지만 **긍정 뉴스가 동반되어야만** 발동한다
(`positive_news_stocks`가 비면 즉시 `return []`). 따라서 뉴스 없는 순수 거래량 돌파는
이 탐지기로 잡히지 않는다.

### 실측 증거 (2026-06-10)

2026-06-10 하루에 +10% 이상 급등 종목이 93개 발생했으나, 다음과 같은 종목은
기존 탐지기 중 어느 것도 시그널을 생성하지 못했다.

| 종목 | 섹터 | 등락률 | 미포착 사유 |
|------|------|-------|-------------|
| STX그린로지스 | 물류 | +30% | 테마 뉴스 없음, 공시 없음 |
| 마니커 | 음식료 | +30% | 테마 뉴스 없음, 공시 없음 |
| 코미코 | 반도체 코팅 | +29% | 테마 뉴스 트리거 없음 |
| 뷰티스킨 | 화장품 | +28% | 테마 뉴스 트리거 없음 |

이들은 모두 **수급(거래량 폭증) + 기술적 패턴(신고가 돌파, 연속 양봉, 상대강도)**으로
급등했으며, 뉴스/공시 촉매가 선행하지 않았다. 기존 시스템은 구조적으로 이 패턴을
탐지할 수 없으므로, 뉴스에 의존하지 않는 독립 탐지기가 필요하다.

### 데이터 가용성 (검증 완료 2026-06-11)

- `naver_finance.fetch_stock_price_history_sync(code, pages=N)`는 일봉 `PriceRecord`
  (`date/close/open/high/low/volume`) 목록을 반환한다. **OHLCV가 모두 존재**하므로
  연속 양봉(close>open), 신고가 비교(high), 거래량 평균 계산이 모두 가능하다.
- `pages` 1개당 약 10 거래일. 20일 평균 거래량은 `pages=3`(약 30일)으로 충분하다.
- **52주 신고가**는 약 250 거래일이 필요하여 `pages≈25`의 무거운 조회가 발생한다
  (Risk 섹션 R-002 참조). 본 SPEC은 이를 후보 사전 필터 통과 종목에만 제한 적용한다.
- KOSDAQ 지수 등락률은 `_fetch_intraday_change_for_cascade()` 패턴(네이버 모바일 API)
  또는 지수 코드 가격 히스토리로 조회한다.
- `Stock.market_cap` 단위는 **억원**이다 (DB 기준). 원 단위 config 값은 억원으로 환산한다.

---

## EARS Requirements

### REQ-044-001 — 신규 탐지기 함수 (Ubiquitous)

The system **shall** provide a new function `detect_technical_momentum_surge(db, config)`
in `backend/app/services/surge_detector.py` that returns a list of `SurgeCandidate`
objects with a new `technical_momentum_score` field populated, without requiring any
news or disclosure records as input.

**Acceptance**:
- 함수 시그니처: `detect_technical_momentum_surge(db: Session, config: SurgeDetectionConfig) -> list[SurgeCandidate]`
- `SurgeCandidate` 데이터클래스에 `technical_momentum_score: float = 0.0` 필드 추가
- 뉴스/공시 테이블을 입력으로 받지 않음 (가격 히스토리 + Stock 메타데이터만 사용)
- DB/API 실패 시 빈 목록 반환 (기존 탐지기 예외 격리 패턴 준수)

### REQ-044-002 — 순수 거래량 돌파 컴포넌트 (State-Driven)

**While** a stock's current-day volume divided by its 20-day average volume is greater
than or equal to `volume_breakout_multiplier`, the detector **shall** add the
volume-breakout component to that stock's `technical_momentum_score`, **without**
checking for any accompanying news (distinguishing it from `volume_news_combo`).

**Acceptance**:
- `volume_ratio = today_volume / mean(history_volumes[1:21])` (오늘 제외 20일 평균)
- `volume_ratio >= config.technical_momentum.volume_breakout_multiplier` (기본 5.0) 충족 시 컴포넌트 점수 가산
- 뉴스 조회 코드 경로 없음
- 20일치 미만 데이터인 종목은 스킵

### REQ-044-003 — 가격 모멘텀(상대강도) 컴포넌트 (State-Driven)

**While** a stock has gained at least `momentum_min_gain_pct` over the last
`momentum_days` trading days **and** the KOSDAQ index over the same window is flat or
negative, the detector **shall** add the relative-strength component to the score.

**Acceptance**:
- `stock_gain = (close[0] - close[momentum_days]) / close[momentum_days] * 100`
- KOSDAQ 동일 창 수익률 `kosdaq_gain` 조회
- `stock_gain >= config.technical_momentum.momentum_min_gain_pct` (기본 3.0) AND `kosdaq_gain <= 0` 충족 시 컴포넌트 가산
- KOSDAQ 조회 실패 시 상대강도 컴포넌트는 0 처리(다른 컴포넌트는 계속 평가)

### REQ-044-004 — 52주 신고가 근접 컴포넌트 (State-Driven)

**While** a stock's current price is within `high52w_proximity_pct` of its 52-week high
**and** the volume-breakout condition (REQ-044-002) is also met, the detector **shall**
add the 52-week-high-proximity component to the score.

**Acceptance**:
- `high_52w = max(high for record in 52주_히스토리)`
- `proximity = (high_52w - current_price) / high_52w * 100`
- `proximity <= config.technical_momentum.high52w_proximity_pct` (기본 5.0) AND 거래량 돌파(REQ-044-002) 동시 충족 시 가산
- 52주 데이터를 얻지 못하면 이 컴포넌트는 0 처리(탐지기는 다른 컴포넌트로 진행)

### REQ-044-005 — 연속 상승일 컴포넌트 (State-Driven)

**While** a stock shows `consecutive_up_days` or more consecutive trading days of price
increase with non-decreasing volume, the detector **shall** add the consecutive-up-days
component to the score.

**Acceptance**:
- 최근 N일 동안 `close[i] > close[i+1]` (최신순 인덱스) 연속 충족 일수 계산
- 연속 양봉 구간의 거래량이 비감소(증가 추세) 여부 확인
- 연속 일수 `>= config.technical_momentum.consecutive_up_days` (기본 3) 충족 시 가산

### REQ-044-006 — 시가총액 필터 (Unwanted Behavior)

**If** a stock's market cap is below `min_market_cap_krw` or above `max_market_cap_krw`,
**then** the detector **shall not** emit a candidate for that stock (중·소형주 집중,
대형주 제외).

**Acceptance**:
- `Stock.market_cap`(억원) 를 config 원 단위 값과 억원 환산 비교
- `min_market_cap_krw`(기본 500억) 미만 또는 `max_market_cap_krw`(기본 5조) 초과 종목은 후보에서 제외
- `market_cap`이 NULL인 종목은 제외 (필터 통과 불가)

### REQ-044-007 — 점수 산출 규칙 (Ubiquitous)

The detector **shall** compute `technical_momentum_score` as a base score plus the sum
of present component scores, capped at a maximum so a single technical signal cannot
dominate the ensemble.

**Acceptance**:
- `base_score = 0.3` (최소 조건 — 거래량 돌파 1개 충족 시 부여)
- 각 추가 컴포넌트(REQ-044-003/004/005) present 시 부분 점수 가산
- 최종 점수 `min(0.8, base + components)` — **최대 0.8 캡**
- 최소 조건(거래량 돌파)조차 미충족이면 후보 미생성 (score=0)

### REQ-044-008 — 설정 스키마 (Ubiquitous)

The system **shall** define a new Pydantic model `TechnicalMomentumConfig` in
`backend/app/surge_config/surge_settings.py` and attach it to `SurgeDetectionConfig`.

**Acceptance**:
- `TechnicalMomentumConfig(BaseModel)` 필드: `enabled: bool = True`,
  `volume_breakout_multiplier: float = 5.0`, `momentum_days: int = 5`,
  `momentum_min_gain_pct: float = 3.0`, `high52w_proximity_pct: float = 5.0`,
  `consecutive_up_days: int = 3`, `min_market_cap_krw: int = 50000000000`,
  `max_market_cap_krw: int = 5000000000000`
- `SurgeDetectionConfig`에 `technical_momentum: TechnicalMomentumConfig` 추가
- `enabled=False`이면 `detect_technical_momentum_surge`가 즉시 빈 목록 반환

### REQ-044-009 — YAML 설정값 (Ubiquitous)

The system **shall** add a `technical_momentum` section to
`backend/app/surge_config/surge_detection.yaml` with the default values from REQ-044-008.

**Acceptance**:
- `surge_detection.yaml`에 `technical_momentum:` 키 추가, 8개 값 명시
- `get_surge_config()`가 해당 섹션을 `TechnicalMomentumConfig`로 정상 파싱
- 코드 변경 없이 YAML 조정만으로 임계값 운영 튜닝 가능

### REQ-044-010 — 앙상블 통합 (Event-Driven)

**When** `compute_ensemble_score()` aggregates detector scores, the system **shall**
include `technical_momentum_score` in the `technical` detector group alongside
`legacy_score`, taking the best score within the group for the consensus multiplier.

**Acceptance**:
- `gather_surge_candidates()`가 `detect_technical_momentum_surge` 결과를 종목코드 기준 병합
- `compute_ensemble_score()`의 `weighted_sum`에 `w.technical_momentum * candidate.technical_momentum_score` 항 추가
- `detector_groups["technical"] = [candidate.legacy_score, candidate.technical_momentum_score]` (그룹 내 best가 컨센서스 카운트에 반영)
- 컨센서스 배율 로직(2그룹 ×1.30, 3그룹 ×1.55)은 무변경 — 그룹 멤버만 확장

### REQ-044-011 — 가중치 재조정 (Ubiquitous)

The system **shall** rebalance ensemble weights so the total remains exactly 1.0 after
adding the new `technical_momentum` weight, and `validate_ensemble_weights` **shall**
include the new weight in its sum check.

**Acceptance**:
- 신규 가중치 배분: theme=0.23, combo=0.29, disclosure=0.16, legacy=0.08, news_delayed=0.13, technical_momentum=0.11 (합 = 1.00)
- `EnsembleWeightsConfig`에 `technical_momentum: float = 0.0` 필드 추가
- `validate_ensemble_weights`의 합산식에 `+ w.technical_momentum` 추가, 합 1.0(허용오차 ±0.001) 검증
- `surge_detection.yaml` `weights:` 6개 값으로 갱신

### REQ-044-012 — 평가 기준 (Event-Driven)

**When** the daily evaluation loop (SPEC-AI-041/043) measures recall, the system
**shall** track whether the technical momentum detector improves non-theme surge recall,
targeting detection of at least 20% of non-theme surge stocks on a backtest window.

**Acceptance**:
- "비테마 급등 종목" 정의: 당일 +10% 이상 급등했고 동일 종목에 당일 테마/공시/뉴스 시그널이 없던 종목
- 백테스트 또는 일일 평가에서 `technical_momentum` 단독 발동으로 포착된 비테마 급등 종목 수 / 전체 비테마 급등 종목 수 >= 0.20 목표
- 측정값을 surge 평가 리포트(SPEC-AI-041 텔레그램/엔드포인트)에 노출
- 목표 미달이어도 차단 아님 — 관측·튜닝 지표로 사용

---

## Exclusions (What NOT to Build)

- **ML/통계 예측 모델**: 회귀·분류·신경망 기반 급등 확률 예측은 범위 외. 본 SPEC은 규칙 기반 컴포넌트 합산만 수행한다. (백엔드에 numpy/scipy/sklearn 없음 — 순수 Python만)
- **실시간 틱/분봉 데이터**: 일봉 OHLCV만 사용한다. 분봉·틱 단위 수급 분석은 별도 데이터 파이프라인이 필요하므로 범위 외.
- **MACD/RSI/볼린저밴드 등 보조지표 산출**: 사용 가능한 OHLCV로 계산 가능한 단순 비율(거래량비, 수익률, 신고가 근접)만 사용. MACD/RSI/BB 등 별도 지표 라이브러리·계산은 범위 외.
- **신규 매수 실행 로직 변경**: `execute_buy_orders()`, 매수 컷오프(`BUY_CUTOFF`), 포지션 수 제한 등 실행 단계는 무변경. 본 SPEC은 시그널 생성에만 관여한다.
- **기존 탐지기 가중치 외 로직 수정**: theme_cluster/combo/disclosure/news_delayed 내부 로직은 손대지 않는다. 가중치 값만 재조정한다.

---

## Architecture (text-based)

```
fund_manager._gather_surge_candidates() (10:00 / 15:20 KST)
  └─ gather_surge_candidates(db, recent_news, config, legacy_candidates, market_regime)
       ├─ detect_theme_news_cluster()          (기존)
       ├─ detect_volume_surge_news_combo()      (기존)
       ├─ detect_disclosure_surge_pattern()     (기존)
       ├─ detect_immediate_disclosure_signal()  (기존)
       ├─ detect_news_delayed_response()        (기존)
       └─ detect_technical_momentum_surge(db, config)   ← 신규 (REQ-044-001)
            │
            ├─ 1. 시총 필터: Stock.market_cap ∈ [500억, 5조]  (REQ-044-006)
            │      → 후보 종목 코드 목록 확보 (가격 API 호출 전 사전 축소)
            │
            ├─ 2. 종목별 가격 히스토리 조회
            │      fetch_stock_price_history_sync(code, pages=3)  → 거래량/연속양봉용
            │      (52주 컴포넌트 평가 대상만 pages≈25 추가 조회 — REQ-044-004, Risk R-002)
            │
            ├─ 3. 컴포넌트 평가
            │      ├─ volume_breakout   (REQ-044-002)  필수 — 미충족 시 후보 탈락
            │      ├─ price_momentum    (REQ-044-003)  KOSDAQ 상대강도
            │      ├─ high52w_proximity (REQ-044-004)  거래량 돌파 동반 조건
            │      └─ consecutive_up    (REQ-044-005)
            │
            └─ 4. 점수 산출: min(0.8, 0.3 + Σcomponents)  (REQ-044-007)
                   → SurgeCandidate(technical_momentum_score=...)

  병합(merged) → compute_ensemble_score()  (REQ-044-010)
       weighted_sum += w.technical_momentum * technical_momentum_score
       detector_groups["technical"] = [legacy_score, technical_momentum_score]
       → 컨센서스 배율 → min_score_for_signal 필터 → surge_candidate 시그널 생성
```

대략 100~150 라인 규모의 단일 함수 + 컴포넌트 계산 헬퍼로 구현한다.

---

## Risks & Dependencies

| ID | 항목 | 내용 / 완화책 |
|----|------|--------------|
| R-001 | 가격 API 부하 | 시총 필터를 가격 조회 **이전**에 적용해 후보 수를 줄인다. 기존 탐지기처럼 상위 N개 캡(예: 30개)을 적용해 timeout(과거 hang 이력)을 방지한다. |
| R-002 | 52주 신고가 데이터 비용 | `pages≈25` 조회는 무겁다. 거래량 돌파+모멘텀 사전 통과 종목에만 52주 조회를 제한 적용한다. 데이터 미확보 시 해당 컴포넌트만 0 처리하고 탐지기는 계속 진행. |
| R-003 | KOSDAQ 지수 조회 의존 | 상대강도(REQ-044-003)는 KOSDAQ 동일 창 수익률에 의존. 조회 실패 시 컴포넌트 0 처리(탐지기 자체는 실패하지 않음). |
| R-004 | 비테마 급등의 추격매수 위험 | 거래량 돌파 종목은 이미 급등 후일 수 있다. base 0.3 + 캡 0.8로 단독 영향력을 제한하고, 컨센서스 미충족 단독 시그널은 기존 `min_score_for_signal`(0.45) 및 적응형 임계값(SPEC-AI-029)이 추가로 거른다. |
| R-005 | 가중치 합 검증 회귀 | `validate_ensemble_weights` 수정 누락 시 기존 테스트가 1.0 합 위반으로 실패. REQ-044-011 수용 기준에 검증식 수정 포함. |
| DEP-1 | `naver_finance.fetch_stock_price_history_sync()` | OHLCV 일봉 히스토리 제공원. 52주는 `pages` 상향 필요. |
| DEP-2 | `SurgeCandidate` / `compute_ensemble_score` / `gather_surge_candidates` | 신규 필드·그룹·병합 통합 지점 (surge_detector.py). |
| DEP-3 | `EnsembleWeightsConfig` / `SurgeDetectionConfig` / `validate_ensemble_weights` | 가중치·설정 스키마 (surge_settings.py). |
| DEP-4 | SPEC-AI-041 / SPEC-AI-043 평가 루프 | REQ-044-012 recall 측정 노출 지점. |

---

## Out of Scope Conflicts Check

- **거래량 관련 중복 우려**: `detect_volume_anomaly_dormant_stocks`(SPEC-AI-022)는 *비활성 종목*의
  거래량 이상을 보고 별도 `volume_anomaly` 시그널을 생성한다. 본 탐지기는 *활성·중소형주*의
  거래량 돌파 + 기술적 패턴을 **앙상블 점수 컴포넌트**로 통합한다는 점에서 목적과 출력 경로가
  다르다(별도 signal_type 생성이 아니라 surge_candidate 앙상블 기여). 두 기능은 공존한다.
- **combo와의 차별점**: `volume_news_combo`는 긍정 뉴스 필수. 본 탐지기는 뉴스 무관 — 동일 종목이
  양쪽에 잡히면 news 그룹/technical 그룹으로 분리 카운트되어 컨센서스 배율이 자연스럽게 강화된다.
