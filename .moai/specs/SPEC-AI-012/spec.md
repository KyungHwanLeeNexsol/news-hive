---
id: SPEC-AI-012
version: 1.0.0
status: Completed
created: 2026-05-07
updated: 2026-05-07
author: MoAI
priority: High
issue_number: 0
title: Surge Precondition Detection System (급등 징후 탐지 시스템)
tags: [fund-manager, surge-detection, theme-cluster, volume-anomaly, disclosure-pattern, ensemble-scoring, backtest]
---

# SPEC-AI-012: 급등 징후 탐지 시스템

## HISTORY

- **v1.0.0 (2026-05-07)**: 초기 SPEC 작성. 기존 4개 탐지기(`_detect_quiet_accumulation`, `_detect_news_price_divergence`, `_detect_bb_compression`, `_detect_sector_laggards`)와 SPEC-AI-004(공시 미반영 갭)에 더해 3개 신규 탐지기(테마 뉴스 클러스터, 거래량+뉴스 복합 신호, 공시 유형별 역사적 급등 패턴)를 추가하여 급등 가능성이 통계적으로 높은 조건을 사전에 포착한다.

---

## 0. 배경 및 목적

### 문제 정의

NewsHive의 AI 펀드매니저는 현재 다음 4개의 사전 탐지기를 통해 매수 후보를 발굴하고 있다:

1. `_detect_quiet_accumulation` — 조용한 매집 패턴
2. `_detect_news_price_divergence` — 뉴스 발생 대비 주가 미반응 종목
3. `_detect_bb_compression` — 볼린저밴드 압축
4. `_detect_sector_laggards` — 섹터 대비 후행 종목

또한 SPEC-AI-004로 공시 기반 미반영 갭 탐지가 추가되어 있다.

그러나 다음 3개의 고가치 신호 영역은 아직 구조화된 탐지 로직이 없다:

1. **테마 뉴스 클러스터링 부재**: 동일 테마 키워드(예: "반도체", "수소")가 단기간(48시간 내)에 다수의 뉴스에서 동시 출현하는 경우, 해당 테마의 수혜 종목군이 곧 함께 움직일 가능성이 높지만, 이를 자동으로 감지하여 후보로 변환하는 로직이 없다.
2. **거래량 이상 + 뉴스 복합 신호 부재**: 단순 거래량 급증만으로는 노이즈가 많고, 단순 뉴스 등장만으로는 시장 반응 여부를 알 수 없다. 두 신호가 동일 시간 윈도우(24시간) 내에 함께 발생하는 종목을 시장이 "주목하기 시작했다"는 신호로 활용하지 못하고 있다.
3. **공시 유형별 역사적 급등 패턴 부재**: SPEC-AI-004는 "이번 공시가 주가에 얼마나 반영되었는가"(미반영 갭)를 측정하지만, "이 공시 유형이 과거에 통계적으로 얼마나 자주 급등을 유발했는가"(historical surge rate)는 측정하지 않는다. 두 정보는 보완적이며, 후자는 SPEC-AI-004의 데이터를 재활용하여 산출 가능하다.

### 핵심 설계 철학

본 시스템은 **정확한 가격 움직임을 예측하지 않는다.** 대신 **"급등이 통계적으로 더 자주 발생하는 조건"을 탐지**한다. 목표 지향성 적중률은 55-62%(랜덤 베이스라인 50% 대비 +5~12%p)이며, 이는 머신러닝 가격 예측 모델이 아닌 룰 기반 앙상블의 합리적 상한선이다.

본 시스템은 가격 예측 시스템이 아니라 **신호 우선순위화 시스템(signal prioritization system)** 이다.

### 목표

- 테마 뉴스 클러스터 탐지로 단기 테마 수혜 종목군을 자동 발굴한다
- 거래량 z-score + 뉴스 감성 복합 신호로 시장의 초기 주목 신호를 포착한다
- 공시 유형별 역사적 급등률을 산출하여 SPEC-AI-004를 보완한다
- 3개 신규 탐지기 + 기존 4개 탐지기 + 공시 신호를 가중 앙상블로 결합한 `surge_probability_score`를 제공한다
- `FundSignal.signal_type`에 `"surge_candidate"` 타입을 추가하고 브리핑에 자동 주입한다
- 백테스팅으로 신호 유형별 적중률(directional accuracy)을 추적하여 가중치를 조정 가능하게 한다
- 모든 임계값을 설정 파일로 외부화하여 하드코딩을 금지한다

---

## 1. 환경 (Environment)

### 1.1 기존 인프라

| 모듈 | 현재 상태 | SPEC-AI-012에서의 역할 |
|------|-----------|----------------------|
| `backend/app/services/fund_manager.py` | 4개 사전 탐지기 + SPEC-AI-004 공시 후보 수집 | 3개 신규 탐지기 추가, 앙상블 스코어 산출 진입점 |
| `backend/app/services/disclosure_impact_scorer.py` | DART 공시 충격 스코어링 (SPEC-AI-004) | 공시 유형별 역사적 급등률 산출의 데이터 소스 |
| `backend/app/services/sector_momentum.py` | 섹터 모멘텀 감지 | 테마 클러스터에서 섹터-테마 매핑에 활용 |
| `backend/app/services/news_price_impact_service.py` | 뉴스 발행 시점 주가 스냅샷 + T+1D / T+5D 반응 추적 | 백테스팅 적중률 측정 방법론 재사용 |
| `backend/app/services/signal_verifier.py` | 시그널 적중률 검증 + 베이지안 보정 | `surge_candidate` 시그널의 적중률 통계 산출 |
| `backend/app/services/naver_news_crawler.py` | 30분 간격 네이버 뉴스 크롤링 | 테마 키워드 매칭 입력 |
| `backend/app/services/naver_finance.py` | 네이버 금융 주가/거래량 폴링 | 거래량 z-score 계산 입력 (신규 데이터 소스 추가 금지) |
| `backend/app/models/fund_signal.py` | `FundSignal` 모델, `signal_type` 필드 보유 | `"surge_candidate"` 타입 추가 |

### 1.2 기존 DB 모델

- `News`: `id`, `title`, `body`, `published_at`, `keywords`(또는 정규식 추출), `sentiment_score`
  - **활용**: 테마 키워드 매칭 + 감성 점수
- `Stock`: `code`, `name`, `sector_id`, `market_cap`
  - **활용**: 섹터-테마 매핑, 시총 필터
- `StockPrice` (네이버 폴링 결과 저장처): `stock_code`, `date/timestamp`, `close`, `volume`
  - **활용**: 거래량 z-score 계산 (20일 평균 대비)
- `Disclosure`: SPEC-AI-004로 확장된 모델 (`impact_score`, `report_type` 등)
  - **활용**: 공시 유형별 역사적 급등률 집계
- `FundSignal`: `id`, `stock_code`, `signal_type`, `confidence_score`, `created_at`, `metadata`(JSON)
  - **변경 필요**: `signal_type` enum에 `"surge_candidate"` 추가
  - **메타데이터 신규 필드**: `surge_probability_score`, `surge_basis`, `lookback_days`

### 1.3 설정 파일 (신규)

신규 설정 파일 `backend/app/config/surge_detection.yaml` (또는 `settings.SURGE_*` 환경변수 그룹)에 다음을 정의한다:

```yaml
surge_detection:
  theme_cluster:
    keywords: ["반도체", "배터리", "수소", "전기차", "AI", "로봇", "방위산업", "바이오", "원전"]
    cluster_window_hours: 48
    min_article_count: 3
    min_market_cap_krw: 100000000000  # 1000억 원
  volume_news_combo:
    volume_zscore_threshold: 2.5
    volume_baseline_days: 20
    news_window_hours: 24
    min_news_sentiment: 0.3
  disclosure_pattern:
    historical_surge_threshold_pct: 10.0
    historical_lookback_days: 5
    min_surge_rate: 0.40
    min_sample_size: 20
  ensemble:
    weights:
      theme_cluster: 0.25
      volume_news_combo: 0.30
      disclosure_pattern: 0.25
      legacy_detectors: 0.20  # 기존 4개 + 공시 미반영 갭의 가중 합
    min_score_for_signal: 0.55
  backtest:
    enabled: true
    evaluation_horizon_days: 5
```

**[HARD]** 위 모든 임계값은 설정 파일에서 읽어야 하며, 코드에 하드코딩을 금지한다.

---

## 2. 가정 (Assumptions)

- **A1**: 네이버 뉴스 크롤링이 30분 간격으로 정상 작동하며, 뉴스 본문/제목에서 테마 키워드를 정규식 또는 키워드 매칭으로 추출 가능하다.
- **A2**: 네이버 금융 폴링이 일별 거래량을 제공하므로, 종목별 20일 거래량 평균 및 표준편차로 z-score 계산이 가능하다.
- **A3**: SPEC-AI-004로 누적된 공시 데이터가 충분(공시 유형당 최소 20건 이상)하여 역사적 급등률 산출이 통계적으로 의미 있다. 샘플 수가 부족한 공시 유형은 자동으로 제외된다.
- **A4**: 본 시스템의 목표 적중률 55-62%는 현실적이며, 65%를 초과하는 적중률을 약속하지 않는다. 적중률이 50% 미만으로 떨어지는 신호 유형은 가중치가 자동 감소된다.
- **A5**: 머신러닝 모델 학습 파이프라인은 본 SPEC의 범위가 아니다. 룰 기반 앙상블만으로 구현하며, 향후 ML 도입은 별도 SPEC으로 분리한다.
- **A6**: `FundSignal.metadata` 필드는 JSON(JSONB) 타입이며 `surge_probability_score`, `surge_basis`, `lookback_days`를 포함하는 dict를 저장 가능하다.
- **A7**: 거래량 데이터는 네이버 금융 기존 폴러로 충분하다. 추가 데이터 소스(증권사 API 등) 도입은 본 SPEC 범위 외이다.

---

## 3. 요구사항 (Requirements)

EARS(Easy Approach to Requirements Syntax) 형식으로 작성한다.

### REQ-SURGE-001: 테마 뉴스 클러스터 탐지

- **(Event-Driven)** **WHEN** 동일한 테마 키워드(설정 파일 `theme_cluster.keywords` 기준)가 직전 `theme_cluster.cluster_window_hours`(기본 48시간) 윈도우 내에 `theme_cluster.min_article_count`(기본 3건) 이상의 서로 다른 뉴스에서 출현하면, **THEN** 시스템은 해당 테마를 "활성 테마(active theme)"로 분류한다.
- **(Ubiquitous)** 시스템은 활성 테마별로 해당 섹터에 속하는 종목 중 시총 `theme_cluster.min_market_cap_krw`(기본 1000억 원) 이상인 종목 리스트를 생성한다.
- **(Ubiquitous)** 각 후보 종목에 대해 `theme_cluster_score`를 계산한다:
  - `theme_cluster_score = min(1.0, article_count / 10) * sector_relevance_weight`
  - `sector_relevance_weight`는 섹터-테마 매핑 사전(설정 파일)에서 조회한다.
- **(Unwanted)** 시스템은 활성 테마라 하더라도 시총 1000억 미만의 초소형주를 자동 후보 풀에 포함시키지 **않는다**.
- **(Optional)** Where 가능하다면, 시스템은 동일 테마 내에서 직전 5거래일 간 가장 적게 상승한 종목(theme laggard)을 별도 표시한다.

#### 신규 함수 시그니처
```python
async def _detect_theme_news_cluster(
    self,
    db: AsyncSession,
    config: SurgeDetectionConfig,
) -> list[SurgeCandidate]:
    """
    테마 키워드의 단기 클러스터링을 탐지하여 수혜 종목 후보를 반환한다.
    """
```

### REQ-SURGE-002: 비정상 거래량 + 뉴스 복합 신호

- **(Event-Driven)** **WHEN** 종목의 일별 거래량 z-score(직전 `volume_news_combo.volume_baseline_days`(기본 20일) 평균/표준편차 대비)가 `volume_news_combo.volume_zscore_threshold`(기본 2.5) 를 초과하면, **THEN** 시스템은 해당 종목을 "거래량 이상 종목(volume anomaly stock)"으로 식별한다.
- **(State-Driven)** **WHILE** 거래량 이상 종목으로 식별된 상태에서, 동일 종목에 대해 `volume_news_combo.news_window_hours`(기본 24시간) 윈도우 내에 감성 점수 `volume_news_combo.min_news_sentiment`(기본 0.3) 이상의 긍정 뉴스가 1건 이상 존재하면, 시스템은 해당 종목을 "거래량+뉴스 복합 신호(volume+news combo)" 후보로 등록한다.
- **(Ubiquitous)** 시스템은 복합 신호 후보에 대해 `combo_score`를 계산한다:
  - `combo_score = sigmoid((volume_zscore - 2.5) / 1.0) * normalized_news_sentiment`
  - 여기서 `normalized_news_sentiment`는 윈도우 내 최대 감성 점수를 [0, 1]로 클리핑한 값이다.
- **(Unwanted)** 시스템은 거래량 이상만 있고 뉴스가 없는 종목, 또는 뉴스만 있고 거래량 이상이 없는 종목을 본 신호로 발신하지 **않는다**(이는 다른 탐지기의 영역이다).

#### 신규 함수 시그니처
```python
async def _detect_volume_surge_news_combo(
    self,
    db: AsyncSession,
    config: SurgeDetectionConfig,
) -> list[SurgeCandidate]:
    """
    거래량 z-score 이상 + 동일 시간 윈도우 내 긍정 뉴스 복합 신호를 탐지한다.
    """
```

### REQ-SURGE-003: 공시 유형별 역사적 급등 패턴

- **(Ubiquitous)** 시스템은 SPEC-AI-004로 누적된 `Disclosure` 데이터를 사용하여 **공시 유형(report_type)별 역사적 급등률**을 주기적으로(일 1회 이상) 산출한다:
  - "이 공시 유형이 발생한 후 `disclosure_pattern.historical_lookback_days`(기본 5거래일) 이내에 종가가 `disclosure_pattern.historical_surge_threshold_pct`(기본 10%) 이상 상승한 비율"
  - 표본 수가 `disclosure_pattern.min_sample_size`(기본 20건) 미만인 공시 유형은 산출 대상에서 제외한다.
- **(Event-Driven)** **WHEN** 새로운 공시가 도착하고 그 공시 유형의 역사적 급등률이 `disclosure_pattern.min_surge_rate`(기본 0.40) 이상이면, **THEN** 시스템은 해당 공시의 종목을 "역사적 급등 패턴 공시(historically surge-correlated disclosure)" 후보로 등록한다.
- **(Ubiquitous)** 시스템은 본 후보에 대해 `pattern_score`를 계산한다:
  - `pattern_score = (historical_surge_rate - 0.40) / 0.60`
  - 즉 급등률 40%일 때 0.0, 100%일 때 1.0으로 정규화된다.
- **(Unwanted)** 본 탐지기는 SPEC-AI-004의 "미반영 갭" 로직을 **중복하지 않는다**. SPEC-AI-004는 "이번 공시가 주가에 얼마나 덜 반영되었나"(현재 상태)를 측정하고, 본 탐지기는 "이 공시 유형이 과거에 얼마나 급등을 유발했나"(역사적 패턴)를 측정한다. 두 신호는 보완적이며, 동일 종목에 대해 둘 다 발신될 수 있다.
- **(State-Driven)** **WHILE** 공시 데이터의 표본 수가 충분하지 않은 초기 단계(SPEC-AI-004 도입 직후 30일 이내)에는, 시스템은 본 탐지기를 비활성 상태로 유지하고 로그에 "insufficient sample" 경고를 기록한다.

#### 신규 함수 시그니처
```python
async def _detect_disclosure_surge_pattern(
    self,
    db: AsyncSession,
    config: SurgeDetectionConfig,
) -> list[SurgeCandidate]:
    """
    공시 유형별 역사적 급등률을 기반으로 급등 가능성이 높은 신규 공시를 탐지한다.
    SPEC-AI-004의 미반영 갭과 보완 관계.
    """

async def compute_disclosure_type_surge_rates(
    db: AsyncSession,
    lookback_days: int,
    surge_threshold_pct: float,
    min_sample_size: int,
) -> dict[str, DisclosureSurgeStat]:
    """
    DB에 누적된 Disclosure를 집계하여 공시 유형별 역사적 급등률을 계산한다.
    """
```

### REQ-SURGE-004: 급등 확률 스코어 앙상블

- **(Ubiquitous)** 시스템은 한 종목에 대해 발생한 모든 신호 점수를 가중 평균하여 `surge_probability_score`를 계산한다:
  ```
  surge_probability_score = (
      ensemble.weights.theme_cluster      * theme_cluster_score
    + ensemble.weights.volume_news_combo  * combo_score
    + ensemble.weights.disclosure_pattern * pattern_score
    + ensemble.weights.legacy_detectors   * legacy_score
  )
  ```
  - `legacy_score`는 기존 4개 탐지기 + SPEC-AI-004 공시 미반영 갭의 가중 합을 [0, 1]로 정규화한 값이다.
  - 발생하지 않은 신호는 0으로 처리한다.
- **(Event-Driven)** **WHEN** `surge_probability_score >= ensemble.min_score_for_signal`(기본 0.55) 이면, **THEN** 시스템은 해당 종목에 대해 `signal_type="surge_candidate"` `FundSignal`을 생성한다.
- **(Ubiquitous)** `surge_probability_score`는 `FundSignal.confidence_score` 필드에 저장된다.
- **(Unwanted)** 시스템은 `surge_probability_score`를 절대 가격 예측 확률로 사용자에게 표시하지 **않는다**. UI/브리핑에서는 "급등 가능성 높음", "주의 깊게 관찰 필요" 등 정성적 표현을 사용한다.

### REQ-SURGE-005: FundSignal 통합 및 브리핑 주입

- **(Ubiquitous)** `FundSignal.signal_type` enum에 `"surge_candidate"`를 추가한다.
- **(Ubiquitous)** `FundSignal.metadata` JSON 필드에 다음을 저장한다:
  - `surge_probability_score`: float (0.0 ~ 1.0)
  - `surge_basis`: list[str] — 트리거된 탐지기 이름 배열, 예: `["theme_cluster", "volume_news_combo"]`
  - `lookback_days`: int — 패턴 산출에 사용된 시간 윈도우
  - `theme_cluster_score`, `combo_score`, `pattern_score`, `legacy_score`: 개별 점수 (디버깅/백테스팅용)
- **(Event-Driven)** **WHEN** AI 펀드매니저 브리핑이 생성될 때, **THEN** 시스템은 직전 24시간 내 생성된 `surge_candidate` 시그널을 별도 섹션("급등 징후 후보")으로 브리핑에 주입한다.
- **(State-Driven)** **WHILE** 동일 종목에 대해 `surge_candidate` 시그널이 활성 상태(생성 후 5거래일 이내)인 동안, 시스템은 동일 종목의 신규 신호를 중복 생성하지 않고 기존 시그널의 점수만 갱신한다.

### REQ-SURGE-006: 백테스팅 — 신호별 적중률 추적

- **(Ubiquitous)** 시스템은 `surge_candidate` 시그널이 생성된 후 `backtest.evaluation_horizon_days`(기본 5거래일) 이내의 종가 변동을 추적하여 다음을 산출한다:
  - **방향성 적중률(directional accuracy)**: 시그널 생성 후 종가가 시그널 시점 대비 +5% 이상 상승한 비율
  - **평균 수익률(average return)**: 시그널 생성 후 5거래일까지의 평균 종가 변화율
- **(Ubiquitous)** 시스템은 `surge_basis`에 포함된 탐지기 조합별로 위 통계를 분리 집계하여, 어떤 탐지기 조합이 가장 적중률이 높은지 분석 가능하게 한다.
- **(Optional)** Where 가능하다면, 시스템은 백테스팅 결과를 기반으로 `ensemble.weights`를 자동 조정 제안한다(자동 적용은 금지하고 제안만 한다).
- **(Unwanted)** 시스템은 적중률이 50%(랜덤 베이스라인) 미만인 탐지기 조합에 대해 자동으로 가중치를 양수로 유지하지 **않는다**. 수동 검토 후 가중치 조정 또는 비활성화를 권고한다.
- **(Ubiquitous)** 백테스팅 결과는 `GET /fund/surge-backtest` 엔드포인트로 조회 가능해야 한다.

### REQ-SURGE-007: 하드코딩 금지 — 임계값은 설정파일로

- **[HARD]** **(Unwanted)** 본 SPEC에서 명시한 모든 수치 임계값(테마 키워드, 윈도우 시간, z-score, 시총 필터, 가중치, 최소 점수 등)은 코드에 하드코딩되어서는 **안 된다**. 모두 `surge_detection.yaml` 또는 환경변수에서 읽어야 한다.
- **(Ubiquitous)** 설정 파일은 Pydantic Settings 또는 동등한 구조화된 검증 메커니즘으로 로드한다.
- **(Event-Driven)** **WHEN** 설정 파일이 누락되거나 검증에 실패하면, **THEN** 시스템은 명확한 에러 메시지와 함께 시작을 거부한다(silent fallback 금지).
- **(Optional)** Where 가능하다면, 운영자가 재시작 없이 설정을 reload할 수 있는 관리 엔드포인트(`POST /admin/surge-config/reload`)를 제공한다.

---

## 4. 인수 조건 (Acceptance Criteria)

각 요구사항에 대한 구체적이고 테스트 가능한 인수 조건. Given-When-Then 형식.

### AC-SURGE-001 (REQ-SURGE-001 검증)

- **Given** 테스트 DB에 직전 48시간 내 "반도체" 키워드 포함 뉴스 5건이 존재하고, 반도체 섹터에 시총 2000억 원 종목 A가 있다
- **When** `_detect_theme_news_cluster()`를 호출한다
- **Then** 반환 리스트에 종목 A가 포함되며, `theme_cluster_score`는 0보다 크고 1 이하이다.
- **Given** 동일 조건에서 시총 500억 원 종목 B가 있다
- **When** `_detect_theme_news_cluster()`를 호출한다
- **Then** 종목 B는 반환 리스트에 포함되지 **않는다**(시총 필터 동작).
- **Given** "반도체" 키워드 뉴스가 단 2건만 존재한다
- **When** `_detect_theme_news_cluster()`를 호출한다
- **Then** "반도체" 테마는 활성화되지 않으며, 관련 후보가 반환되지 않는다.

### AC-SURGE-002 (REQ-SURGE-002 검증)

- **Given** 종목 X의 직전 20거래일 거래량 평균이 1,000,000주, 표준편차가 200,000주인 상태에서 오늘 거래량이 1,700,000주(z-score = 3.5)이다
- **And** 직전 24시간 내 종목 X에 대해 감성 점수 0.7의 긍정 뉴스가 존재한다
- **When** `_detect_volume_surge_news_combo()`를 호출한다
- **Then** 종목 X는 반환 리스트에 포함되며, `combo_score > 0.5` 이다.
- **Given** 동일 거래량 이상이지만 뉴스가 없다
- **When** `_detect_volume_surge_news_combo()`를 호출한다
- **Then** 종목 X는 반환되지 **않는다**.
- **Given** 거래량 z-score가 2.0(임계값 2.5 미만)이고 긍정 뉴스가 있다
- **When** `_detect_volume_surge_news_combo()`를 호출한다
- **Then** 종목 X는 반환되지 **않는다**.

### AC-SURGE-003 (REQ-SURGE-003 검증)

- **Given** 테스트 DB에 공시 유형 "단일판매·공급계약체결" 표본 30건이 있고, 그중 18건이 5거래일 이내 10% 이상 상승했다(historical_surge_rate = 0.60)
- **And** 동일 유형의 신규 공시가 종목 Y에 대해 도착했다
- **When** `_detect_disclosure_surge_pattern()`를 호출한다
- **Then** 종목 Y는 반환되며, `pattern_score = (0.60 - 0.40) / 0.60 ≈ 0.333` 이다.
- **Given** 공시 유형 "기타경영사항" 표본이 15건뿐이다(min_sample_size 20 미만)
- **When** `compute_disclosure_type_surge_rates()`를 호출한다
- **Then** 반환된 dict에 "기타경영사항" 키가 포함되지 **않는다**.
- **Given** SPEC-AI-004와 본 SPEC이 동일 종목 동일 공시에 대해 동시 트리거되었다
- **When** 시그널 발신 결과를 조회한다
- **Then** 두 신호는 별도의 `signal_type`("disclosure_impact" vs "surge_candidate")으로 발신되며, 중복 처리 없이 각각 기록된다.

### AC-SURGE-004 (REQ-SURGE-004 검증)

- **Given** 종목 Z에 대해 `theme_cluster_score=0.8`, `combo_score=0.6`, `pattern_score=0.0`, `legacy_score=0.4` 이고 가중치가 기본값(0.25, 0.30, 0.25, 0.20)이다
- **When** `surge_probability_score`를 계산한다
- **Then** 결과는 `0.25*0.8 + 0.30*0.6 + 0.25*0.0 + 0.20*0.4 = 0.46` 이다.
- **And** 0.46 < 0.55(`min_score_for_signal`)이므로 `surge_candidate` 시그널은 생성되지 **않는다**.
- **Given** 동일 종목의 `combo_score`가 0.9로 갱신되었다
- **When** `surge_probability_score`를 재계산한다
- **Then** 결과는 `0.25*0.8 + 0.30*0.9 + 0.25*0.0 + 0.20*0.4 = 0.55` 이고, 임계값 충족으로 `surge_candidate` 시그널이 생성된다.

### AC-SURGE-005 (REQ-SURGE-005 검증)

- **Given** `surge_candidate` 시그널이 종목 W에 대해 생성되었고 metadata에 `surge_basis=["theme_cluster", "volume_news_combo"]`가 저장되어 있다
- **When** AI 펀드매니저 브리핑을 생성한다
- **Then** 브리핑에 "급등 징후 후보" 섹션이 포함되며, 종목 W가 표시되고 트리거된 탐지기 이름이 함께 노출된다.
- **Given** 동일 종목에 대해 5거래일 이내에 신규 트리거가 발생한다
- **When** 시그널 생성 로직이 동작한다
- **Then** 새로운 `FundSignal` 행이 생성되지 않고, 기존 시그널의 `confidence_score`와 `metadata`가 갱신된다.

### AC-SURGE-006 (REQ-SURGE-006 검증)

- **Given** 직전 30일간 `surge_candidate` 시그널 50건이 발신되었고, 그중 30건이 5거래일 이내 +5% 이상 상승했다
- **When** `GET /fund/surge-backtest`를 호출한다
- **Then** 응답에 `directional_accuracy=0.60`, `total_signals=50`이 포함된다.
- **And** `surge_basis` 조합별 적중률(예: `["theme_cluster"]` 단독, `["volume_news_combo"]` 단독, 둘의 조합)이 분리 집계되어 응답에 포함된다.

### AC-SURGE-007 (REQ-SURGE-007 검증)

- **Given** `surge_detection.yaml`에서 `theme_cluster.min_article_count: 5`로 변경한다
- **When** 시스템을 재시작한다
- **Then** `_detect_theme_news_cluster()`는 새로운 임계값(5건)으로 동작한다.
- **Given** `surge_detection.yaml`에 `ensemble.weights` 합이 1.0이 아닌 잘못된 값(예: 0.95)이 설정되었다
- **When** 시스템 시작 시 설정 검증이 동작한다
- **Then** 시스템은 명확한 에러 메시지("ensemble weights must sum to 1.0")와 함께 시작을 거부한다.
- **Given** 코드 정적 분석으로 fund_manager.py를 검사한다
- **When** 매직 넘버(2.5, 48, 0.40 등 SPEC에 정의된 임계값)를 검색한다
- **Then** 해당 숫자가 코드에 직접 등장하지 않고 모두 설정 객체 참조로 사용되고 있어야 한다.

---

## 5. 기술 설계 (Technical Design)

### 5.1 파일 변경 사항

| 파일 | 변경 유형 | 내용 |
|------|---------|------|
| `backend/app/services/fund_manager.py` | 수정 | 3개 신규 탐지기 메서드 추가, 앙상블 스코어 계산 로직 추가, `surge_candidate` 시그널 발신 로직 추가 |
| `backend/app/services/surge_detector.py` | 신규 | (선택) 3개 신규 탐지기를 별도 모듈로 분리하여 fund_manager.py 비대화 방지. fund_manager.py는 thin orchestrator 역할 |
| `backend/app/services/surge_backtest.py` | 신규 | 백테스팅 통계 산출 로직 (REQ-SURGE-006) |
| `backend/app/config/surge_detection.yaml` | 신규 | 모든 임계값 설정 파일 |
| `backend/app/config/surge_settings.py` | 신규 | Pydantic Settings 기반 설정 로더 + 검증 (가중치 합 검증 포함) |
| `backend/app/models/fund_signal.py` | 수정 | `signal_type` enum에 `"surge_candidate"` 추가 |
| `backend/app/api/fund.py` | 수정 | `GET /fund/surge-backtest`, (선택) `POST /admin/surge-config/reload` 엔드포인트 추가 |
| `backend/alembic/versions/0XX_spec_ai_012_surge_signal.py` | 신규 | 마이그레이션 — `signal_type` enum 갱신 (Postgres native enum 사용 시 ALTER TYPE 필요) |
| `backend/tests/test_surge_detector.py` | 신규 | 3개 탐지기 + 앙상블 단위 테스트 |
| `backend/tests/test_surge_backtest.py` | 신규 | 백테스팅 단위 테스트 |
| `backend/tests/conftest.py` | 수정 | 테마 클러스터/거래량/공시 패턴 테스트용 fixture 추가 |

### 5.2 fund_manager.py 진입점 흐름

```
generate_briefing()
  ├─ _gather_legacy_candidates()       # 기존 4개 탐지기
  ├─ _gather_disclosure_candidates()   # SPEC-AI-004 미반영 갭
  ├─ _gather_surge_candidates()        # 신규: 3개 surge 탐지기 + 앙상블
  │    ├─ surge_detector.detect_theme_news_cluster()
  │    ├─ surge_detector.detect_volume_surge_news_combo()
  │    ├─ surge_detector.detect_disclosure_surge_pattern()
  │    └─ _ensemble_surge_score()
  └─ _persist_signals_and_inject_briefing()
```

### 5.3 DB 변경 사항

- **`fund_signal.signal_type`**: 기존 enum에 `"surge_candidate"` 값 추가 (Postgres의 경우 `ALTER TYPE ... ADD VALUE`).
- **신규 컬럼은 추가하지 않는다.** 모든 추가 정보는 기존 `metadata` JSON 필드에 저장한다(DB 스키마 변경 최소화).
- 백테스팅 통계는 별도 테이블 없이 매 호출 시 SQL 집계로 계산한다(데이터 양이 폭증하지 않는 한 별도 캐시 테이블 불필요).

### 5.4 캐싱 전략

- **공시 유형별 역사적 급등률**: 일 1회 백그라운드 작업으로 산출하여 Redis(또는 in-memory dict + TTL)에 캐싱한다. 매 공시 도착 시마다 전체 집계를 다시 계산하지 않는다.
- **거래량 z-score**: 종목당 일별 1회 계산되면 충분하므로 batch job으로 미리 계산하여 in-memory dict에 저장한다.

### 5.5 의존성

- **신규 외부 라이브러리 추가 없음.** scikit-learn, statsmodels 등 ML 라이브러리 도입은 본 SPEC 범위 외(REQ-SURGE-007의 정신 — 단순성 유지).
- 표준 라이브러리(`statistics`, `math`)와 기존 의존성(`sqlalchemy`, `pydantic`, `fastapi`)만 사용.

---

## 6. 구현 제약 (Implementation Constraints)

본 SPEC을 구현하면서 **하지 말아야 할 것들** 명시. 위반 시 SPEC 미준수로 간주.

### 6.1 절대 금지 사항 [HARD]

1. **머신러닝 모델 학습 파이프라인 도입 금지.** 본 SPEC은 룰 기반 앙상블만 다룬다. ML 도입은 별도 SPEC으로 분리한다.
2. **65% 이상의 급등 예측 적중률 주장/명시 금지.** 코드 주석, 로그, API 응답, UI 어디에도 "정확도 X%" 같은 절대 수치를 약속하지 않는다. 표시 가능한 정성 표현: "관찰 가치 높음", "추가 검증 필요" 등.
3. **테마 키워드 하드코딩 금지.** 모든 키워드는 `surge_detection.yaml`에서 로드하며, 신규 키워드 추가는 코드 수정 없이 가능해야 한다.
4. **모든 임계값 하드코딩 금지.** REQ-SURGE-007 참조. 임계값은 반드시 설정 객체 경유.
5. **SPEC-AI-004의 미반영 갭 로직 중복 구현 금지.** REQ-SURGE-003은 SPEC-AI-004를 **확장**하며 데이터를 **재사용**한다. 동일한 갭 계산 로직을 본 SPEC 코드에 복사하지 말 것.
6. **신규 외부 데이터 소스 도입 금지.** 거래량은 기존 Naver Finance 폴러를, 뉴스는 기존 Naver News 크롤러를, 공시는 기존 DART 크롤러를 사용한다. 증권사 API, 텔레그램 등 신규 소스 추가는 본 SPEC 범위 외.
7. **사용자에게 "급등 확률 X%"로 표시 금지.** `surge_probability_score`는 내부 점수이며, UI/브리핑에서는 정성 표현으로만 사용한다.

### 6.2 권장 사항 (Should)

1. **테스트 우선 (TDD).** `tests/test_surge_detector.py`를 먼저 작성하고, 각 탐지기 단위 테스트가 실패함을 확인한 후 구현.
2. **Pure function 우선.** 가능한 경우 탐지기를 DB 의존성 없는 순수 함수로 구현하고, fund_manager는 데이터를 주입받아 호출하는 형태로 분리.
3. **타입 힌트 100%.** 모든 신규 함수는 type annotations 필수.
4. **로그 레벨 분리.** 신호 발신은 INFO, 임계값 미달은 DEBUG, 설정 오류는 ERROR.

### 6.3 SPEC-AI-004와의 명확한 경계

| 측면 | SPEC-AI-004 (기존) | SPEC-AI-012 REQ-SURGE-003 (본 SPEC) |
|------|-------------------|------------------------------------|
| 측정 대상 | 이번 공시가 주가에 얼마나 덜 반영됐는가 | 이 공시 유형이 과거에 얼마나 자주 급등을 유발했는가 |
| 데이터 소스 | 단일 공시 + 발생 후 주가 반응 | 누적된 공시 데이터셋 |
| 시그널 타입 | `"disclosure_impact"` | `"surge_candidate"` |
| 발신 가능성 | 공시 후 즉시 (실시간) | 공시 도착 시 (역사 통계 캐시 조회) |
| 동시 발신 | 가능 — 두 신호는 독립적이며 보완적 |

---

## 7. 우선순위 및 의존성

### 7.1 의존성

| 의존 SPEC | 의존 유형 | 설명 |
|----------|----------|------|
| SPEC-AI-004 | **선행 필수** | REQ-SURGE-003은 SPEC-AI-004로 누적된 `Disclosure` 데이터 + `disclosure_impact_scorer.py`를 활용한다. 표본 30일치 누적 후 본 SPEC 활성화 가능. |
| SPEC-AI-003 | 호환 | 기존 4개 사전 탐지기는 본 SPEC의 `legacy_detectors` 가중치 입력으로 사용된다. 변경 불필요. |
| SPEC-AI-011 | 무관 | 지배구조 인식은 본 SPEC과 직교. 단, 향후 테마 클러스터 후보군에 자회사 확장 로직 적용 가능 (선택). |

### 7.2 구현 순서 (Priority)

본 SPEC은 단일 PR로 한 번에 구현하지 말고, 다음 순서로 분할 구현 권장:

#### Priority 1 (선결 조건)
- **M1**: 설정 파일/로더 구축 (`surge_settings.py`, `surge_detection.yaml`)
  - REQ-SURGE-007 만족
  - 테스트 가능한 검증 로직(가중치 합, 키워드 비어있지 않음 등)

#### Priority 2 (핵심 기능)
- **M2**: REQ-SURGE-001 — `_detect_theme_news_cluster` 구현 + 단위 테스트
- **M3**: REQ-SURGE-002 — `_detect_volume_surge_news_combo` 구현 + 단위 테스트
- **M4**: REQ-SURGE-003 — `_detect_disclosure_surge_pattern` 구현 + 단위 테스트
  - `compute_disclosure_type_surge_rates` 백그라운드 작업 등록

#### Priority 3 (통합)
- **M5**: REQ-SURGE-004 — 앙상블 스코어 계산 + `min_score_for_signal` 게이트
- **M6**: REQ-SURGE-005 — `FundSignal.signal_type` enum 추가, Alembic 마이그레이션, 브리핑 주입
- **M7**: 통합 테스트 — fund_manager.py 진입점에서 end-to-end 시나리오 검증

#### Priority 4 (관측성/검증)
- **M8**: REQ-SURGE-006 — 백테스팅 모듈 + `GET /fund/surge-backtest` 엔드포인트
- **M9**: 운영 환경에서 30일간 shadow mode 운영 (시그널 생성하되 브리핑 주입하지 않음)
- **M10**: 적중률 검증 후 정식 활성화 + 가중치 조정

### 7.3 완료 정의 (Definition of Done)

- [ ] 모든 REQ-SURGE-001 ~ REQ-SURGE-007의 인수 조건이 단위/통합 테스트로 검증됨
- [ ] `cd backend && uv run pytest tests/test_surge_detector.py tests/test_surge_backtest.py --tb=short -q` 통과
- [ ] `cd backend && uv run ruff check .` 통과 (lint clean)
- [ ] `cd backend && uv run mypy app/services/surge_detector.py app/services/surge_backtest.py` 통과
- [ ] 코드 어디에도 매직 넘버 임계값이 직접 등장하지 않음 (grep 검증)
- [ ] SPEC-AI-004의 기존 동작이 회귀하지 않음 (기존 테스트 전부 통과)
- [ ] CHANGELOG에 SPEC-AI-012 항목 추가
- [ ] OCI 배포 후 30일 shadow mode 데이터 수집 (M9 완료)

---

## 8. 검증 및 운영 (Verification & Operations)

### 8.1 운영 모니터링 지표

- **신호 발신 빈도**: 일일 `surge_candidate` 시그널 수 (과다 발신 시 임계값 조정 필요)
- **탐지기별 기여도**: `surge_basis` 분포 (특정 탐지기에 과의존 여부 확인)
- **방향성 적중률**: 5거래일 후 +5% 상승 비율, 50% 미만 시 알림
- **설정 reload 카운트**: `POST /admin/surge-config/reload` 호출 빈도 (운영 안정성 확인)

### 8.2 회귀 방지

- 기존 4개 탐지기와 SPEC-AI-004의 단위 테스트는 본 SPEC 도입 후에도 100% 통과해야 한다.
- 본 SPEC의 신규 시그널이 기존 시그널 발신을 차단/대체하지 않음을 통합 테스트로 검증한다.

### 8.3 롤백 전략

- 운영 중 적중률이 50% 미만으로 7일 연속 유지되면, `ensemble.weights.theme_cluster` / `combo` / `pattern` 중 가장 적중률 낮은 항목을 0으로 설정하여 즉시 비활성화 가능 (재시작 또는 reload 엔드포인트로).
- 코드 레벨 롤백이 필요한 경우, `_gather_surge_candidates()` 호출만 fund_manager.py에서 주석 처리하면 SPEC-AI-012 전체가 비활성화된다(다른 탐지기에는 영향 없음).

---

## 9. 참고 (References)

- SPEC-AI-003: 4개 사전 탐지기 (`_detect_quiet_accumulation`, `_detect_news_price_divergence`, `_detect_bb_compression`, `_detect_sector_laggards`)
- SPEC-AI-004: 공시 기반 미반영 호재 탐지 시스템 (`disclosure_impact_scorer.py`)
- SPEC-AI-011: AI 펀드매니저 지배구조 인식 (보완 가능, 본 SPEC과 독립)
- 기존 `news_price_impact_service.py`의 T+1D / T+5D 반응 추적 방법론은 REQ-SURGE-006 백테스팅에 재사용
- Bayesian 보정은 `signal_verifier.py` 참조 (필요 시 향후 적용)

---

**문서 끝.**
