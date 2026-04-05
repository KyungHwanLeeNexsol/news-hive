---
id: SPEC-AI-004
version: 1.0.0
status: In Progress
created: 2026-03-31
updated: 2026-04-05
author: MoAI
priority: High
issue_number: 0
title: Disclosure-Based Pre-emptive Signal System
tags: [dart, disclosure, intraday, impact-scoring, gap-analysis, paper-trading, backtest]
---

# SPEC-AI-004: 공시 기반 미반영 호재 탐지 시스템

## 0. 배경 및 목적

### 문제 정의

현재 NewsHive의 매수 신호는 뉴스/기술적 지표에 집중되어 있으나, 다음 두 가지 고가치 신호 소스가 활용되지 않고 있다:

1. **DART 공시의 장중 실시간 처리 부재**: 현재 `dart_crawler.py`는 주기적으로 공시를 수집하지만, 장중 새 공시 발생 시 즉시 충격 분석 → FundSignal 생성이 이루어지지 않는다.

2. **미반영 갭 계산 없음**: 공시 발생 후 주가가 "예상 충격 대비 얼마나 반영됐는가"를 측정하는 로직이 없다. 이미 반영된 종목과 아직 미반영인 종목을 구분할 수 없다.

### 목표

- 공시 유형·규모별 예상 시장 충격을 자동 계산한다
- 공시 후 실제 주가 반응을 측정하여 "미반영 갭"을 산출한다
- 미반영 갭이 임계값 이상인 종목을 즉시 매수 후보로 올린다
- 동종업계 파급 효과(A사 수주 → B사 주목)를 탐지한다
- 페이퍼트레이딩에 공시 기반 시그널을 자동 연동한다
- 백테스팅 통계로 시그널 품질을 측정한다

---

## 1. 환경 (Environment)

### 1.1 기존 인프라

| 모듈 | 현재 상태 | SPEC-AI-004에서의 역할 |
|------|-----------|----------------------|
| `dart_crawler.py` | DART Open API 주기적 폴링, `Disclosure` 모델 저장 | 장중 실시간 폴링 트리거 역할 확장 |
| `paper_trading.py` | 가상 포트폴리오, 포지션 관리, 방어 모드 완비 | 공시 기반 FundSignal 자동 진입 연동 |
| `signal_verifier.py` | 시그널 적중률 검증 + 베이지안 보정 | 백테스팅 통계 산출 기반 |
| `news_price_impact_service.py` | 뉴스 발행 시점 주가 스냅샷 + 1일/5일 반응 추적 | 공시 반응도 측정 방법론 재사용 |
| `sector_momentum.py` | 섹터 모멘텀 감지 | 동종업계 파급 탐지에 활용 |
| `naver_finance.py` | 실시간 주가 조회 | 공시 후 현재 반응률 측정 |
| `fund_manager.py` | AI 브리핑 + FundSignal 생성 | 공시 기반 후보를 브리핑에 주입 |

### 1.2 기존 DB 모델

- `Disclosure`: corp_code, stock_code, report_name, report_type, rcept_dt, ai_summary
  - **누락 필드**: 충격 스코어, 반영도, 미반영 갭 → 마이그레이션 필요
- `VirtualPortfolio` / `VirtualTrade` / `PortfolioSnapshot`: 페이퍼트레이딩 완비
- `FundSignal`: 기존 signal_type에 `"disclosure_impact"` 추가 필요

### 1.3 DART API

- OpenDART API: `https://opendart.fss.or.kr/api/list.json`
- `settings.DART_API_KEY` 기존 설정
- `settings.DART_CRAWL_INTERVAL_MINUTES` 기존 설정

---

## 2. 가정 (Assumptions)

- **A1**: 장중(09:00~15:30) 5분 간격 DART 폴링은 OCI 서버 리소스상 허용 가능하다
- **A2**: 수주 공시에서 수주금액은 공시 제목 또는 `ai_summary`로부터 정규식 추출 가능하다
- **A3**: 공시 발생 후 30분~2시간 이내 주가 반응이 없으면 "미반영"으로 판단한다
- **A4**: 동종업계 파급은 `Stock.sector_id`가 동일한 종목 중 시총 순위 1-3위가 반응했을 때 나머지가 따라가는 패턴이다
- **A5**: 기존 `paper_trading.py`의 `execute_paper_trade()` 함수는 `FundSignal`을 입력받아 가상 매수를 실행한다
- **A6**: 갭업 풀백 전략에서 "풀백"이란 시초가 대비 -3% 이상 하락 후 재차 지지되는 구간이다

---

## 3. 요구사항 (Requirements)

### 3.1 공시 충격 스코어링

> **REQ-DISC-001 [Event-Driven]**: **WHEN** 새로운 `Disclosure`가 저장될 때 **THEN** 시스템은 보고서 유형과 내용으로부터 예상 시장 충격 점수(0~100)를 계산하여 `Disclosure.impact_score`에 저장해야 한다.

> **REQ-DISC-002 [State-Driven]**: **IF** 공시 유형이 "수주" 또는 "매출 관련 계약" 이고 수주금액/시총 비율이 계산 가능 **THEN** `impact_score = min(수주금액/시총 × 500, 100)`으로 계산해야 한다.
> WHY: 시총 20% 수주 → impact_score=100(최대 충격), 시총 2% 수주 → impact_score=10.

> **REQ-DISC-003 [State-Driven]**: **IF** 공시 유형이 "실적 변동" **THEN** `impact_score`는 AI가 공시 내용에서 전기 대비 실적 변화율을 추출하여 `min(변화율 절대값, 100)`으로 산정한다.

> **REQ-DISC-004 [State-Driven]**: **IF** 공시 유형이 그 외(지분공시, 정기공시 등) **THEN** `impact_score`는 10~30 범위의 기본값을 유형별로 할당한다.
> - 지분공시(대량보유 변경): 25
> - M&A(합병/분할): 30
> - 신주/전환사채: -10 (희석 효과, 음수)
> - 기타: 10

### 3.2 미반영 갭 탐지

> **REQ-DISC-005 [Event-Driven]**: **WHEN** `impact_score >= 20`인 공시가 저장되고 해당 종목의 주식 코드(`stock_code`)가 존재할 때 **THEN** 시스템은 공시 발생 시점의 주가를 스냅샷(`Disclosure.baseline_price`)으로 저장해야 한다.

> **REQ-DISC-006 [Event-Driven]**: **WHEN** 공시 발생 후 30분이 경과했을 때 **THEN** 시스템은 현재 주가와 `baseline_price`를 비교하여 반영도(`reflected_pct = (현재가 - baseline_price) / baseline_price × 100`)를 `Disclosure.reflected_pct`에 저장해야 한다.

> **REQ-DISC-007 [State-Driven]**: **IF** `impact_score - reflected_pct >= 15` (미반영 갭 임계값) **THEN** 시스템은 해당 종목을 "미반영 공시 매수 후보"로 분류하고 `FundSignal`을 생성해야 한다.
> WHY: 예상 충격 30점, 실제 반영 5% → 갭 25점 → 강한 미반영 신호.

> **REQ-DISC-008 [Unwanted]**: 시스템은 `reflected_pct >= impact_score × 0.8`인 공시(이미 80% 이상 반영)를 매수 후보에서 제외**해야 한다**.
> WHY: 이미 대부분 반영된 공시에 추격 매수하면 고점 매수가 된다.

### 3.3 장중 실시간 공시 알림

> **REQ-DISC-009 [Event-Driven]**: **WHEN** 장중(09:00~15:30) 5분 주기 DART 폴링에서 새 공시가 감지될 때 **THEN** 시스템은 해당 공시를 즉시 분석(충격 스코어 계산)하고 `impact_score >= 20`이면 스케줄러를 통해 30분 후 반영도 측정 작업을 등록해야 한다.

> **REQ-DISC-010 [Event-Driven]**: **WHEN** 미반영 갭 탐지로 `FundSignal`이 생성될 때 **THEN** `FundSignal.signal_type = "disclosure_impact"`, `FundSignal.confidence = min(impact_score / 100, 0.95)`로 설정해야 한다.

### 3.4 동종업계 파급 탐지

> **REQ-DISC-011 [Event-Driven]**: **WHEN** 특정 종목에서 `impact_score >= 30`인 공시가 발생했을 때 **THEN** 시스템은 동일 섹터(`sector_id`) 내 다른 종목들의 당일 등락률을 조회하여 아직 반응(등락률 < +2%)하지 않은 종목을 "파급 후보"로 분류해야 한다.
> WHY: A사 대형 수주 → 같은 섹터 B, C사가 1~2일 후 따라 상승하는 패턴.

> **REQ-DISC-012 [State-Driven]**: **IF** 파급 후보 종목의 시총이 원인 종목 시총의 30% 이상 **THEN** 파급 신호 강도를 "strong"으로, 30% 미만이면 "moderate"로 설정해야 한다.
> WHY: 시총이 비슷한 종목일수록 파급 효과가 강하다.

> **REQ-DISC-013 [State-Driven]**: **IF** 파급 후보가 1개 이상 존재 **THEN** 해당 종목들을 `signal_type="sector_ripple"`인 `FundSignal`로 생성해야 한다.

### 3.5 장 마감 후 공시 + 다음날 풀백 전략

> **REQ-DISC-014 [Event-Driven]**: **WHEN** 15:30~18:00 사이에 수집된 공시 중 `impact_score >= 25`인 공시가 있을 때 **THEN** 시스템은 해당 종목을 "갭업 후 풀백 대기" 목록에 등록하고 `signal_type="gap_pullback_candidate"`인 `FundSignal`을 생성해야 한다.

> **REQ-DISC-015 [Event-Driven]**: **WHEN** 다음 거래일 10:00~11:30 사이에 갭업 후 풀백 대기 종목의 주가가 시초가 대비 -3% 이상 하락했다가 -1.5% 이내로 회복될 때 **THEN** 시스템은 해당 시그널을 "활성화"하고 페이퍼트레이딩 자동 매수를 실행해야 한다.
> WHY: 갭업 이후 FOMO 매수 → 차익실현 → 풀백 → 지지 확인 → 실질 상승 재개 패턴.

### 3.6 백테스팅 통계

> **REQ-DISC-016 [State-Driven]**: **IF** `signal_type IN ("disclosure_impact", "sector_ripple", "gap_pullback_candidate")`인 `FundSignal`의 검증 기간이 5일 이상 경과 **THEN** `signal_verifier.py`는 해당 시그널 유형별 적중률, 평균 수익률, 샤프 지표를 산출해야 한다.

> **REQ-DISC-017 [Event-Driven]**: **WHEN** `/api/v1/portfolio/backtest-stats` API가 호출될 때 **THEN** 시스템은 시그널 유형별 통계(`hit_rate`, `avg_return_pct`, `total_signals`, `winning_signals`)를 반환해야 한다.

> **REQ-DISC-018 [Ubiquitous]**: 시스템은 **항상** `signal_type`이 `"disclosure_impact"` | `"sector_ripple"` | `"gap_pullback_candidate"` 중 하나인 시그널에 대해 검증 결과를 `fund_signals.is_correct`, `fund_signals.exit_price_at_verify`에 기록해야 한다.

### 3.7 페이퍼트레이딩 연동

> **REQ-DISC-019 [Event-Driven]**: **WHEN** `signal_type IN ("disclosure_impact", "sector_ripple")`인 `FundSignal`이 생성될 때 **THEN** `paper_trading.py`의 `execute_paper_trade()`가 자동 호출되어 가상 매수가 실행되어야 한다.

> **REQ-DISC-020 [State-Driven]**: **IF** 포트폴리오가 방어 모드(`is_defensive_mode=True`) **THEN** 공시 기반 시그널도 방어 모드 규칙(신규 매수 차단)을 따라야 한다.

---

## 4. 사양 (Specifications)

### 4.1 DB 마이그레이션: `disclosures` 테이블 확장

```
ALTER TABLE disclosures ADD COLUMN impact_score FLOAT;         -- 예상 시장 충격 (0~100)
ALTER TABLE disclosures ADD COLUMN baseline_price INT;         -- 공시 시점 주가
ALTER TABLE disclosures ADD COLUMN reflected_pct FLOAT;        -- 실제 반영도 (%)
ALTER TABLE disclosures ADD COLUMN unreflected_gap FLOAT;      -- 미반영 갭 = impact_score - reflected_pct
ALTER TABLE disclosures ADD COLUMN ripple_checked BOOLEAN DEFAULT FALSE; -- 파급 탐지 완료 여부
ALTER TABLE disclosures ADD COLUMN disclosed_at TIMESTAMP;     -- 공시 발생 시각 (rcept_dt보다 정밀)
```

### 4.2 새 서비스: `disclosure_impact_scorer.py`

**위치**: `backend/app/services/disclosure_impact_scorer.py`

**함수 목록**:

| 함수 | 설명 |
|------|------|
| `score_disclosure_impact(disclosure: Disclosure, market_cap: int) -> float` | 공시 유형 + 규모로 충격 점수 계산 |
| `extract_contract_amount(report_name: str, ai_summary: str) -> int \| None` | 정규식으로 수주금액 추출 |
| `measure_price_reflection(stock_code: str, baseline_price: int) -> float` | 현재가 vs 기준가 반영도 계산 |
| `detect_unreflected_gap(disclosure: Disclosure) -> bool` | 미반영 갭 >= 15 여부 반환 |
| `detect_sector_ripple(db: Session, trigger_disclosure: Disclosure) -> list[dict]` | 동종업계 파급 후보 탐지 |

### 4.3 `dart_crawler.py` 확장

**기존**: 주기적 DART 폴링 → DB 저장  
**추가**:
- `fetch_dart_disclosures()` 완료 후 `impact_score >= 20` 공시에 대해 `capture_baseline_price()` 호출
- 장중(09:00~15:30) 감지 시 → 30분 후 반영도 측정 스케줄 등록 (`APScheduler one-shot job`)
- 장마감 후(15:30~18:00) 감지 시 → `gap_pullback_candidate` FundSignal 생성

### 4.4 `fund_manager.py` 통합

`_gather_leading_candidates()` (SPEC-AI-003에서 정의) 이후 단계에 추가:
- `_gather_disclosure_candidates(db)` 함수 추가
- 반환 형식: 기존 후보 dict 구조 + `"disclosure_type"`, `"impact_score"`, `"unreflected_gap"` 필드

### 4.5 새 API 엔드포인트

**파일**: `backend/app/api/v1/portfolio.py`

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/api/v1/portfolio/backtest-stats` | GET | 시그널 유형별 백테스트 통계 |
| `/api/v1/portfolio/disclosure-signals` | GET | 활성 공시 기반 시그널 목록 |
| `/api/v1/portfolio/paper-performance` | GET | 페이퍼트레이딩 누적 성과 |

### 4.6 `fund_signals` 테이블 확장

```
ALTER TABLE fund_signals ADD COLUMN disclosure_id INT REFERENCES disclosures(id);
```
공시 기반 시그널에서 원인 공시를 추적 가능하게 한다.

---

## 5. 수용 기준 (Acceptance Criteria)

| ID | 기준 | 검증 방법 |
|----|------|-----------|
| AC-001 | `score_disclosure_impact()`가 수주금액/시총=10% 공시에 대해 impact_score=50을 반환한다 | 단위 테스트 |
| AC-002 | 공시 발생 30분 후 `reflected_pct`가 올바르게 계산되어 DB에 저장된다 | 통합 테스트 |
| AC-003 | `impact_score=40`, `reflected_pct=5`인 공시에서 미반영 갭=35 → FundSignal 생성됨 | 통합 테스트 |
| AC-004 | `impact_score=10`, `reflected_pct=35`인 공시(이미 반영)에서 FundSignal 생성 안 됨 | 단위 테스트 |
| AC-005 | A사 `impact_score >= 30` 공시 → 동일 섹터 B사(등락률 < +2%)가 파급 후보로 탐지됨 | 통합 테스트 |
| AC-006 | 장마감 후 `impact_score >= 25` 공시 → `gap_pullback_candidate` FundSignal 생성됨 | 통합 테스트 |
| AC-007 | `FundSignal(signal_type="disclosure_impact")` 생성 시 `execute_paper_trade()` 자동 호출됨 | 통합 테스트 |
| AC-008 | `/api/v1/portfolio/backtest-stats` 응답에 `hit_rate`, `avg_return_pct`, `total_signals` 포함됨 | API 테스트 |
| AC-009 | 방어 모드 중 `disclosure_impact` 시그널이 가상 매수를 실행하지 않음 | 단위 테스트 |
| AC-010 | `test_disclosure_impact_scorer.py` 커버리지 >= 85% | pytest --cov |

---

## 6. 구현 우선순위

| 우선순위 | 요구사항 | 예상 구현 복잡도 |
|---------|---------|----------------|
| P1 | REQ-DISC-001~004 (충격 스코어링) | 낮음 |
| P1 | REQ-DISC-005~008 (미반영 갭 탐지) | 중간 |
| P2 | REQ-DISC-009~010 (장중 실시간 알림) | 중간 |
| P2 | REQ-DISC-011~013 (동종업계 파급) | 중간 |
| P3 | REQ-DISC-014~015 (갭업 후 풀백 전략) | 높음 |
| P3 | REQ-DISC-016~018 (백테스팅 통계) | 낮음 (기존 signal_verifier 확장) |
| P3 | REQ-DISC-019~020 (페이퍼트레이딩 연동) | 낮음 (기존 paper_trading 연동) |

---

## 7. 기술 제약

- Python 3.12+, FastAPI, SQLAlchemy 2.0, APScheduler
- DART Open API 일 요청 한도: 10,000회 (5분 주기 × 8시간 = 96회/일, 여유 충분)
- OCI VM.Standard.E2.1.Micro: 1 OCPU, 1GB RAM — APScheduler one-shot job 부하 주의
- 정규식 수주금액 추출이 실패할 경우 AI(Gemini) 보조 추출 fallback 허용

---

## 8. 관련 SPEC

- **SPEC-AI-003**: 기술적 선행 지표 탐지 (선행 수급, BB, 섹터 로테이션) — 본 SPEC과 병렬 실행, 통합 후보 풀에 합산
- **SPEC-AI-002**: 뉴스-가격 반응 추적 — `news_price_impact_service.py` 방법론을 공시 반응 측정에 재사용
