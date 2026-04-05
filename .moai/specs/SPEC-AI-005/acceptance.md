---
id: SPEC-AI-005
type: acceptance
version: 1.0.0
created: 2026-04-05
---

# SPEC-AI-005 수용 기준: 동적 목표가/손절가 계산 시스템

## 1. ATR 계산 (REQ-TPSL-001~003)

### AC-001: ATR 정확성 검증

```gherkin
Given 14일 이상의 주가 데이터(고가, 저가, 종가)가 제공될 때
When calculate_atr(prices, period=14)를 호출하면
Then 반환된 ATR 값이 수동 계산 결과와 소수점 2자리까지 일치해야 한다
```

### AC-002: ATR 기반 동적 TP/SL 계산

```gherkin
Given 종목 코드 "005930"의 ATR이 1,500원이고 entry_price가 70,000원일 때
When calculate_dynamic_tp_sl(stock_code="005930", entry_price=70000, confidence=0.6, sector_id=1)를 호출하면
Then target_price는 73,000원(70,000 + 1,500 * 2.0)이어야 한다
And stop_loss는 67,750원(70,000 - 1,500 * 1.5)이어야 한다
And method는 "atr_fallback"이어야 한다
```

### AC-013: 데이터 부족 시 ATR 미사용

```gherkin
Given 종목의 가격 데이터가 10일치(14일 미만)만 존재할 때
When calculate_dynamic_tp_sl()를 호출하면
Then ATR 계산을 시도하지 않아야 한다
And 섹터 기본값 폴백을 사용해야 한다
And method는 "sector_default"이어야 한다
```

---

## 2. AI 프롬프트 개선 (REQ-TPSL-004~006)

### AC-009: Few-shot 예시 포함 검증

```gherkin
Given fund_manager.py의 AI 종목 분석 프롬프트를 확인할 때
When 프롬프트 내용을 검사하면
Then 최소 2개의 target_price/stop_loss 구체 계산 예시가 포함되어 있어야 한다
And "0이나 null 금지" 또는 동등한 명시적 지시가 포함되어 있어야 한다
```

### AC-010: tp_sl_method 기록 검증

```gherkin
Given AI가 target_price=55000, stop_loss=47500을 반환할 때
When FundSignal이 생성되면
Then fund_signals.tp_sl_method는 "ai_provided"이어야 한다

Given AI가 target_price=0 (또는 null)을 반환할 때
When FundSignal이 생성되면
Then fund_signals.tp_sl_method는 "atr_fallback" 또는 "sector_default"이어야 한다
```

---

## 3. Confidence 기반 조정 (REQ-TPSL-007~008)

### AC-003: 고확신 시그널 배수 조정

```gherkin
Given ATR이 2,000원이고 confidence가 0.85일 때
When 동적 TP/SL을 계산하면
Then 손절 배수는 ATR * 1.0 = 2,000원이어야 한다
And 목표가 배수는 ATR * 2.5 = 5,000원이어야 한다
```

### AC-004: 저확신 시그널 배수 조정

```gherkin
Given ATR이 2,000원이고 confidence가 0.4일 때
When 동적 TP/SL을 계산하면
Then 손절 배수는 ATR * 2.0 = 4,000원이어야 한다
And 목표가 배수는 ATR * 1.5 = 3,000원이어야 한다
```

---

## 4. 섹터별 기본값 (REQ-TPSL-009~011)

### AC-005: 바이오 섹터 기본값

```gherkin
Given ATR 계산이 불가능하고 종목의 섹터가 "바이오/제약"일 때
When 동적 TP/SL을 계산하면
Then target_price는 entry_price * 1.15이어야 한다
And stop_loss는 entry_price * 0.92이어야 한다
```

### AC-006: 금융 섹터 기본값

```gherkin
Given ATR 계산이 불가능하고 종목의 섹터가 "금융/은행"일 때
When 동적 TP/SL을 계산하면
Then target_price는 entry_price * 1.06이어야 한다
And stop_loss는 entry_price * 0.97이어야 한다
```

### 미분류 섹터 하위 호환성

```gherkin
Given ATR 계산이 불가능하고 종목의 섹터가 매핑되지 않은 "기타"일 때
When 동적 TP/SL을 계산하면
Then target_price는 entry_price * 1.10이어야 한다
And stop_loss는 entry_price * 0.95이어야 한다
And 기존 고정 비율과 동일한 결과를 반환해야 한다
```

---

## 5. 트레일링 스톱 (REQ-TPSL-012~014)

### AC-007: 트레일링 스톱 활성화

```gherkin
Given entry_price가 10,000원인 포지션이 있고 현재가가 10,500원(+5%)일 때
When 포지션 체크가 실행되면
Then trailing_stop_active가 True로 설정되어야 한다
And high_water_mark가 10,500원으로 설정되어야 한다
And trailing_stop_price가 high_water_mark - (ATR * 1.5)로 계산되어야 한다
```

### AC-008: 트레일링 손절가 단조 증가

```gherkin
Given trailing_stop_price가 10,200원으로 설정된 포지션이 있을 때
When 현재가가 하락하여 새로 계산된 trailing_stop이 10,100원일 때
Then trailing_stop_price는 10,200원으로 유지되어야 한다 (하향 업데이트 불가)

When 이후 현재가가 상승하여 새로 계산된 trailing_stop이 10,400원일 때
Then trailing_stop_price는 10,400원으로 업데이트되어야 한다
```

### 트레일링 스톱 매도 실행

```gherkin
Given trailing_stop_active가 True이고 trailing_stop_price가 10,200원일 때
When 현재가가 10,100원으로 하락하면
Then 시스템은 해당 포지션을 자동 매도(익절)해야 한다
```

---

## 6. 백테스트 (REQ-TPSL-015~016)

### AC-011: 백테스트 API 응답

```gherkin
Given 기존 페이퍼트레이딩 시그널 데이터가 존재할 때
When GET /api/v1/portfolio/tp-sl-backtest를 호출하면
Then 응답에 다음 필드가 포함되어야 한다:
  - fixed_method: { win_rate, avg_return_pct, max_loss_pct, total_signals }
  - dynamic_method: { win_rate, avg_return_pct, max_loss_pct, total_signals }
  - improvement: { win_rate_diff, avg_return_diff }
```

### 백테스트 경고 플래그

```gherkin
Given 백테스트 결과에서 동적 방식의 win_rate가 고정 방식보다 낮을 때
When 결과를 반환하면
Then needs_review 필드가 true이어야 한다
```

---

## 7. 기존 포지션 보호 (REQ-TPSL-017~018)

### AC-012: AI 설정값 보호

```gherkin
Given tp_sl_method가 "ai_provided"인 활성 포지션이 있을 때
When 기존 포지션 마이그레이션 작업이 실행되면
Then 해당 포지션의 target_price와 stop_loss는 변경되지 않아야 한다
```

### 레거시 포지션 마이그레이션

```gherkin
Given tp_sl_method가 NULL 또는 "legacy_fixed"인 활성 포지션이 있을 때
When 마이그레이션 작업이 실행되면
Then ATR 기반으로 target_price와 stop_loss가 재계산되어야 한다
And tp_sl_method가 "atr_fallback" 또는 "sector_default"로 업데이트되어야 한다
```

---

## 8. 품질 게이트

### AC-014: 테스트 커버리지

```gherkin
Given SPEC-AI-005 구현이 완료되었을 때
When pytest --cov를 실행하면
Then backend/app/services/dynamic_tp_sl.py 커버리지가 85% 이상이어야 한다
And backend/app/services/technical_indicators.py의 calculate_atr 함수 커버리지가 100%이어야 한다
```

### Definition of Done

- [ ] `calculate_atr()` 함수가 단위 테스트를 통과한다
- [ ] `calculate_dynamic_tp_sl()` 함수가 모든 경로(ATR/섹터/confidence)를 처리한다
- [ ] AI 프롬프트에 Few-shot 예시가 포함되었다
- [ ] `tp_sl_method` 필드가 모든 FundSignal에 기록된다
- [ ] 트레일링 스톱이 +5% 도달 시 활성화되고 단조 증가한다
- [ ] 백테스트 API가 고정 vs 동적 비교 결과를 반환한다
- [ ] 기존 ai_provided 포지션이 마이그레이션에서 보호된다
- [ ] Alembic 마이그레이션이 성공적으로 적용된다
- [ ] 테스트 커버리지 85% 이상 달성
