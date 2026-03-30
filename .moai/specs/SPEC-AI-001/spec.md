---
id: SPEC-AI-001
version: "1.0.0"
status: completed
created: "2026-03-28"
updated: "2026-03-28"
author: zuge3
priority: high
issue_number: 0
---

# AI 펀드 예측 시스템 고도화 마스터 SPEC

## 개요

NewsHive AI 펀드매니저 시스템의 예측 정확도를 체계적으로 개선하기 위한 마스터 SPEC.
fund_manager.py 기반 시그널 생성 파이프라인의 필터링, 피드백 루프, 다중 팩터 스코어링,
A/B 테스트, 고급 예측 모델을 3단계(Phase A/B/C)로 고도화한다.

## 환경 (Environment)

- Backend: Python 3.11+ / FastAPI / SQLAlchemy 2.0 / PostgreSQL 16
- AI Provider: OpenRouter (primary) + Gemini (fallback x3)
- Data Sources: KIS API, Naver Finance, DART, Google News, Naver News API
- Scheduler: APScheduler (30분 간격 크롤링, 일 1회 브리핑)
- 기존 테이블: fund_signals, daily_briefings, portfolio_reports, news_price_impact, macro_alerts
- 기존 SPEC: SPEC-RELATION-001 (news_price_impact 연동 완료)

## 전제 (Assumptions)

- KIS API 및 Naver Finance 데이터는 장중 실시간 수준으로 접근 가능하다
- AI 프로바이더(OpenRouter/Gemini)의 응답 품질은 프롬프트 설계에 의해 제어 가능하다
- 최소 30일 이상의 fund_signals 이력이 축적되어 통계적 분석이 가능하다
- news_price_impact 테이블에 30일 이상 데이터가 존재한다 (SPEC-RELATION-001 기반)
- MacroAlert 테이블은 키워드 기반으로 현재 운영 중이다

---

## Module 1: 시그널 필터링 최적화 (Phase A)

### REQ-AI-001: 매수 후보 필터링 임계값 완화

시스템은 **항상** 매수 후보 종목 필터링 시 당일 등락률(change_rate) 임계값을 -3% 이상으로 적용해야 한다.

시스템은 **항상** 매수 추천 필수 조건 4가지(등락률, 5일 추세, 수급, 밸류에이션) 중 3가지 이상 충족 시 후보로 포함해야 한다.

**WHEN** 모든 4가지 조건을 충족하지 못하는 종목이 3-of-4를 충족할 때 **THEN** 시스템은 해당 종목을 "관망" 대신 "조건부 매수 후보"로 분류하고 AI 분석에 포함해야 한다.

**IF** 당일 등락률이 -3% 미만인 경우 **THEN** 시스템은 해당 종목을 매수 후보에서 제외하고 "급락 회피" 태그를 부여해야 한다.

수용 기준:
- 일일 매수 후보 종목 수가 기존 대비 40% 이상 증가
- -3% 이상 -1% 미만 종목이 후보에 포함됨
- 3-of-4 조건 충족 종목에 "조건부" 태그 부여

### REQ-AI-002: 시간 가중 뉴스 스코어링

**WHEN** 뉴스를 수집하여 AI 프롬프트에 주입할 때 **THEN** 시스템은 발행 시간 기반 가중치를 적용해야 한다:
- 24시간 이내: 1.0x (최대 가중)
- 24~48시간: 0.7x
- 48~72시간: 0.4x

시스템은 **항상** 가중치가 적용된 뉴스 목록을 중요도 순으로 정렬하여 AI에 전달해야 한다.

수용 기준:
- 프롬프트 내 뉴스 목록에 시간 가중치 표시
- 24시간 이내 뉴스가 목록 상단에 위치
- 72시간 초과 뉴스는 프롬프트에서 제외

---

## Module 2: 피드백 루프 강화 (Phase A+B)

### REQ-AI-003: 오류 패턴 분류

**WHEN** 시그널 검증(verify_signals) 시 is_correct가 False로 판정될 때 **THEN** 시스템은 실패 원인을 다음 카테고리 중 하나로 분류해야 한다:
- `macro_shock`: 매크로 이벤트(금리, 환율, 지정학)에 의한 시장 전체 하락
- `supply_reversal`: 외국인/기관 수급 반전
- `earnings_miss`: 실적 미달 또는 어닝쇼크
- `sector_contagion`: 동일 섹터 내 타 종목 이슈 전이
- `technical_breakdown`: 기술적 지지선 이탈

시스템은 **항상** error_category를 fund_signals 테이블에 기록하고, 최근 30일 오류 패턴 분포를 AI 프롬프트에 피드백해야 한다.

수용 기준:
- 검증 실패 시그널에 error_category 컬럼 값이 기록됨
- AI 프롬프트에 "최근 30일 오류 패턴: macro_shock 40%, supply_reversal 25%..." 형태로 주입
- 분류 정확도 수동 검증 시 70% 이상 일치

### REQ-AI-004: 베이지안 신뢰도 보정

**WHILE** 30일 이상의 검증된 시그널 이력이 존재할 때 **THEN** 시스템은 AI가 부여한 confidence 값을 과거 실적 기반으로 보정(calibrate)해야 한다.

**WHEN** AI가 confidence 0.8을 부여했으나 해당 구간의 역사적 적중률이 55%일 때 **THEN** 시스템은 calibrated_confidence를 0.55로 조정하고 fund_signals에 기록해야 한다.

시스템은 **항상** 사용자에게 calibrated_confidence를 원본 confidence와 함께 표시해야 한다.

수용 기준:
- fund_signals 테이블에 calibrated_confidence 컬럼 추가
- 보정 로직이 confidence 구간별(0.1 단위) 역사적 적중률을 기반으로 동작
- API 응답에 confidence와 calibrated_confidence 모두 포함

### REQ-AI-005: 빠른 검증 루프 (6h/12h)

**WHILE** 한국 주식시장 개장 시간(09:00-15:30 KST) 동안 **WHEN** 시그널이 6시간 또는 12시간 경과했을 때 **THEN** 시스템은 조기 검증(early verification)을 수행하여 price_after_6h, price_after_12h를 기록해야 한다.

**WHEN** 6시간 조기 검증에서 손절가(stop_loss) 이탈이 감지될 때 **THEN** 시스템은 해당 시그널에 "early_warning" 플래그를 설정하고 알림을 생성해야 한다.

수용 기준:
- fund_signals에 price_after_6h, price_after_12h 컬럼 추가
- 장중 6h/12h 시점에 자동 가격 조회 및 기록
- stop_loss 이탈 시 early_warning 플래그 설정

---

## Module 3: 다중 팩터 스코어링 엔진 (Phase B)

### REQ-AI-006: 독립 팩터 점수 산출

시스템은 **항상** 각 시그널에 대해 4개의 독립적 팩터 점수를 산출해야 한다:
- `news_sentiment_score` (0-100): 뉴스 감성 분석 기반
- `technical_score` (0-100): SMA, RSI, MACD, Bollinger 기반
- `supply_demand_score` (0-100): 외국인/기관 순매수 기반
- `valuation_score` (0-100): PER, PBR, ROE 업종 비교 기반

**WHILE** 섹터별 팩터 가중치 설정이 존재할 때 **THEN** 시스템은 해당 섹터의 가중치를 적용하여 composite_score를 산출해야 한다.

**가능하면** 각 팩터에 대해 과거 30일 예측력(correlation with 5d return)을 추적하여 가중치 자동 조정 기능을 제공한다.

수용 기준:
- fund_signals.factor_scores (JSONB)에 4개 팩터 점수 저장
- 기본 가중치: 각 0.25 (균등)
- factor_weights 테이블에서 섹터별 가중치 설정 가능
- composite_score = sum(factor * weight) 계산

### REQ-AI-007: 팩터 기여도 추적

**WHEN** 시그널이 생성될 때 **THEN** 시스템은 각 팩터가 최종 판단에 미친 기여도를 기록하고 사용자에게 투명하게 공개해야 한다.

**WHEN** 시그널 검증 후 적중/미적중이 결정될 때 **THEN** 시스템은 어떤 팩터가 정확했고 어떤 팩터가 틀렸는지 분석하여 기록해야 한다.

수용 기준:
- 시그널 상세 API에 factor_contribution 필드 포함
- 검증 후 factor_accuracy_breakdown 기록
- "뉴스 감성 80점이 적중, 기술적 분석 30점이 미적중" 형태 피드백

---

## Module 4: A/B 테스트 및 학습 (Phase B)

### REQ-AI-008: 프롬프트 버전 관리 및 병렬 생성

시스템은 **항상** AI 프롬프트를 버전 관리하고, 각 시그널에 사용된 prompt_version을 기록해야 한다.

**WHEN** A/B 테스트가 활성화되었을 때 **THEN** 시스템은 동일 종목에 대해 2개 프롬프트 버전으로 병렬 시그널을 생성하고, 5일 후 통계적 비교를 수행해야 한다.

**WHEN** A/B 테스트에서 한 버전이 95% 신뢰구간에서 유의미하게 우수할 때 **THEN** 시스템은 해당 버전을 기본 프롬프트로 자동 승격해야 한다.

수용 기준:
- prompt_versions 테이블에 버전별 프롬프트 템플릿 저장
- fund_signals.prompt_version에 사용 버전 기록
- A/B 비교 리포트에 paired t-test 결과 포함
- 자동 승격 시 이전 버전은 archived 상태로 전환

### REQ-AI-009: 뉴스 임팩트 통계 학습

**WHILE** news_price_impact 데이터가 30일 이상 축적되었을 때 **THEN** 시스템은 섹터별/뉴스 유형별 평균 가격 반응을 학습하여 시그널 생성에 활용해야 한다.

**WHEN** 특정 섹터의 뉴스가 역사적으로 평균 +3% 5일 수익률을 보여줄 때 **THEN** 시스템은 해당 섹터 관련 뉴스 발생 시 news_sentiment_score에 가산점을 부여해야 한다.

수용 기준:
- 섹터별 뉴스 임팩트 통계 테이블 또는 캐시 생성
- AI 프롬프트에 "이 섹터 뉴스는 역사적으로 평균 +X% 반응" 주입
- 학습 데이터가 부족한 경우(10건 미만) 기본값 사용

### REQ-AI-010: 매크로 리스크 NLP 분류기

**WHEN** 뉴스 크롤링 시 매크로 관련 뉴스가 감지될 때 **THEN** 시스템은 키워드 매칭 대신 AI 기반 NLP로 리스크 심각도를 분류해야 한다.

시스템은 매크로 리스크를 단순 키워드 빈도가 아닌 **문맥 기반**으로 평가해야 한다.

시스템은 키워드만으로 리스크를 판단하지 **않아야 한다** (거짓 양성 방지).

수용 기준:
- MacroAlert 생성 시 AI 분류 결과(severity, context_summary) 포함
- 키워드 기반 대비 거짓 양성(false positive) 30% 이상 감소
- 문맥 요약이 포함된 매크로 리스크 보고서 생성

---

## Module 5: 고급 예측 (Phase C)

### REQ-AI-011: ML 앙상블 모델

**WHILE** 90일 이상의 팩터 점수 및 시그널 결과 데이터가 축적되었을 때 **THEN** 시스템은 XGBoost 앙상블 모델을 학습하여 AI 시그널과 결합해야 한다.

**WHEN** ML 모델과 AI 시그널이 동시에 "매수"를 출력할 때 **THEN** 시스템은 confidence를 상향 조정하고 "ML+AI 합의" 태그를 부여해야 한다.

**가능하면** ML 모델의 feature importance를 사용자에게 시각화하여 제공한다.

수용 기준:
- XGBoost 모델이 4개 팩터 점수 + AI confidence를 입력으로 사용
- 주간 모델 재학습 파이프라인 동작
- ML 단독 대비 ML+AI 앙상블이 정확도 5% 이상 우수

### REQ-AI-012: 섹터 전파 모델

**WHEN** 특정 종목에 대한 뉴스가 발생할 때 **THEN** 시스템은 동일 섹터 내 다른 종목들에 대한 간접 영향을 추정하고 propagation_score를 산출해야 한다.

**WHILE** 섹터 내 종목 간 상관관계 데이터가 충분할 때(30일 이상 price_history) **THEN** 시스템은 뉴스 전파 강도를 과거 상관계수 기반으로 계산해야 한다.

수용 기준:
- 섹터 내 종목 간 가격 상관 행렬 계산
- 뉴스 발생 시 관련 종목 목록에 propagation_score 부여
- "현대제철 뉴스 -> 대창단조 propagation_score: 0.72" 형태 출력

### REQ-AI-013: 페이퍼 트레이딩 시뮬레이션

시스템은 **항상** 생성된 매수/매도 시그널을 가상 포트폴리오에 자동 반영하여 성과를 추적해야 한다.

**WHEN** 매수 시그널이 생성될 때 **THEN** 시스템은 가상 포트폴리오에 해당 종목을 편입하고, target_price 또는 stop_loss 도달 시 자동 청산해야 한다.

시스템은 **항상** 가상 포트폴리오의 일일 수익률, 누적 수익률, Sharpe ratio, 최대 낙폭(MDD)을 계산하여 기록해야 한다.

**WHEN** 가상 포트폴리오의 Sharpe ratio가 1.0 미만일 때 **THEN** 시스템은 전략 조정이 필요하다는 경고를 생성해야 한다.

수용 기준:
- virtual_portfolios / virtual_trades 테이블 생성
- 시그널 생성 시 자동 가상 매매 기록
- 일일 포트폴리오 성과 계산 및 저장
- KOSPI 벤치마크 대비 초과 수익률 추적
- Sharpe ratio, MDD, 승률 대시보드 API 제공

---

## 추적 태그

- SPEC-AI-001
- REQ-AI-001 ~ REQ-AI-013
- Phase A: REQ-AI-001, REQ-AI-002, REQ-AI-003, REQ-AI-004
- Phase B: REQ-AI-005, REQ-AI-006, REQ-AI-007, REQ-AI-008, REQ-AI-009, REQ-AI-010
- Phase C: REQ-AI-011, REQ-AI-012, REQ-AI-013
