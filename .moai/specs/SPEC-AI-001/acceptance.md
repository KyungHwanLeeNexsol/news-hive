---
spec_id: SPEC-AI-001
type: acceptance-criteria
---

# SPEC-AI-001 수용 기준: AI 펀드 예측 시스템 고도화

---

## AC-01: 매수 후보 필터링 완화 (REQ-AI-001)

### Scenario 1: 등락률 -2% 종목의 후보 포함

```gherkin
Given 종목 "대창단조"의 당일 change_rate가 -2.0%이고
  And 5일 추세(price_5d_trend)가 +1.5%이고
  And 외국인 순매수(foreign_net_5d)가 50,000주이고
  And PER이 업종 평균 이하일 때
When generate_daily_briefing()이 실행되면
Then "대창단조"가 매수 후보 목록(candidate_data)에 포함되어야 한다
  And 후보 데이터에 "condition_met: 4/4" 태그가 포함되어야 한다
```

### Scenario 2: 3-of-4 조건 충족 종목

```gherkin
Given 종목 "진성이엔씨"의 change_rate가 -1.5%이고
  And price_5d_trend가 +2.0%이고
  And foreign_net_5d가 -10,000주 (수급 미충족)이고
  And PER이 업종 평균 이하일 때
When generate_daily_briefing()이 실행되면
Then "진성이엔씨"가 "조건부 매수 후보"로 포함되어야 한다
  And 후보 데이터에 "condition_met: 3/4, failed: supply_demand" 태그가 포함되어야 한다
```

### Scenario 3: -3% 초과 급락 종목 제외

```gherkin
Given 종목 "ABC주식"의 change_rate가 -4.5%일 때
When generate_daily_briefing()이 실행되면
Then "ABC주식"은 매수 후보 목록에서 제외되어야 한다
  And 해당 종목에 "급락 회피" 태그가 부여되어야 한다
```

---

## AC-02: 시간 가중 뉴스 스코어링 (REQ-AI-002)

### Scenario 4: 뉴스 시간 가중치 적용

```gherkin
Given 다음 뉴스 3건이 수집되었을 때:
  | 제목                    | 발행 시간      |
  | "현대제철 사업부 매각"    | 6시간 전       |
  | "철강 업종 실적 개선"     | 30시간 전      |
  | "원자재 가격 하락 전망"   | 60시간 전      |
When AI 프롬프트가 생성되면
Then 뉴스 목록이 가중치 순으로 정렬되어야 한다:
  | 제목                    | 가중치 |
  | "현대제철 사업부 매각"    | 1.0   |
  | "철강 업종 실적 개선"     | 0.7   |
  | "원자재 가격 하락 전망"   | 0.4   |
  And 각 뉴스 항목 앞에 "[가중치: X.X]" 표시가 포함되어야 한다
```

### Scenario 5: 72시간 초과 뉴스 제외

```gherkin
Given 뉴스 발행 시간이 80시간 전일 때
When _gather_stock_news()가 실행되면
Then 해당 뉴스는 프롬프트에 포함되지 않아야 한다
```

---

## AC-03: 오류 패턴 분류 (REQ-AI-003)

### Scenario 6: 매크로 쇼크 패턴 분류

```gherkin
Given "매수" 시그널이 발행되었고
  And 5일 후 price_after_5d가 price_at_signal보다 낮아 is_correct가 False이고
  And 해당 기간 중 KOSPI가 -3% 이상 하락했을 때
When verify_signals()가 실행되면
Then fund_signals.error_category가 "macro_shock"으로 기록되어야 한다
```

### Scenario 7: 수급 반전 패턴 분류

```gherkin
Given "매수" 시그널이 발행되었고
  And 시그널 당시 foreign_net_5d가 양수였으나
  And 5일 후 외국인 순매도로 전환되었고
  And is_correct가 False일 때
When verify_signals()가 실행되면
Then fund_signals.error_category가 "supply_reversal"로 기록되어야 한다
```

### Scenario 8: 오류 패턴 프롬프트 피드백

```gherkin
Given 최근 30일간 검증된 시그널 50건 중:
  | error_category      | 건수 |
  | macro_shock         | 20   |
  | supply_reversal     | 10   |
  | earnings_miss       | 5    |
  | sector_contagion    | 3    |
  | technical_breakdown | 2    |
When generate_daily_briefing() 프롬프트가 생성되면
Then "최근 30일 예측 실패 패턴: macro_shock 50%, supply_reversal 25%, ..." 형태의 피드백이 프롬프트에 포함되어야 한다
```

---

## AC-04: 베이지안 신뢰도 보정 (REQ-AI-004)

### Scenario 9: 과신(overconfidence) 보정

```gherkin
Given AI가 confidence 0.85를 부여했고
  And 과거 90일간 confidence 0.8-0.9 구간의 역사적 적중률이 58%이고
  And 해당 구간 샘플 수가 20건 이상일 때
When analyze_stock()이 완료되면
Then fund_signals.calibrated_confidence가 0.58로 기록되어야 한다
  And API 응답에 confidence: 0.85와 calibrated_confidence: 0.58이 모두 포함되어야 한다
```

### Scenario 10: 데이터 부족 시 보정 생략

```gherkin
Given AI가 confidence 0.75를 부여했고
  And 과거 90일간 confidence 0.7-0.8 구간의 샘플 수가 5건 미만일 때
When analyze_stock()이 완료되면
Then fund_signals.calibrated_confidence가 원본 0.75와 동일하게 기록되어야 한다
```

---

## AC-05: 빠른 검증 루프 (REQ-AI-005)

### Scenario 11: 장중 6시간 조기 검증

```gherkin
Given "매수" 시그널이 오전 09:30에 생성되었고
  And 현재 시각이 15:30 (6시간 경과)이고
  And 한국 주식시장이 개장 중일 때
When fast_verify()가 실행되면
Then fund_signals.price_after_6h에 현재 주가가 기록되어야 한다
```

### Scenario 12: stop_loss 이탈 조기 경고

```gherkin
Given "매수" 시그널의 stop_loss가 45,000원이고
  And price_at_signal이 50,000원이고
  And 6시간 후 현재가가 44,000원일 때
When fast_verify()가 실행되면
Then fund_signals.price_after_6h에 44,000이 기록되고
  And 해당 시그널에 "early_warning" 플래그가 설정되어야 한다
```

---

## AC-06: 다중 팩터 스코어링 (REQ-AI-006, REQ-AI-007)

### Scenario 13: 독립 팩터 점수 산출

```gherkin
Given 종목 "삼성전자"에 대해:
  | 데이터           | 값        |
  | 뉴스 감성        | 긍정 70%  |
  | RSI             | 45        |
  | 외국인 순매수 5일  | +200만주  |
  | PER/업종PER 비율  | 0.8       |
When analyze_stock()이 실행되면
Then fund_signals.factor_scores에 다음이 기록되어야 한다:
  | 팩터                  | 범위     |
  | news_sentiment_score  | 60-80   |
  | technical_score       | 40-60   |
  | supply_demand_score   | 70-90   |
  | valuation_score       | 60-80   |
  And composite_score가 4개 팩터의 가중 평균으로 계산되어야 한다
```

### Scenario 14: 팩터 기여도 추적

```gherkin
Given 시그널이 생성되어 factor_scores가 기록되었고
  And 5일 후 is_correct가 True로 검증되었을 때
When 시그널 상세 API를 조회하면
Then factor_contribution 필드에 각 팩터의 기여도가 포함되어야 한다
  And "news_sentiment가 적중 (예측 75, 실제 상승)" 형태의 분석이 포함되어야 한다
```

---

## AC-07: A/B 테스트 프레임워크 (REQ-AI-008)

### Scenario 15: 프롬프트 A/B 비교

```gherkin
Given prompt_version "v1.0" (기존)과 "v1.1" (개선)이 등록되었고
  And A/B 테스트가 활성화되었을 때
When 종목 "현대제철"에 대해 analyze_stock()이 실행되면
Then 2개의 시그널이 생성되어야 한다:
  | prompt_version | signal | confidence |
  | v1.0          | buy    | 0.72       |
  | v1.1          | buy    | 0.68       |
  And 각 시그널의 prompt_version이 fund_signals에 기록되어야 한다
```

### Scenario 16: A/B 테스트 자동 승격

```gherkin
Given A/B 테스트가 30회 이상 실행되었고
  And "v1.1"의 5일 적중률이 68%이고
  And "v1.0"의 5일 적중률이 55%이고
  And paired t-test p-value가 0.03일 때
When evaluate_ab_test()가 실행되면
Then "v1.1"이 기본 프롬프트로 자동 승격되어야 한다
  And "v1.0"은 "archived" 상태로 전환되어야 한다
  And prompt_ab_results에 winner: "v1.1", p_value: 0.03이 기록되어야 한다
```

---

## AC-08: 매크로 NLP 분류 (REQ-AI-010)

### Scenario 17: 문맥 기반 리스크 분류

```gherkin
Given 뉴스 제목 "미 연준 금리 동결, 시장 안도"가 수집되었고
  And 키워드 "금리"가 매크로 키워드에 해당할 때
When NLP 분류기가 실행되면
Then MacroAlert.ai_severity가 "low"로 분류되어야 한다 (금리 동결은 부정적 이벤트가 아님)
  And context_summary에 "연준 금리 동결로 시장 불확실성 해소" 형태 요약이 포함되어야 한다
```

### Scenario 18: 키워드 기반 거짓 양성 감소

```gherkin
Given 키워드 "금리" 매칭으로 warning 알림이 생성되었으나
  And 뉴스 내용이 "주택담보대출 금리 인하 혜택 확대"인 경우
When NLP 분류기가 2차 검증을 수행하면
Then MacroAlert.ai_severity가 "none"으로 재분류되어야 한다
  And 해당 알림은 비활성화(is_active=False)되어야 한다
```

---

## AC-09: 페이퍼 트레이딩 (REQ-AI-013)

### Scenario 19: 시그널 기반 자동 가상 매매

```gherkin
Given virtual_portfolio가 초기 자본 100,000,000원으로 생성되었고
  And "매수" 시그널이 종목 "삼성전자" 가격 70,000원으로 생성되었을 때
When paper_trading 서비스가 시그널을 처리하면
Then virtual_trades에 다음이 기록되어야 한다:
  | action | stock    | price  | shares |
  | buy    | 삼성전자  | 70,000 | 계산됨  |
  And 포트폴리오의 current_value가 업데이트되어야 한다
```

### Scenario 20: 성과 지표 계산

```gherkin
Given 가상 포트폴리오가 30일간 운영되었고
  And 총 15건의 매매가 기록되었을 때
When GET /api/fund/paper-trading/performance를 호출하면
Then 응답에 다음 지표가 포함되어야 한다:
  | 지표             | 형식     |
  | total_return     | 백분율   |
  | daily_returns    | 배열     |
  | sharpe_ratio     | 소수점   |
  | max_drawdown     | 백분율   |
  | win_rate         | 백분율   |
  | vs_kospi         | 백분율   |
  And sharpe_ratio가 1.0 미만이면 "전략 조정 필요" 경고가 포함되어야 한다
```

---

## Quality Gate

| 항목 | 기준 |
|------|------|
| Phase A 완료 조건 | AC-01 ~ AC-04 전체 통과 |
| Phase B 완료 조건 | AC-05 ~ AC-08 전체 통과 |
| Phase C 완료 조건 | AC-09 전체 통과 + Sharpe ratio > 1.0 |
| 테스트 커버리지 | 신규 모듈 85% 이상 |
| 기존 기능 호환 | 기존 fund_manager API 응답 형식 유지 (하위 호환) |
| DB 마이그레이션 | Alembic upgrade/downgrade 양방향 동작 |

---

## 추적 태그

- SPEC-AI-001
- REQ-AI-001 -> AC-01 (Scenario 1, 2, 3)
- REQ-AI-002 -> AC-02 (Scenario 4, 5)
- REQ-AI-003 -> AC-03 (Scenario 6, 7, 8)
- REQ-AI-004 -> AC-04 (Scenario 9, 10)
- REQ-AI-005 -> AC-05 (Scenario 11, 12)
- REQ-AI-006, REQ-AI-007 -> AC-06 (Scenario 13, 14)
- REQ-AI-008 -> AC-07 (Scenario 15, 16)
- REQ-AI-010 -> AC-08 (Scenario 17, 18)
- REQ-AI-013 -> AC-09 (Scenario 19, 20)
