---
id: SPEC-AI-003
version: 1.0.0
status: Planned
created: 2026-03-31
updated: 2026-03-31
author: manager-spec
priority: High
issue_number: 0
title: Pre-emptive Buy Signal Detection
tags: [leading-indicator, fund-manager, buy-signal, technical-analysis]
---

# SPEC-AI-003: 선행 매수 신호 탐지 (Pre-emptive Buy Signal Detection)

## 1. 환경 (Environment)

### 1.1 현재 시스템 상태

- **매수 후보 선정 함수**: `fund_manager.py::_gather_pick_candidates()` (라인 321-425)
- **현재 로직**: 뉴스-종목 관계(`NewsStockRelation`)에서만 후보를 추출
- **AI 브리핑 프롬프트**: 라인 1205-1328에서 후보 데이터 기반 매수 추천 생성
- **4팩터 스코어링**: `factor_scoring.py` (뉴스감성, 기술적, 수급, 밸류에이션 각 0-100)
- **기술적 지표**: `technical_indicators.py` (SMA, RSI, MACD, 볼린저밴드, OBV 등)
- **섹터 모멘텀**: `sector_momentum.py` (`detect_momentum_sectors()`, `detect_capital_inflow()`)
- **시세 API**: `naver_finance.py` (`fetch_naver_stock_list()` KOSPI/KOSDAQ 전종목 조회 가능)

### 1.2 핵심 문제

1. **뉴스 파이프라인 의존성**: 뉴스가 없으면 후보 종목 0개 -> 빈 추천
2. **후행적 종목 선정**: 뉴스에 이미 보도된 종목 = 시장이 이미 반응한 종목
3. **핵심 원칙 위반**: 매수 추천은 가격 상승 **이전에** 이루어져야 하나, 현재 시스템은 상승 **이후** 추천

### 1.3 기존 인프라 활용

| 모듈 | 활용 데이터 | 선행 지표 연결 |
|------|------------|--------------|
| `naver_finance.py` | KOSPI/KOSDAQ 전종목 시세 | 조용한 수급 축적 스캔 |
| `technical_indicators.py` | 볼린저밴드 폭(`bb_width`), 거래량비(`volume_ratio`) | 밴드 수축 감지 |
| `sector_momentum.py` | `detect_momentum_sectors()` | 섹터 내 낙오자 발굴 |
| `news_relation.py` + `news_price_impact.py` | 뉴스-종목 관계 + 가격 반응 | 뉴스-가격 괴리 탐지 |
| `factor_scoring.py` | composite_score (0-100) | 최종 랭킹 및 검증 |

---

## 2. 가정 (Assumptions)

### 2.1 데이터 가용성

- **A1**: `fetch_naver_stock_list()`로 KOSPI/KOSDAQ 전종목의 당일 시세(현재가, 등락률, 거래량)를 실시간 조회 가능
- **A2**: `_gather_market_data()`로 개별 종목의 외국인/기관 5일 순매수, 볼린저밴드, RSI 등 기술적 지표 조회 가능
- **A3**: `NewsStockRelation` 테이블에 최근 3시간 이내 뉴스-종목 매핑 데이터 존재
- **A4**: `SectorMomentum` 테이블에 최소 5일 이상의 섹터별 일간 수익률 데이터 축적

### 2.2 시장 가정

- **A5**: 외국인+기관 동시 순매수 상태에서 가격 미반영은 선행 매수 신호로 유의미
- **A6**: 볼린저밴드 수축은 2-5 거래일 이내 방향성 결정(브레이크아웃)의 전조
- **A7**: 모멘텀 섹터 내 낙오 종목은 1-2 거래일 후행하여 섹터 평균에 수렴하는 경향

### 2.3 성능 가정

- **A8**: 전종목 스캔은 최대 2,500종목 대상이며, 1차 필터링(등락률, 시가총액)으로 100-200종목으로 축소 후 상세 분석
- **A9**: 전체 선행 신호 탐지 프로세스는 60초 이내 완료 가능

---

## 3. 요구사항 (Requirements)

### 3.1 핵심 원칙

> **REQ-AI-030 [Ubiquitous]**: 시스템은 **항상** 당일 등락률이 +3% 초과인 종목을 선행 매수 후보에서 제외해야 한다.
> WHY: 이미 상승한 종목은 선행 신호가 아닌 후행 추격 매수이므로.

> **REQ-AI-031 [Ubiquitous]**: 시스템은 **항상** 기존 `_gather_pick_candidates()`의 4가지 검증 기준(등락률 > -3%, 5일 양의 추세, 수급 양호, 밸류에이션 매력)을 최종 검증 단계에서 적용해야 한다.
> WHY: 선행 후보의 후보 발굴은 새로운 방식이나, 최종 품질 게이트는 기존 검증된 기준 유지.

### 3.2 선행 지표 1: 조용한 수급 축적 (Quiet Accumulation)

> **REQ-AI-032 [Event-Driven]**: **WHEN** 특정 종목의 `foreign_net_5d > 0` AND `institution_net_5d > 0` AND `-2% <= change_rate <= +2%` **THEN** 시스템은 해당 종목을 "조용한 수급 축적" 후보로 분류해야 한다.
> WHY: 스마트머니(외국인+기관)가 동시에 순매수 중이나 가격이 아직 미반영 = 가격 상승 전 진입 기회.

> **REQ-AI-033 [State-Driven]**: **IF** 조용한 수급 축적 후보의 `foreign_net_5d + institution_net_5d`의 합산 순매수량이 일평균 거래량의 10% 이상 **THEN** 신호 강도를 "강함"으로 설정해야 한다.
> WHY: 순매수 규모가 거래량 대비 유의미해야 실제 수급 압력으로 작용.

### 3.3 선행 지표 2: 뉴스-가격 괴리 (News-Price Divergence)

> **REQ-AI-034 [Event-Driven]**: **WHEN** 긍정 감성 뉴스가 최근 3시간 이내 발행되었고 해당 종목의 `change_rate < +1%` **THEN** 시스템은 해당 종목을 "뉴스-가격 괴리" 후보로 분류해야 한다.
> WHY: 호재 뉴스 발행 후 시장이 아직 가격에 반영하지 않은 구간 = 매수 윈도우.

> **REQ-AI-035 [State-Driven]**: **IF** 뉴스-가격 괴리 후보의 관련 뉴스가 2건 이상이고 모두 긍정 감성 **THEN** 신호 강도를 "강함"으로 설정해야 한다.
> WHY: 복수의 긍정 뉴스가 집중된 종목은 시장 반응 확률이 높음.

### 3.4 선행 지표 3: 볼린저밴드 수축 (Bollinger Band Compression)

> **REQ-AI-036 [Event-Driven]**: **WHEN** 특정 종목의 `bb_width`가 20일 평균 `bb_width`의 50% 미만이고 `volume_ratio < 0.7` **THEN** 시스템은 해당 종목을 "밴드 수축" 후보로 분류해야 한다.
> WHY: 가격 변동성과 거래량이 동시에 수축 = 에너지 축적 상태, 2-5일 이내 브레이크아웃 임박.

> **REQ-AI-037 [Unwanted]**: 시스템은 볼린저밴드 수축 후보 중 20일 이동평균이 하향 추세(sma_20_slope < 0)인 종목을 추천**하지 않아야 한다**.
> WHY: 하향 추세에서의 밴드 수축은 하방 브레이크아웃(추가 하락)으로 이어질 확률이 높음.

### 3.5 선행 지표 4: 섹터 로테이션 낙오자 (Sector Rotation Laggard)

> **REQ-AI-038 [Event-Driven]**: **WHEN** 섹터가 `detect_momentum_sectors()`에 의해 "momentum_sector"로 태그되고 해당 섹터 내 특정 종목의 5일 수익률이 섹터 평균 수익률 미만 **THEN** 시스템은 해당 종목을 "섹터 낙오자" 후보로 분류해야 한다.
> WHY: 섹터 전체가 상승 중일 때, 아직 따라가지 못한 종목은 1-2일 후행 상승 가능성.

> **REQ-AI-039 [State-Driven]**: **IF** 섹터 낙오자 후보의 5일 수익률이 섹터 평균 대비 -3%p 이상 괴리 **THEN** 신호 강도를 "강함"으로 설정해야 한다.
> WHY: 괴리가 클수록 평균 회귀(catch-up) 여력이 크기 때문.

### 3.6 통합 및 랭킹

> **REQ-AI-040 [Event-Driven]**: **WHEN** 4개 선행 지표 탐지가 완료되면 **THEN** 시스템은 모든 후보를 통합하고, 동일 종목이 복수 지표에 감지된 경우 가중 점수를 합산하여 우선순위를 결정해야 한다.
> WHY: 복수 선행 신호가 겹치는 종목이 가장 높은 확신도를 가짐.

> **REQ-AI-041 [Ubiquitous]**: 시스템은 **항상** 선행 매수 후보의 최대 개수를 10개로 제한해야 한다.
> WHY: AI 프롬프트 토큰 효율성 및 분석 품질 유지.

> **REQ-AI-042 [Event-Driven]**: **WHEN** 선행 후보와 기존 뉴스 기반 후보가 모두 존재 **THEN** 시스템은 두 소스를 병합하되, 선행 후보를 우선 배치하고 최종 10개를 AI에 전달해야 한다.
> WHY: 선행 후보가 핵심이나, 뉴스 기반 후보도 보조적 가치 있음.

### 3.7 브리핑 프롬프트 통합

> **REQ-AI-043 [Event-Driven]**: **WHEN** 선행 후보가 AI 브리핑 프롬프트에 포함될 때 **THEN** 각 후보에 감지된 선행 지표 유형과 신호 강도를 메타데이터로 제공해야 한다.
> WHY: AI가 "이 종목이 왜 선행 후보인지"를 이해해야 올바른 분석과 추천을 생성.

> **REQ-AI-044 [Ubiquitous]**: 시스템은 **항상** 선행 후보 데이터에 `leading_signals` 필드를 포함해야 한다.
> 형식: `[{"type": "quiet_accumulation"|"news_divergence"|"bb_compression"|"sector_laggard", "strength": "strong"|"moderate", "detail": "설명"}]`

---

## 4. 사양 (Specifications)

### 4.1 새 함수: `_gather_leading_candidates()`

- **위치**: `backend/app/services/fund_manager.py`
- **시그니처**: `async def _gather_leading_candidates(db: Session) -> list[dict]`
- **반환**: 기존 `_gather_pick_candidates()`와 동일한 dict 구조 + `leading_signals` 필드 추가
- **호출 시점**: `generate_briefing()` 내에서 `_gather_pick_candidates()` **이전** 호출

### 4.2 선행 지표 탐지 서브 함수

| 함수명 | 위치 | 입력 | 출력 |
|--------|------|------|------|
| `_detect_quiet_accumulation()` | `fund_manager.py` | `db: Session` | `list[dict]` |
| `_detect_news_price_divergence()` | `fund_manager.py` | `db: Session, recent_news: list` | `list[dict]` |
| `_detect_bb_compression()` | `fund_manager.py` | `db: Session` | `list[dict]` |
| `_detect_sector_laggards()` | `fund_manager.py` | `db: Session` | `list[dict]` |

### 4.3 전종목 스캔 전략

1. **1차 필터**: `fetch_naver_stock_list()`로 KOSPI+KOSDAQ 1-5페이지(250종목) 조회
2. **빠른 제외**: `change_rate > +3%` 또는 `change_rate < -5%` 종목 제외
3. **시가총액 하한**: 시가총액 1,000억 미만 종목 제외 (유동성 리스크)
4. **상세 분석**: 필터 통과 종목에 대해 개별 기술적 지표/수급 데이터 수집

### 4.4 선행 신호 가중치

| 지표 유형 | 기본 점수 | "강함" 보너스 | 복수 지표 가산 |
|-----------|----------|-------------|--------------|
| 조용한 수급 축적 | 30 | +15 | +10/추가 지표 |
| 뉴스-가격 괴리 | 25 | +15 | +10/추가 지표 |
| 볼린저밴드 수축 | 20 | +10 | +10/추가 지표 |
| 섹터 로테이션 낙오자 | 25 | +10 | +10/추가 지표 |

### 4.5 기존 코드 변경 범위

| 파일 | 변경 유형 | 설명 |
|------|----------|------|
| `fund_manager.py` | **추가** | `_gather_leading_candidates()` 및 4개 서브 함수 |
| `fund_manager.py` | **수정** | `generate_briefing()` 내 후보 수집 로직 병합 |
| `fund_manager.py` | **수정** | AI 프롬프트에 선행 지표 메타데이터 섹션 추가 |
| `factor_scoring.py` | **추가 (선택)** | 선행 신호 통합 스코어링 함수 |
| `technical_indicators.py` | **변경 없음** | 기존 `bb_width`, `volume_ratio` 그대로 활용 |
| `sector_momentum.py` | **변경 없음** | 기존 `detect_momentum_sectors()` 그대로 활용 |
| `naver_finance.py` | **변경 없음** | 기존 `fetch_naver_stock_list()` 그대로 활용 |

### 4.6 성능 요구사항

- 전체 선행 신호 탐지: 60초 이내 (비동기 병렬 처리)
- 4개 지표 탐지는 `asyncio.gather()`로 병렬 실행
- 네이버 API 호출 최소화: 캐시 활용, 페이지 단위 일괄 조회

### 4.7 에러 처리

> **REQ-AI-045 [Unwanted]**: **IF** 선행 지표 탐지 중 일부 지표가 실패 **THEN** 시스템은 실패한 지표를 건너뛰고 성공한 지표의 결과만으로 후보를 구성해야 한다. 전체 실패 시에만 기존 `_gather_pick_candidates()` 결과만 사용한다.
> WHY: 부분 실패가 전체 브리핑 생성을 차단하면 안 됨.

---

## 5. 추적성 (Traceability)

| 요구사항 ID | 구현 위치 | 테스트 시나리오 |
|------------|----------|--------------|
| REQ-AI-030 | `_gather_leading_candidates()` 제외 필터 | TC-001: +4% 종목 제외 확인 |
| REQ-AI-031 | 최종 검증 단계 | TC-002: 기존 4가지 기준 적용 확인 |
| REQ-AI-032 | `_detect_quiet_accumulation()` | TC-003: 수급 축적 감지 |
| REQ-AI-034 | `_detect_news_price_divergence()` | TC-004: 뉴스-가격 괴리 감지 |
| REQ-AI-036 | `_detect_bb_compression()` | TC-005: 밴드 수축 감지 |
| REQ-AI-038 | `_detect_sector_laggards()` | TC-006: 섹터 낙오자 감지 |
| REQ-AI-040 | 통합 랭킹 로직 | TC-007: 복수 지표 가중 합산 |
| REQ-AI-042 | 후보 병합 로직 | TC-008: 선행+뉴스 후보 병합 |
| REQ-AI-043 | 프롬프트 통합 | TC-009: leading_signals 메타데이터 |
| REQ-AI-045 | 에러 핸들링 | TC-010: 부분 실패 시 graceful degradation |
