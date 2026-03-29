---
id: SPEC-AI-002
version: "1.0.0"
status: draft
created: "2026-03-29"
updated: "2026-03-29"
author: zuge3
priority: high
issue_number: 0
depends_on: ["SPEC-AI-001"]
---

# AI 펀드 예측력 2단계 고도화

## 개요

SPEC-AI-001(Phase A/B/C)에서 구축한 4-factor scoring, A/B 테스트, 베이지안 보정, 페이퍼 트레이딩 인프라 위에
**예측 정확도를 한 단계 더 끌어올리기 위한 고급 분석 기능**을 추가한다.

핵심 목표:
- 다중 시간축 분석으로 단기 노이즈를 걸러내고 중장기 추세를 반영
- 섹터 로테이션 감지로 자금 흐름 변화를 선제 포착
- DART 공시 기반 어닝 서프라이즈 예측
- 동일 섹터 상관 시그널 중복 제거
- 시장 변동성 기반 동적 포지션 사이징
- 과거 유사 패턴 매칭으로 시그널 신뢰도 보강
- Chain-of-Thought AI 프롬프트로 분석 깊이 향상
- 원자재 가격 크로스 검증
- REQ-AI-011 ML 앙상블 데이터 준비 완료 시 고도화

## 환경 (Environment)

- Backend: Python 3.11+ / FastAPI / SQLAlchemy 2.0 / PostgreSQL 16
- AI Provider: Groq (primary) + Gemini x3 (fallback) via ai_client.py
- Data Sources: KIS API, Naver Finance, DART, Google/Naver/Yahoo News, Korean RSS
- Scheduler: APScheduler (10분 뉴스 크롤, 일 1회 브리핑)
- 기존 인프라:
  - fund_manager.py (52KB): 시그널 생성 파이프라인
  - factor_scoring.py: 4-factor 스코어링 (news_sentiment, technical, supply_demand, valuation)
  - prompt_versioner.py: A/B 테스트 프레임워크
  - signal_verifier.py: 시그널 검증 (6h/12h fast verify)
  - naver_finance.py: 주가/재무 데이터 수집
  - dart_crawler.py: DART 공시 수집
  - paper_trading 시스템: 가상 매매 시뮬레이션
- 기존 테이블: fund_signals, daily_briefings, news_price_impact, macro_alerts, paper_trades

## 전제 (Assumptions)

- A1: SPEC-AI-001 Phase A/B가 완료되어 4-factor scoring, A/B 테스트, 오류 패턴 분류가 운영 중이다
- A2: fund_signals 테이블에 60일 이상의 검증 데이터가 축적되어 패턴 분석이 가능하다
- A3: KIS API에서 주간/월간 OHLCV 데이터를 조회할 수 있다
- A4: DART 공시 데이터(dart_crawler.py)가 실적 관련 공시를 수집 중이다
- A5: 원자재 가격 데이터가 commodity 관련 기존 시스템에서 접근 가능하다
- A6: Groq/Gemini 모델이 한국어 Chain-of-Thought 프롬프트를 잘 처리한다
- A7: REQ-AI-011(ML 앙상블)과 REQ-AI-012(섹터 전파)는 90일+ 데이터 축적 후 활성화 예정

---

## Module 1: 다중 시간축 분석 (Multi-Timeframe Analysis)

### REQ-AI-014: 주간/월간 추세 통합 분석

**WHEN** 시그널 생성 시 개별 종목의 기술적 분석을 수행할 때 **THEN** 시스템은 일봉 외에 주간(5일)/월간(20일) 시간축 데이터를 함께 분석해야 한다.

시스템은 **항상** 다음 3개 시간축의 추세 방향을 산출해야 한다:
- 단기(5일): 5일 이동평균 기울기 + RSI(14)
- 중기(20일): 20일 이동평균 기울기 + MACD 시그널
- 장기(60일): 60일 이동평균 대비 현재가 위치

**WHEN** 3개 시간축 추세가 모두 같은 방향(상승 또는 하락)일 때 **THEN** 시스템은 "추세 정렬(trend_aligned)" 태그를 부여하고 technical factor 점수에 +15점 가산해야 한다.

**IF** 단기 추세가 상승이나 장기 추세가 하락인 경우(추세 역행) **THEN** 시스템은 "추세 역행(trend_divergent)" 경고를 시그널에 포함하고 confidence를 0.1 감산해야 한다.

수용 기준:
- fund_signals 테이블에 trend_alignment 필드 추가 (aligned/divergent/mixed)
- factor_scoring.py의 compute_technical_score()에 다중 시간축 로직 통합
- 일간 브리핑 프롬프트에 추세 정렬 정보 포함
- 추세 정렬 시그널의 적중률이 비정렬 대비 10%p 이상 높음 (30일 후 검증)

### REQ-AI-015: 거래량 이상 탐지

**WHEN** 일간 거래량이 20일 평균 거래량의 2배 이상일 때 **THEN** 시스템은 "거래량 이상(volume_spike)" 이벤트를 감지하고 시그널 생성 시 해당 정보를 AI 프롬프트에 주입해야 한다.

**WHILE** volume_spike가 감지된 종목에 대해 **WHEN** 가격이 상승 중일 때 **THEN** 시스템은 supply_demand factor 점수에 +10점을 가산해야 한다.

수용 기준:
- 거래량 이상 탐지 로직이 factor_scoring.py에 통합
- volume_spike 이벤트가 fund_signals의 metadata JSON에 기록
- AI 프롬프트에 "거래량 급증 종목" 섹션 포함

---

## Module 2: 섹터 로테이션 감지 (Sector Rotation Detection)

### REQ-AI-016: 섹터별 자금 흐름 추적

시스템은 **항상** 일간 브리핑 생성 시 각 섹터의 최근 5일간 평균 등락률과 거래대금 변화율을 계산해야 한다.

**WHEN** 특정 섹터의 5일 평균 등락률이 전체 시장 대비 +2%p 이상 초과 성과를 보일 때 **THEN** 시스템은 해당 섹터를 "모멘텀 섹터(momentum_sector)"로 태그해야 한다.

**WHEN** 특정 섹터가 3일 연속 거래대금 증가 + 양의 수익률을 기록할 때 **THEN** 시스템은 "자금 유입(capital_inflow)" 알림을 생성해야 한다.

수용 기준:
- sector_momentum 테이블 생성 (sector_id, date, avg_return_5d, volume_change_5d, momentum_tag)
- 일간 브리핑에 "섹터 모멘텀 분석" 섹션 추가
- 모멘텀 섹터 내 종목에 대한 시그널 생성 시 가산점 부여

### REQ-AI-017: 섹터 로테이션 패턴 인식

**WHEN** 이전 모멘텀 섹터에서 자금이 유출되고(5일 평균 등락률 하락 전환) 새로운 섹터에 자금이 유입될 때 **THEN** 시스템은 "섹터 로테이션(sector_rotation)" 이벤트를 생성하고 AI 프롬프트에 포함해야 한다.

시스템은 **항상** 로테이션 이벤트 발생 시 이전 모멘텀 섹터의 매수 시그널을 보수적으로 조정(confidence -0.15)해야 한다.

수용 기준:
- sector_rotation_events 테이블 생성 (from_sector, to_sector, detected_at, confidence)
- 로테이션 감지 후 이전 섹터 시그널의 confidence 자동 하향 조정
- 브리핑에 "섹터 로테이션 알림" 포함

---

## Module 3: DART 어닝 서프라이즈 예측 (Earnings Surprise Prediction)

### REQ-AI-018: 실적 공시 사전 시그널

**WHEN** DART에서 특정 종목의 실적 공시가 예정되어 있을 때(공시 예정일 D-5) **THEN** 시스템은 해당 종목의 과거 실적 서프라이즈 패턴, 동종 섹터 실적 동향, 관련 뉴스 감성을 종합하여 "어닝 프리뷰(earnings_preview)" 분석을 생성해야 한다.

**IF** 어닝 프리뷰에서 긍정적 서프라이즈 확률이 60% 이상으로 판단될 때 **THEN** 시스템은 해당 종목에 대한 매수 시그널의 confidence에 +0.1을 가산해야 한다.

시스템은 실적 공시 **이후** 실제 서프라이즈 결과와 예측을 비교하여 정확도를 추적해야 한다.

수용 기준:
- dart_crawler.py에서 실적 관련 공시 필터링 로직 추가
- earnings_preview 결과가 fund_signals metadata에 포함
- 실적 발표 후 예측 vs 실제 비교 로그 기록
- AI 프롬프트에 "실적 시즌 분석" 섹션 포함

---

## Module 4: 시그널 상관관계 분석 (Signal Correlation Analysis)

### REQ-AI-019: 동일 섹터 시그널 중복 제거

**WHEN** 같은 섹터 내에서 동일 브리핑에 3개 이상의 매수 시그널이 생성될 때 **THEN** 시스템은 시그널 간 상관관계를 분석하고 가장 강한 시그널 2개만 최종 추천에 포함해야 한다.

시스템은 **항상** 섹터 내 시그널 수를 최대 2개로 제한하되, 다음 기준으로 우선순위를 결정해야 한다:
1. composite_score 상위
2. trend_alignment가 "aligned"인 종목 우선
3. volume_spike가 감지된 종목 우선

**가능하면** 사용자에게 "동일 섹터 X에서 N개 시그널 중 상위 2개를 선정" 메시지를 브리핑에 포함한다.

수용 기준:
- 섹터별 시그널 수 제한 로직이 fund_manager.py에 구현
- 제외된 시그널은 "섹터 중복 제거" 사유와 함께 로그 기록
- 브리핑에 섹터별 시그널 분산 정보 표시

---

## Module 5: 동적 리스크 관리 (Dynamic Risk Management)

### REQ-AI-020: 시장 변동성 기반 포지션 사이징

**WHILE** KOSPI 일간 변동성(20일 표준편차)이 2% 이상일 때 **THEN** 시스템은 시그널의 suggested_weight를 기본값의 70%로 조정해야 한다.

**WHILE** KOSPI 일간 변동성이 3% 이상(고변동성)일 때 **THEN** 시스템은 모든 매수 시그널의 confidence를 0.15 감산하고 "고변동성 주의(high_volatility_warning)" 태그를 부여해야 한다.

시스템은 **항상** 현재 시장 변동성 레벨(low/normal/high/extreme)을 일간 브리핑 상단에 표시해야 한다.

수용 기준:
- market_volatility 계산 로직 구현 (KOSPI 20일 표준편차)
- 변동성 레벨에 따른 포지션 사이징 자동 조정
- fund_signals에 volatility_level 필드 추가
- 브리핑에 "시장 변동성 지표" 섹션 포함

### REQ-AI-021: 최대 손실 제한 (Max Drawdown Control)

**WHEN** 페이퍼 트레이딩 포트폴리오의 누적 손실이 -10% 이하로 하락할 때 **THEN** 시스템은 신규 매수 시그널 생성을 일시 중단하고 "방어 모드(defensive_mode)" 상태로 전환해야 한다.

**WHILE** 방어 모드일 때 **THEN** 시스템은 기존 포지션의 손절 기준을 -5%에서 -3%로 강화해야 한다.

**WHEN** 포트폴리오 수익률이 -5% 이상으로 회복될 때 **THEN** 시스템은 방어 모드를 해제하고 정상 시그널 생성을 재개해야 한다.

수용 기준:
- 방어 모드 상태 관리 (fund_config 또는 별도 상태 테이블)
- 방어 모드 진입/해제 이력 로그
- 방어 모드 시 브리핑에 "현재 방어 모드 활성화" 경고 표시

---

## Module 6: 과거 유사 패턴 매칭 (Historical Pattern Matching)

### REQ-AI-022: 시장 상황 유사도 분석

**WHEN** 시그널 생성 시 **THEN** 시스템은 현재 시장 상황(KOSPI 등락률, 섹터 분포, 거래대금, 변동성)과 유사한 과거 시점을 fund_signals 이력에서 탐색하고, 당시 시그널의 적중률을 AI 프롬프트에 참조 정보로 주입해야 한다.

유사도 측정 기준:
- KOSPI 5일 수익률 차이 1%p 이내
- 변동성 레벨 동일
- 모멘텀 섹터 1개 이상 겹침

**가능하면** "현재와 유사한 과거 시장 상황에서의 시그널 적중률: X%" 형태의 레퍼런스를 브리핑에 포함한다.

수용 기준:
- 유사 패턴 매칭 함수 구현 (최소 30일 이력 필요)
- AI 프롬프트에 유사 과거 시점 정보 포함
- 매칭된 과거 시점의 시그널 성과 통계 표시

---

## Module 7: Chain-of-Thought AI 프롬프트 고도화

### REQ-AI-023: 구조화된 분석 프롬프트

시스템은 **항상** AI에 시그널 분석을 요청할 때 다음의 Chain-of-Thought 구조를 프롬프트에 포함해야 한다:

```
[STEP 1: 시장 환경 진단]
현재 시장 변동성, 섹터 로테이션, 매크로 리스크를 종합하여 시장 환경을 진단하시오.

[STEP 2: 종목별 팩터 분석]
각 후보 종목에 대해 4개 팩터(뉴스, 기술적, 수급, 밸류에이션) 점수를 기반으로 강약점을 분석하시오.

[STEP 3: 추세 정렬 검증]
다중 시간축(5일/20일/60일) 추세 방향이 일치하는지 확인하시오.

[STEP 4: 리스크 평가]
과거 유사 시장 상황의 적중률, 섹터 중복 리스크, 어닝 이벤트 유무를 평가하시오.

[STEP 5: 최종 추천 및 근거]
매수 추천 종목과 구체적 근거를 제시하시오. 각 추천에 대해 "가장 큰 리스크"도 명시하시오.
```

**WHEN** AI 응답에서 STEP 1~5 중 하나라도 누락되면 **THEN** 시스템은 해당 시그널의 confidence를 0.1 감산하고 "불완전 분석(incomplete_analysis)" 태그를 부여해야 한다.

수용 기준:
- fund_manager.py의 프롬프트가 5단계 CoT 구조로 변경
- AI 응답 파싱 시 STEP 누락 감지 로직 구현
- A/B 테스트로 CoT 프롬프트 vs 기존 프롬프트 성능 비교
- CoT 프롬프트 사용 시그널의 분석 깊이가 정성적으로 향상

---

## Module 8: 원자재 가격 크로스 검증 (Commodity Cross-Validation)

### REQ-AI-024: 원자재 연관 종목 검증

**WHEN** 원자재 관련 섹터(철강, 정유, 화학, 비철금속) 종목에 대한 시그널을 생성할 때 **THEN** 시스템은 관련 원자재 가격 동향(최근 5일 추세)을 확인하고 시그널과의 정합성을 검증해야 한다.

**IF** 종목 시그널이 매수이나 관련 원자재 가격이 5일 연속 하락 중일 때 **THEN** 시스템은 "원자재 역행(commodity_divergence)" 경고를 시그널에 포함하고 confidence를 0.1 감산해야 한다.

수용 기준:
- 섹터-원자재 매핑 테이블 구현 (철강-철광석, 정유-WTI 등)
- 원자재 가격 추세가 AI 프롬프트에 포함
- commodity_divergence 태그가 fund_signals metadata에 기록

---

## Module 9: ML 앙상블 준비 (REQ-AI-011 확장)

### REQ-AI-025: 피처 엔지니어링 파이프라인

시스템은 **항상** REQ-AI-011 ML 앙상블 모델 활성화를 대비하여 다음 피처를 일별로 계산하고 저장해야 한다:
- 4-factor 점수 (news_sentiment, technical, supply_demand, valuation)
- 추세 정렬 상태 (aligned/divergent/mixed)
- 섹터 모멘텀 점수
- 시장 변동성 레벨
- 거래량 이상 여부
- 최근 5건 시그널 적중률

**WHEN** 90일 이상의 피처 데이터가 축적되면 **THEN** 시스템은 REQ-AI-011 ML 앙상블 모델 학습이 가능한 상태임을 관리자에게 알려야 한다.

수용 기준:
- ml_features 테이블 생성 (daily feature snapshot)
- 피처 엔지니어링 로직이 일간 브리핑 후 자동 실행
- 90일 데이터 축적 시 알림 로직 구현

---

## 추적 태그

| TAG | 설명 | 관련 파일 |
|-----|------|-----------|
| SPEC-AI-002 | 본 SPEC 전체 | - |
| REQ-AI-014 | 다중 시간축 분석 | factor_scoring.py, fund_manager.py |
| REQ-AI-015 | 거래량 이상 탐지 | factor_scoring.py |
| REQ-AI-016 | 섹터 자금 흐름 추적 | sector_momentum.py (신규) |
| REQ-AI-017 | 섹터 로테이션 패턴 | sector_momentum.py (신규) |
| REQ-AI-018 | DART 어닝 서프라이즈 | dart_crawler.py, fund_manager.py |
| REQ-AI-019 | 섹터 시그널 중복 제거 | fund_manager.py |
| REQ-AI-020 | 동적 포지션 사이징 | fund_manager.py |
| REQ-AI-021 | Max Drawdown 제어 | fund_manager.py, paper_trading |
| REQ-AI-022 | 유사 패턴 매칭 | fund_manager.py |
| REQ-AI-023 | CoT 프롬프트 고도화 | fund_manager.py |
| REQ-AI-024 | 원자재 크로스 검증 | fund_manager.py |
| REQ-AI-025 | ML 피처 엔지니어링 | ml_features.py (신규) |
