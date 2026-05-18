---
id: SPEC-AI-014
version: 1.0.0
status: Planned
created: 2026-05-18
updated: 2026-05-18
author: MoAI
priority: High
issue_number: 0
title: 급등 시그널 스코어링 고도화 (Surge Signal Scoring Enhancement)
tags: [surge-detection, scoring, ensemble, theme-cluster, runtime-filter, signal-quality]
dependencies: [SPEC-AI-012, SPEC-AI-013]
---

# SPEC-AI-014: 급등 시그널 스코어링 고도화

> **ID 안내**: 사용자는 "SPEC-AI-013"으로 요청하였으나, `SPEC-AI-013`은 이미 *"Surge Prediction Paper Trading Portfolio"* (Completed, 2026-05-07)에 할당되어 있어 다음 가용 번호인 **SPEC-AI-014**로 발급하였습니다. (`SPEC-AI-015`는 별도 SPEC으로 이미 사용 중)

## HISTORY

- 2026-05-18 (v1.0.0): 초기 SPEC 작성 — 급등 시그널 ensemble 스코어링 차별성 부족 및 런타임 필터 차단 문제 해결을 위한 6대 요구사항 정의

---

## 0. 배경 및 목적 (Background)

### 0.1 배경

NewsHive 백엔드의 급등 탐지 시스템(`surge_detector.py`)은 4개의 detector를 ensemble 방식으로 결합하여 `surge_candidate` 시그널을 산출한다. 그러나 현재 운영 환경에서 다음 3가지 구조적 문제로 인해 시그널이 거의 매수 후보로 진입하지 못하고 있다.

**문제 1 — theme_cluster 차별성 없음**:
- `theme_cluster_score = min(1.0, theme_article_count/10) * sector_relevance`
- `theme_article_count`는 종목이 아닌 **테마 단위 기사 수**이므로, 동일 섹터의 442개 종목이 전부 동일한 0.25점을 받음
- 결과적으로 종목 간 변별력 부재

**문제 2 — volume_news_combo z-score 과도하게 엄격**:
- 거래량 z-score > 2.5 (상위 0.6%) 요구
- 거의 발화하지 않고 DEBUG 로그로 skip → ensemble 기여 0

**문제 3 — 런타임 필터가 단일 detector 시그널 전부 차단**:
- `surge_trading_service.get_today_signals()`: `if len(active_detectors) < 2 and probability < 0.40: continue`
- theme_cluster만 발화하는 현실에서 최대 점수 0.25 → 모든 시그널이 필터링됨 → **0건 매수**

### 0.2 목적

종목별 정보(개별 기사·가격·감성)를 ensemble 스코어링에 반영하여 변별력을 확보하고, 다중 detector 합의(consensus) 보너스로 신호 품질을 강조하며, 과열·낙폭 종목을 사전 차단함으로써 **실제 매수 후보를 일별 ≥1건 안정적으로 산출**한다.

### 0.3 비즈니스 가치

- 급등예측 모의투자 포트폴리오(SPEC-AI-013)의 실거래 검증 데이터 확보
- 시그널 정확도 모니터링 가능 (현재 0건 → 측정 불가 상태 해소)
- 과열주 진입 차단으로 모의 자산 보존

---

## 1. 영향 범위 (Affected Files)

| 파일 | 변경 성격 |
|---|---|
| `backend/app/services/surge_detector.py` (632 LOC) | theme_cluster 산식 전면 개편 (REQ-001~003), consensus 보너스 추가 (REQ-004) |
| `backend/app/surge_config/surge_detection.yaml` | ensemble weights 재조정 (REQ-006) |
| `backend/app/services/surge_trading_service.py` (684 LOC) | 가격 모멘텀 사전 필터 (REQ-005), 단일 detector 통과 조건 완화 |
| `backend/app/services/fund_manager.py` | 호출부 호환성 확인 (변경 최소) |

---

## 2. 요구사항 (Requirements, EARS 형식)

### REQ-AI014-001: 종목 단위 뉴스 개인화 (Stock-Level News Personalization)

**WHEN** `surge_detector`가 특정 종목에 대해 `theme_cluster_score`를 계산할 때, 시스템은 SHALL 해당 종목을 **직접 언급한 기사 수**를 기반으로 추가 점수를 산출한다.

- **현재**: `theme_cluster_score = min(1.0, theme_article_count/10) * sector_relevance`
  → 테마 단위 점수만 반영 → 모든 종목 동일 점수

- **변경 후 산식**:
  - `theme_base_score = min(1.0, theme_article_count / 10)` (기존 유지)
  - `stock_article_score = min(1.0, stock_specific_article_count / 5)` (5건 이상 = 1.0)
  - **종목 특화 기사가 1건 이상 존재 시**:
    `theme_cluster_score = (theme_base_score * 0.6) + (stock_article_score * 0.4)`
  - **종목 특화 기사가 0건일 때 (섹터 추종만)**:
    `theme_cluster_score = theme_base_score * 0.5`
  - 최종적으로 `sector_relevance`를 곱한다 (기존과 동일).

**WHERE** 종목명·종목코드 매칭 로직이 이미 `surge_detector` 내 기사 분류에 존재한다면 그 로직을 재사용한다. **IF** 종목 매칭 모듈이 존재하지 않으면, **THEN** 시스템은 기사 제목·본문에 종목명 또는 종목코드가 포함된 경우를 stock-specific로 분류한다.

**수락 기준**:
- 동일 테마 내에서 stock-specific 기사 3건 이상 보유 종목은 0건 종목 대비 `theme_cluster_score` ≥ 20% 높음
- 단위 테스트: 합성 데이터(기사 3건 + 5건 + 10건)로 점수 단조 증가 검증

---

### REQ-AI014-002: theme_cluster 경량 거래량 보너스 (Lightweight Volume Bonus)

**WHEN** `theme_cluster` 후보 종목의 점수를 계산할 때, 시스템은 SHALL 직전 거래일 대비 가격 변동률을 조회하여 **3% 초과 시 +0.10 보너스**를 가산한다.

- **현재**: `theme_cluster`는 거래량·가격 변동을 전혀 참조하지 않음 → 거래량 z-score 산출 불요

- **변경 후 동작**:
  - 각 후보 종목에 대해 `abs(current_price - price_1d_ago) / price_1d_ago` 계산
  - 변동률 > 0.03 (3%)이면: `theme_cluster_score += 0.10` (weight 곱셈 전)
  - 가격 조회 실패(API 오류·종목코드 없음 등) 시 **graceful fallback**: 보너스 없이 진행 (필터링 금지)

**WHERE** 가격 조회는 기존 Naver finance 모듈(`fetch_current_price`, SPEC-AI-004에서 도입) 또는 등가의 사기 캐시(intra-run cache) 인프라를 재사용한다.

**IF** 정규장 시간 외에 실행되어 1일 전 가격이 부재한 경우, **THEN** 시스템은 SHALL 가장 최근 종가 기준으로 변동률을 계산한다.

**수락 기준**:
- 활발한 거래일(coverage 종목 ≥ 50개)에서 최소 1개 이상의 `theme_cluster` 종목이 0.35점 이상(0.25 + 보너스)에 도달
- 가격 API 50% 실패 시뮬레이션에서도 시스템은 정상 동작(예외 없이 점수 산출)

---

### REQ-AI014-003: 뉴스 감성 통합 (News Sentiment Integration)

**WHEN** `theme_cluster_score` 산출 시 종목 특화 기사가 1건 이상 존재할 때, 시스템은 SHALL 기존 `_positive_sentiment_score()` 함수를 이용해 평균 긍정 점수를 계산하고 ensemble 점수에 곱셈 인자로 반영한다.

- **현재**: `theme_cluster`는 sentiment 라벨을 무시함

- **변경 후 동작**:
  - `avg_sentiment = mean(_positive_sentiment_score(a.sentiment) for a in stock_articles)`
  - `sentiment_factor = 0.8 + (0.4 * avg_sentiment)` → 결과 범위 0.8 ~ 1.2
  - `theme_cluster_score *= sentiment_factor`
  - 종목 특화 기사가 0건인 경우 본 절은 미적용 (factor = 1.0)

**WHILE** 기사가 `neutral`/`unknown`/`None`인 경우, `_positive_sentiment_score` 반환값에 의거하여 약한 감점(×0.8 수렴)을 부여한다.

**수락 기준**:
- `positive` 또는 `strong_positive` 기사 비율 ≥ 50%인 종목은 neutral 종목 대비 최종 점수 ≥ 10% 높음
- 단위 테스트: `[positive, positive, neutral]` vs `[neutral, neutral, neutral]` 입력에서 factor 차이 ≥ 0.15

---

### REQ-AI014-004: 다중 Detector 합의 보너스 (Multi-Detector Consensus Bonus)

**WHEN** ensemble 점수 계산이 완료되어 가중합(weighted sum)이 산출된 직후, 시스템은 SHALL 발화한 detector 수에 따라 **곱셈 보너스**를 적용한다.

- **현재**: 합의 보너스 없음 → 단순 가중합

- **변경 후 동작**:
  | 발화 detector 수 | 보너스 multiplier |
  |---|---|
  | 1개 | 1.00 (변동 없음) |
  | 2개 | 1.15 (+15%) |
  | 3개 이상 | 1.30 (+30%) |
  - 최종 `ensemble_score = min(1.0, weighted_sum * multiplier)` (1.0 상한)

**IF** 보너스 적용 후 점수가 1.0을 초과하면, **THEN** 시스템은 SHALL 1.0으로 클램프(clamp)한다.

**수락 기준**:
- `theme_cluster=0.25` + `volume_news_combo=0.20` 동시 발화 종목의 최종 점수 ≥ `(0.25+0.20) × 1.15 = 0.5175` (단, 가중치 적용 후 기준)
- 단위 테스트: 1·2·3개 detector 발화 케이스에 대해 multiplier가 각각 1.00/1.15/1.30으로 적용됨을 확인

---

### REQ-AI014-005: 가격 모멘텀 사전 필터 (Price Momentum Pre-Filter)

**WHEN** `surge_trading_service.get_today_signals()`가 매수 후보 목록을 생성할 때, 시스템은 SHALL 다음 두 가지 가격 조건을 만족하는 종목을 **제외**한다.

- **변경 후 제외 기준**:
  1. **과열 차단**: 5일 가격 변동률 > +15% (이미 상승 → 추격 매수 회피)
  2. **낙폭 차단**: 1일 가격 변동률 < -5% (급락 중 → 떨어지는 칼날 회피)

**WHERE** 가격 조회는 기존 `_get_current_price_sync()` 인프라 및 보조 가격 조회 함수를 재사용한다.

**IF** 가격 데이터를 가져올 수 없는 경우(API 실패·종목 미커버리지), **THEN** 시스템은 SHALL **해당 종목을 제외하지 않고 통과**시킨다 (graceful fallback, 중립 가정).

**WHILE** 본 필터는 ensemble 점수 평가 **이후** 단계에서 적용되어, 점수가 임계치를 통과한 종목만을 대상으로 한다(불필요한 가격 조회 최소화).

**수락 기준**:
- 5일 누적 +15% 초과 종목은 최종 buy list에 진입하지 않음
- 1일 -5% 미만 종목 또한 진입하지 않음
- 가격 조회 실패 시뮬레이션에서 시그널이 제외되지 않음을 확인

---

### REQ-AI014-006: Ensemble 가중치 재조정 (Weight Rebalancing)

**WHEN** `surge_detection.yaml`의 ensemble weights를 적용할 때, 시스템은 SHALL 다음 신규 가중치를 사용한다.

- **현재 가중치**:
  ```yaml
  ensemble:
    weights:
      theme_cluster: 0.25
      volume_news_combo: 0.30
      disclosure_pattern: 0.25
      legacy_detectors: 0.20
    min_score_for_signal: 0.20
  ```

- **변경 후 가중치**:
  ```yaml
  ensemble:
    weights:
      theme_cluster: 0.35          # 개인화 강화로 비중 상향
      volume_news_combo: 0.35      # 발화 시 신뢰도 높음, 유지
      disclosure_pattern: 0.20     # 희소하나 고품질, 소폭 하향
      legacy_detectors: 0.10       # 영향력 축소
    min_score_for_signal: 0.20     # 변경 없음
  ```
- 가중치 합은 1.00을 유지한다 (제약 조건).

**WHERE** YAML 변경은 단순 값 수정이며, 코드 로직 변경은 불필요하다 (`surge_detector`가 weights를 dict로 읽는 구조 유지).

**수락 기준**:
- 완벽 점수(theme_cluster_score = 1.0) 단일 발화 종목의 ensemble 점수 = 0.35 (기존 0.25 대비 +40% 상승)
- 모든 가중치 합 = 1.00 ± 0.001 (부동소수점 오차 허용)

---

## 3. 비목표 (Non-Goals / Exclusions)

본 SPEC은 다음을 **변경하지 않는다**:

1. ❌ **신규 detector 추가**: 5번째 detector(예: 외국인/기관 매수)는 본 SPEC 범위 외
2. ❌ **머신러닝 기반 스코어링**: 통계·룰 기반 산식만 사용. ML 모델 도입은 별도 SPEC 필요
3. ❌ **DB 스키마 변경**: 기존 `FundSignal`, `Disclosure` 테이블 구조 유지
4. ❌ **알람·UI 변경**: 프론트엔드 표시 로직 및 알람 발송 정책은 별도 처리
5. ❌ **기존 페이퍼 트레이딩 포트폴리오(SPEC-AI-013) 룰 변경**: 본 SPEC은 시그널 산출만 개선, 포트폴리오 매매 룰은 그대로
6. ❌ **disclosure_pattern detector 내부 로직 변경**: 가중치만 조정, 알고리즘 개편은 별도 작업

---

## 4. 성공 기준 (Success Criteria)

| 메트릭 | 현재 | 목표 |
|---|---|---|
| 일별 매수 후보 산출 건수 | 0건 | ≥ 1건 (활발한 거래일) |
| theme_cluster 점수 최대값 | 0.25 (전부 동일) | ≥ 0.35 (개인화·보너스 반영) |
| 단일 detector 통과율 (런타임 필터) | 0% | ≥ 50% (consensus 보너스 후) |
| 과열주(5일 +15% 초과) 매수 비율 | 미측정 | 0% (REQ-005로 차단) |
| 시그널 변별력 (테마 내 동점 종목 비율) | ~100% | ≤ 30% |

---

## 5. 구현 가이드 (Implementation Notes)

### 5.1 단계별 구현 순서 (권장)

1. **Phase A — YAML 가중치 변경** (REQ-006): 단순·저위험, 즉시 적용 가능
2. **Phase B — theme_cluster 산식 개편** (REQ-001 + 002 + 003): 핵심 변경, 함께 묶어서 구현
3. **Phase C — Consensus 보너스** (REQ-004): ensemble 산출 함수 말미에 추가
4. **Phase D — 가격 사전 필터** (REQ-005): `surge_trading_service.get_today_signals()` 수정
5. **Phase E — 런타임 필터 완화 검토**: `if len(active_detectors) < 2 and probability < 0.40` 조건을 `probability < 0.30`으로 완화하거나 REQ-004 multiplier로 자연스럽게 해결되는지 검증

### 5.2 데이터 흐름 (Data Flow)

```
[기사 수집/sentiment 분석]
        │
        ▼
[theme_cluster detector]
   ├── theme_article_count → theme_base_score (REQ-001)
   ├── stock_specific_article_count → stock_article_score (REQ-001)
   ├── price_change_1d > 3% → +0.10 보너스 (REQ-002)
   └── avg sentiment → ×factor (REQ-003)
        │
        ▼
[ensemble 가중합] (REQ-006 가중치)
        │
        ▼
[consensus multiplier] (REQ-004)
        │
        ▼
[ensemble_score] (cap 1.0)
        │
        ▼
[surge_trading_service.get_today_signals()]
   ├── min_score_for_signal 통과
   ├── 가격 모멘텀 사전 필터 (REQ-005)
   └── 최종 매수 후보 출력
```

### 5.3 호환성 및 폴백

- 모든 가격·뉴스 조회는 **실패 시 graceful fallback**으로 점수 산출을 계속한다 (예외 발생 금지).
- 기존 `Disclosure`-기반 시그널(SPEC-AI-004) 흐름은 본 SPEC과 독립적으로 동작한다.
- DB 마이그레이션 없음.

### 5.4 로깅 표준

- 종목별 ensemble breakdown을 DEBUG 레벨로 출력:
  `code=005930 theme_base=0.50 stock_news=0.60 price_bonus=0.10 sentiment_factor=1.10 raw=0.81 weighted=0.28 consensus=1.15 final=0.32`
- 가격 조회 실패는 WARNING 레벨로 1회 발생, 동일 종목 반복 실패는 30분 캐시

---

## 6. 테스트 수락 기준 (Test Acceptance Criteria)

### 6.1 단위 테스트 (Unit Tests)

| 테스트 ID | 대상 REQ | 검증 항목 |
|---|---|---|
| T-001 | REQ-001 | stock_article_count = 0/3/5/10 입력 시 score 단조 증가 |
| T-002 | REQ-001 | sector-only 케이스에서 0.5 배율 적용 확인 |
| T-003 | REQ-002 | 가격 변동 +3.5%/+2.5%/-3.5% 케이스에서 보너스 적용 여부 |
| T-004 | REQ-002 | 가격 API 예외 발생 시 보너스 0 + 정상 반환 (no raise) |
| T-005 | REQ-003 | sentiment 평균 0.0/0.5/1.0 입력 시 factor 0.8/1.0/1.2 확인 |
| T-006 | REQ-004 | 1/2/3 active detectors → multiplier 1.00/1.15/1.30 |
| T-007 | REQ-004 | weighted_sum = 0.9 × multiplier 1.30 → cap 1.0 |
| T-008 | REQ-005 | 5일 +20% 종목 제외, 5일 +10% 종목 통과 |
| T-009 | REQ-005 | 1일 -7% 종목 제외, 1일 -3% 종목 통과 |
| T-010 | REQ-005 | 가격 조회 실패 → 제외하지 않고 통과 |
| T-011 | REQ-006 | YAML 로드 후 weights 합 = 1.00 |

### 6.2 통합 테스트 (Integration Tests)

| 테스트 ID | 시나리오 |
|---|---|
| I-001 | 합성 24시간 기사·가격 데이터로 end-to-end 실행 → 매수 후보 ≥ 1건 |
| I-002 | 가격 API 100% 실패 환경에서 ensemble 산출 정상 동작 |
| I-003 | 동일 테마 100종목 입력 → 점수 분산(std) ≥ 0.05 (변별력 확보) |
| I-004 | 과열주(5일 +18% 종목) 입력 → 최종 buy list 미포함 |

### 6.3 회귀 테스트 (Regression)

- 기존 `disclosure_pattern` detector 출력값에 변화가 없음을 확인 (가중치만 변경, 알고리즘 미변경)
- 기존 SPEC-AI-013 paper trading 포트폴리오의 매매 룰 정상 동작 (signal_type="surge_candidate" 입력 호환성 유지)

### 6.4 Done 정의 (Definition of Done)

- [ ] 6개 REQ 전부 구현 및 통과
- [ ] 단위 테스트 11종 + 통합 테스트 4종 전부 통과
- [ ] `pytest tests/ -m "not slow"` 100% 통과
- [ ] `ruff check .` & `mypy app/` 오류 0
- [ ] 운영 환경 1주 관찰: 일별 매수 후보 ≥ 1건 산출 확인
- [ ] CHANGELOG 업데이트
- [ ] @MX:NOTE 태그 추가 (ensemble 함수, 가격 사전 필터 함수)

---

## 7. 위험 및 완화 (Risks & Mitigation)

| 위험 | 영향도 | 완화 방안 |
|---|---|---|
| 가격 API 빈번한 실패로 보너스/필터 무력화 | 중 | graceful fallback + 30분 캐시 + 30일 모니터링 |
| consensus multiplier 과적용으로 점수 인플레이션 | 중 | 1.0 상한 클램프 + 운영 점수 분포 추적 |
| stock_specific 매칭 false positive (관련 없는 기사가 종목명 우연 일치) | 중 | 종목명 + 종목코드 동시 매칭 또는 본문 길이 가중 |
| 가중치 변경으로 disclosure 시그널 노출 감소 | 낮 | disclosure 가중치 0.25→0.20 (소폭), 일별 발화 빈도 모니터링 |
| 5일 +15% 임계 너무 빡빡하여 매수 기회 박탈 | 낮 | 운영 후 임계 재조정 (별도 패치) |

---

## 8. 참고 문서 (References)

- SPEC-AI-012: 급등예측 시그널 시스템 (signal_type="surge_candidate" 도입 SPEC)
- SPEC-AI-013: 급등예측 모의투자 포트폴리오 (본 SPEC의 다운스트림 소비자)
- SPEC-AI-004: 공시 기반 선제적 시그널 (disclosure_pattern detector 원본)
- `backend/app/services/surge_detector.py`: 4개 detector 본체
- `backend/app/services/surge_trading_service.py`: 런타임 필터 및 모의투자 진입 로직
- `backend/app/surge_config/surge_detection.yaml`: ensemble 가중치 구성

---

**SPEC-AI-014 작성 완료** — Run 단계 진입 전 본 SPEC 검토 및 승인이 필요합니다.
