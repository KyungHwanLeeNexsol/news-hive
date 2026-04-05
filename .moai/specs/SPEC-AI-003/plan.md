---
id: SPEC-AI-003
version: 1.0.0
status: Planned
created: 2026-03-31
updated: 2026-03-31
author: manager-spec
priority: High
tags: [leading-indicator, fund-manager, buy-signal, implementation-plan]
---

# SPEC-AI-003 구현 계획: 선행 매수 신호 탐지

## 1. 마일스톤

### Primary Goal: 4개 선행 지표 탐지 함수 구현

**범위**: `fund_manager.py`에 `_gather_leading_candidates()` 및 4개 서브 함수 추가

**작업 분해**:

1. **전종목 스캔 유틸리티 함수 작성**
   - `_scan_market_stocks(db)` 함수: KOSPI+KOSDAQ 상위 250종목 조회
   - 1차 필터: `change_rate > +3%` 또는 `< -5%` 제외, 시가총액 1,000억 미만 제외
   - 반환: 필터 통과 종목 리스트 (code, name, change_rate, market_cap, volume)

2. **`_detect_quiet_accumulation(db)` 구현**
   - 필터 통과 종목 중 `foreign_net_5d > 0 AND institution_net_5d > 0 AND -2% <= change_rate <= +2%`
   - 신호 강도 판정: 합산 순매수 >= 일평균 거래량 10% -> "strong"
   - 개별 종목 `_gather_market_data()` 호출 필요 (비동기 병렬)

3. **`_detect_news_price_divergence(db, recent_news)` 구현**
   - `NewsStockRelation`에서 3시간 이내 긍정 뉴스 연결 종목 추출
   - 해당 종목의 `change_rate < +1%` 조건 필터
   - 2건 이상 긍정 뉴스 -> "strong"

4. **`_detect_bb_compression(db)` 구현**
   - 필터 통과 종목에 대해 `calculate_technical_indicators()` 호출
   - `bb_width < 20일 평균 bb_width의 50%` AND `volume_ratio < 0.7` 조건
   - 추가 필터: `sma_20_slope >= 0` (하향 추세 제외)
   - 주가 히스토리 필요 -> `fetch_stock_price_history()` 활용

5. **`_detect_sector_laggards(db)` 구현**
   - `detect_momentum_sectors()` 호출하여 모멘텀 섹터 목록 확보
   - 모멘텀 섹터 내 종목들의 5일 수익률 계산
   - 섹터 평균 미만 종목 = 낙오자 후보
   - 섹터 평균 대비 -3%p 이상 괴리 -> "strong"

6. **`_gather_leading_candidates(db)` 통합 함수 작성**
   - 4개 탐지 함수를 `asyncio.gather()`로 병렬 실행
   - 동일 종목 복수 감지 시 점수 합산 (가중치 테이블 참조)
   - 상위 10개 선정
   - 각 후보에 `leading_signals` 필드 추가
   - 기존 `_gather_pick_candidates()` 4가지 검증 기준으로 최종 필터

### Secondary Goal: 브리핑 통합

**범위**: `generate_briefing()` 함수 수정

1. **후보 수집 로직 변경**
   - `_gather_leading_candidates(db)` 먼저 호출
   - `_gather_pick_candidates(db, recent_news)` 보조 호출
   - 두 결과 병합: 선행 후보 우선, 최대 10개

2. **AI 프롬프트 수정**
   - "매수 후보 종목 실시간 데이터" 섹션에 `leading_signals` 정보 추가
   - 각 후보 종목 설명에 선행 지표 유형 및 강도 표시
   - AI에게 "선행 신호 기반 추천은 아직 가격이 움직이지 않은 종목이므로, 진입 근거를 선행 지표 중심으로 기술" 지시 추가

3. **프롬프트 필드 매핑 추가**
   ```
   - leading_signals: 감지된 선행 지표 유형과 강도
     예: [{"type": "quiet_accumulation", "strength": "strong", "detail": "외국인+기관 5일 순매수 합산 12,000주, 등락률 +0.3%"}]
   ```

### Final Goal: 품질 검증 및 모니터링

1. **로깅 강화**
   - 각 선행 지표별 감지 종목 수 로깅
   - 전체 스캔 소요 시간 로깅
   - 병합 결과(선행 vs 뉴스 기반 비율) 로깅

2. **성능 최적화**
   - 네이버 API 호출 수 모니터링 (rate limit 회피)
   - `asyncio.Semaphore`로 동시 API 호출 제한 (최대 5개)
   - 캐시 히트율 모니터링

### Optional Goal: 팩터 스코어링 확장

1. **`factor_scoring.py`에 선행 신호 팩터 추가** (선택적)
   - `compute_leading_signal_score(leading_signals)` 함수
   - 5번째 팩터로 가중치 배분 (기존 4팩터 가중치 재조정)
   - 현재 구현에서는 단순 가중 합산으로 충분하므로, 복잡도 증가 시 보류 가능

---

## 2. 기술적 접근

### 2.1 아키텍처 설계

```
generate_briefing()
    |
    +-- _gather_leading_candidates(db)     # 신규: 선행 후보
    |       |
    |       +-- _scan_market_stocks(db)     # 전종목 1차 필터
    |       +-- asyncio.gather(
    |       |       _detect_quiet_accumulation(),
    |       |       _detect_news_price_divergence(),
    |       |       _detect_bb_compression(),
    |       |       _detect_sector_laggards()
    |       |   )
    |       +-- _merge_and_rank_signals()   # 통합 랭킹
    |       +-- _validate_with_existing_criteria()  # 기존 4가지 검증
    |
    +-- _gather_pick_candidates(db, news)   # 기존: 뉴스 기반 후보
    |
    +-- _merge_all_candidates()             # 병합: 선행 우선 + 뉴스 보조
```

### 2.2 데이터 흐름

1. **1차 스캔** (전종목): `fetch_naver_stock_list()` 5페이지 = 250종목
   - KOSPI 3페이지 (150종목) + KOSDAQ 2페이지 (100종목)
   - 응답 필드: stock_code, name, current_price, change_rate, volume, market_cap

2. **1차 필터링** (250 -> ~100-150종목):
   - `change_rate > +3%` 제외 (이미 상승)
   - `change_rate < -5%` 제외 (급락 위험)
   - `market_cap < 100,000,000,000` 제외 (유동성 부족)

3. **지표별 상세 분석** (~100-150 -> 지표별 0-20종목):
   - 조용한 수급: `_gather_market_data()` 개별 호출 필요
   - 뉴스 괴리: DB 쿼리 (뉴스 관계) + 시세 확인
   - 밴드 수축: `fetch_stock_price_history()` + `calculate_technical_indicators()`
   - 섹터 낙오: `detect_momentum_sectors()` + 섹터 내 종목 수익률

4. **통합 랭킹**: 점수 합산 -> 상위 10개 선정 -> 기존 검증 적용

### 2.3 성능 전략

| 단계 | API 호출 수 | 소요 시간 (예상) | 전략 |
|------|------------|-----------------|------|
| 전종목 스캔 | 5회 (페이지) | ~3초 | 네이버 캐시 활용 |
| 조용한 수급 | ~100회 (개별 시세) | ~20초 | `asyncio.gather` + `Semaphore(5)` |
| 뉴스 괴리 | 0회 (DB 쿼리) | ~1초 | SQLAlchemy 인메모리 |
| 밴드 수축 | ~100회 (가격 히스토리) | ~25초 | `asyncio.gather` + 캐시 |
| 섹터 낙오 | 0회 (DB 쿼리) | ~1초 | 기존 함수 활용 |
| **합계** | ~205회 | ~50초 | 60초 이내 목표 |

**최적화 방안**:
- 조용한 수급과 밴드 수축은 동일 종목 대상이므로, 시세 데이터를 공유하여 API 호출 중복 제거
- `_scan_market_stocks()`의 1차 필터 결과를 모든 지표 함수에 공유
- 실제 구현 시 API 호출을 ~100-120회로 축소 가능

### 2.4 리스크 및 대응

| 리스크 | 영향 | 대응 |
|--------|------|------|
| 네이버 API rate limit | 전종목 스캔 실패 | `Semaphore(5)` + 호출 간 100ms 딜레이 |
| 전종목 스캔 60초 초과 | 브리핑 생성 지연 | 타임아웃 45초 설정, 초과 시 확보된 결과만 사용 |
| 선행 후보 0개 | 빈 추천 | 기존 `_gather_pick_candidates()` 폴백 |
| 외국인/기관 데이터 미제공 종목 | 조용한 수급 미감지 | 해당 종목 건너뛰기, 다른 지표로 보완 |
| 주가 히스토리 부족 (상장 20일 미만) | 볼린저밴드 계산 불가 | 해당 종목 밴드 수축 탐지에서 제외 |

---

## 3. 의존성

### 3.1 기존 모듈 의존성 (변경 없이 사용)

- `naver_finance.py`: `fetch_naver_stock_list()`, `fetch_stock_price_history()`, `fetch_stock_detail()`
- `technical_indicators.py`: `calculate_technical_indicators()` (bb_width, volume_ratio 활용)
- `sector_momentum.py`: `detect_momentum_sectors()`, `calculate_sector_momentum()`
- `factor_scoring.py`: `compute_composite_score()` (최종 검증용)

### 3.2 DB 모델 의존성

- `NewsStockRelation`: 뉴스-가격 괴리 탐지
- `NewsPriceImpact`: 뉴스 감성 판단 보조
- `SectorMomentum`: 섹터별 일간 수익률
- `Stock`, `Sector`: 종목-섹터 매핑

### 3.3 관련 SPEC

- **SPEC-AI-001**: 4팩터 스코어링 엔진 (검증 기준으로 활용)
- **SPEC-AI-002**: 섹터 모멘텀 추적 (`detect_momentum_sectors()` 직접 활용)

---

## 4. 구현 순서

```
[Primary Goal]
  1. _scan_market_stocks()          -- 전종목 스캔 유틸리티
  2. _detect_quiet_accumulation()   -- 수급 축적 탐지
  3. _detect_news_price_divergence()-- 뉴스 괴리 탐지
  4. _detect_bb_compression()       -- 밴드 수축 탐지
  5. _detect_sector_laggards()      -- 섹터 낙오자 탐지
  6. _gather_leading_candidates()   -- 통합 함수

[Secondary Goal]
  7. generate_briefing() 후보 수집 로직 변경
  8. AI 프롬프트 선행 지표 메타데이터 섹션 추가

[Final Goal]
  9. 로깅 및 모니터링 강화
  10. 성능 최적화 (API 호출 최소화)

[Optional Goal]
  11. factor_scoring.py 선행 신호 팩터 확장
```
