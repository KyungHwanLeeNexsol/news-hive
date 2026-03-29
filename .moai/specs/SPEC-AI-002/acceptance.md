---
id: SPEC-AI-002
type: acceptance
version: "1.0.0"
created: "2026-03-29"
updated: "2026-03-29"
---

# SPEC-AI-002 수용 기준: AI 펀드 예측력 2단계 고도화

## Module 1: 다중 시간축 분석

### AC-014-1: 추세 정렬 계산

```gherkin
Given 종목 A의 5일/20일/60일 이동평균이 모두 상승 기울기
When factor_scoring.compute_technical_score()가 호출되면
Then trend_alignment = "aligned"가 반환된다
And technical score에 +15점이 가산된다
```

### AC-014-2: 추세 역행 감지

```gherkin
Given 종목 B의 5일 이동평균은 상승이나 60일 이동평균은 하락
When 시그널이 생성되면
Then trend_alignment = "divergent"가 기록된다
And confidence가 0.1 감산된다
And fund_signals.trend_alignment 컬럼에 "divergent" 저장
```

### AC-014-3: 브리핑 통합

```gherkin
Given 추세 정렬 분석이 완료된 시그널 목록
When 일간 브리핑이 생성되면
Then AI 프롬프트에 각 종목의 추세 정렬 상태가 포함된다
```

### AC-015-1: 거래량 이상 탐지

```gherkin
Given 종목 C의 당일 거래량이 20일 평균의 2.5배
When factor_scoring이 실행되면
Then volume_spike = true가 fund_signals metadata에 기록된다
And 가격이 상승 중이면 supply_demand score에 +10점 가산
```

### AC-020-1: 고변동성 포지션 조정

```gherkin
Given KOSPI 20일 표준편차가 2.5% (high 레벨)
When 시그널이 생성되면
Then suggested_weight가 기본값의 70%로 조정된다
And volatility_level = "high"가 fund_signals에 기록된다
```

### AC-020-2: 극단 변동성 경고

```gherkin
Given KOSPI 20일 표준편차가 3.5% (extreme 레벨)
When 매수 시그널이 생성되면
Then confidence가 0.15 감산된다
And "high_volatility_warning" 태그가 부여된다
And 브리핑 상단에 변동성 레벨이 표시된다
```

---

## Module 2: 섹터 분석

### AC-016-1: 모멘텀 섹터 감지

```gherkin
Given 철강 섹터의 5일 평균 등락률이 시장 대비 +3%p
When 섹터 모멘텀 분석이 실행되면
Then 철강 섹터에 "momentum_sector" 태그가 부여된다
And sector_momentum 테이블에 레코드가 생성된다
```

### AC-016-2: 자금 유입 알림

```gherkin
Given 반도체 섹터가 3일 연속 거래대금 증가 + 양의 수익률
When 일간 분석이 실행되면
Then "capital_inflow" 알림이 생성된다
And 브리핑에 "섹터 모멘텀 분석" 섹션이 포함된다
```

### AC-017-1: 섹터 로테이션 감지

```gherkin
Given 이전 모멘텀 섹터(철강)의 5일 수익률이 음수로 전환
And 새로운 섹터(반도체)가 모멘텀 섹터로 부상
When 로테이션 분석이 실행되면
Then sector_rotation_events에 (from: 철강, to: 반도체) 레코드 생성
And 철강 섹터 매수 시그널의 confidence가 0.15 감산
```

### AC-019-1: 섹터 시그널 중복 제거

```gherkin
Given 철강 섹터에서 3개 매수 시그널 (A: 85점, B: 78점, C: 72점)
When 최종 추천 목록이 생성되면
Then A와 B만 최종 추천에 포함된다
And C는 "섹터 중복 제거"로 제외 로그 기록
And 브리핑에 "철강 섹터: 3개 시그널 중 상위 2개 선정" 메시지 포함
```

---

## Module 3: 어닝 서프라이즈

### AC-018-1: 어닝 프리뷰 생성

```gherkin
Given 종목 D의 실적 공시가 D-5 이내로 예정
When 시그널 생성이 실행되면
Then earnings_preview 분석이 생성된다
And fund_signals metadata에 earnings_preview 결과 포함
```

### AC-018-2: 긍정적 서프라이즈 가산

```gherkin
Given 어닝 프리뷰에서 긍정적 서프라이즈 확률 65%
When 해당 종목의 매수 시그널이 생성되면
Then confidence에 +0.1이 가산된다
And AI 프롬프트에 "실적 시즌 분석" 섹션이 포함된다
```

### AC-018-3: 실적 후 정확도 추적

```gherkin
Given 어닝 프리뷰가 "긍정적 서프라이즈" 예측
When 실제 실적 공시가 발표되면
Then 예측 vs 실제 비교 결과가 로그에 기록된다
```

---

## Module 4: 시그널 상관관계

### AC-019-2: 우선순위 기준 적용

```gherkin
Given 같은 섹터에 3개 시그널:
  - A: composite=85, aligned, volume_spike
  - B: composite=82, divergent, no spike
  - C: composite=88, aligned, no spike
When 섹터 중복 제거가 실행되면
Then C(88점, aligned)와 A(85점, aligned+spike)가 선택된다
And B는 divergent이므로 제외
```

---

## Module 5: 리스크 관리

### AC-021-1: 방어 모드 진입

```gherkin
Given 페이퍼 트레이딩 포트폴리오 누적 손실이 -12%
When 시그널 생성이 트리거되면
Then 시스템이 "defensive_mode"로 전환된다
And 신규 매수 시그널이 생성되지 않는다
And 브리핑에 "방어 모드 활성화" 경고 표시
```

### AC-021-2: 방어 모드 해제

```gherkin
Given 방어 모드가 활성화된 상태
And 포트폴리오 수익률이 -4%로 회복
When 다음 브리핑 생성 시
Then 방어 모드가 해제된다
And 정상 시그널 생성이 재개된다
```

### AC-021-3: 손절 기준 강화

```gherkin
Given 방어 모드가 활성화된 상태
When 기존 포지션의 손실이 -3%에 도달하면
Then 해당 포지션에 대해 손절 알림이 생성된다
(정상 모드에서는 -5%에서 손절)
```

---

## Module 6: 유사 패턴 매칭

### AC-022-1: 유사 시장 상황 검색

```gherkin
Given 현재 KOSPI 5일 수익률 -1.5%, 변동성 normal, 모멘텀 섹터: 반도체
And 과거 60일 내 유사 조건(수익률 차이 1%p 이내, 같은 변동성) 시점 존재
When 유사 패턴 매칭이 실행되면
Then 유사 시점의 시그널 적중률이 계산된다
And AI 프롬프트에 참조 정보로 포함
```

---

## Module 7: CoT 프롬프트

### AC-023-1: 5단계 구조 검증

```gherkin
Given CoT 프롬프트로 AI 분석을 요청
When AI가 STEP 1~5를 모두 포함한 응답을 반환하면
Then 시그널이 정상 생성된다
```

### AC-023-2: STEP 누락 감지

```gherkin
Given CoT 프롬프트로 AI 분석을 요청
When AI 응답에서 STEP 3이 누락되면
Then confidence가 0.1 감산된다
And "incomplete_analysis" 태그가 시그널에 부여
```

### AC-023-3: A/B 테스트 등록

```gherkin
Given prompt_versioner.py에 CoT 프롬프트가 등록
When 시그널 생성이 실행되면
Then 50%는 CoT 프롬프트, 50%는 기존 프롬프트로 분석
And 각 버전의 적중률이 추적된다
```

---

## Module 8: 원자재 크로스 검증

### AC-024-1: 원자재 역행 경고

```gherkin
Given 철강 종목에 대한 매수 시그널
And 철광석 가격이 5일 연속 하락
When 원자재 크로스 검증이 실행되면
Then "commodity_divergence" 경고가 시그널에 포함
And confidence가 0.1 감산된다
```

---

## Module 9: ML 피처

### AC-025-1: 일별 피처 저장

```gherkin
Given 일간 브리핑이 완료된 상태
When ML 피처 엔지니어링이 실행되면
Then ml_features 테이블에 당일 피처 스냅샷이 저장된다
And 4-factor 점수, 추세 정렬, 변동성 레벨 등 포함
```

### AC-025-2: 데이터 축적 알림

```gherkin
Given ml_features 테이블에 90일 이상 데이터 축적
When 피처 엔지니어링 job이 실행되면
Then "ML 앙상블 학습 가능" 알림이 로그에 기록된다
```

---

## Quality Gates

### 성능 기준
- 시그널 생성 파이프라인 전체 소요 시간: 기존 대비 +30초 이내 (AI 호출 제외)
- 섹터 모멘텀 계산: 전체 섹터 5초 이내
- 유사 패턴 매칭: 60일 이력 검색 2초 이내

### 정확도 기준 (30일 후 측정)
- 추세 정렬 시그널 적중률: 비정렬 대비 +10%p 이상
- CoT 프롬프트 시그널: 기존 대비 분석 근거 수 2배 이상
- 방어 모드: 고변동성 구간 최대 손실 30% 감소

### Definition of Done
- [ ] 모든 REQ에 대응하는 수용 기준 테스트 시나리오 통과
- [ ] fund_signals 테이블 마이그레이션 완료 및 하위 호환
- [ ] 신규 모듈(market_context, sector_momentum, earnings_analyzer) 독립 테스트
- [ ] fund_manager.py 기존 시그널 생성 로직 regression 없음
- [ ] 페이퍼 트레이딩으로 최소 7일 정상 운영 확인
- [ ] 각 모듈의 graceful degradation 검증 (데이터 부족 시 fallback)
