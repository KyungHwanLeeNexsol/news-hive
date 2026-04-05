---
id: SPEC-AI-005
version: 1.0.0
status: Planned
created: 2026-04-05
updated: 2026-04-05
author: MoAI
priority: High
issue_number: 0
title: Dynamic Target Price / Stop Loss Calculation System
tags: [paper-trading, atr, volatility, trailing-stop, backtest, ai-prompt, target-price, stop-loss]
---

# SPEC-AI-005: 동적 목표가/손절가 계산 시스템

## 0. 배경 및 목적

### 문제 정의

현재 NewsHive 페이퍼트레이딩의 목표가/손절가 설정에 심각한 구조적 결함이 있다:

1. **AI가 목표가/손절가를 거의 반환하지 않음**: `fund_manager.py` 라인 1658에서 AI(Gemini)에게 `target_price`와 `stop_loss`를 JSON으로 요청하지만, AI는 빈번하게 `0` 또는 `null`을 반환한다.

2. **고정 비율 폴백의 비효율성**: AI가 값을 반환하지 않으면 `paper_trading.py` 라인 33-34에서 `DEFAULT_TARGET_PCT=0.10`(+10%), `DEFAULT_STOP_LOSS_PCT=0.05`(-5%)의 고정 비율이 적용된다.

3. **실증 데이터**: 21개 페이퍼트레이딩 포지션 중 AI가 목표가를 설정한 종목은 1개(비에이치아이, +13.5%)에 불과하며, 나머지 20개는 모두 +10%/-5% 고정 폴백이 적용되었다.

4. **변동성 무시**: 바이오 종목(일평균 변동성 5~8%)과 은행주(일평균 변동성 1~2%)에 동일한 +10%/-5%를 적용하면, 바이오 종목은 조기 손절되고 은행주는 목표가 도달이 불가능하다.

### 목표

- ATR(Average True Range) 기반 변동성 적응형 목표가/손절가 계산 시스템을 구축한다
- AI 프롬프트를 개선하여 목표가/손절가 반환율을 80% 이상으로 높인다
- 시그널 confidence에 따라 손절 폭을 조정한다
- 섹터별 변동성 프로파일에 맞는 기본값을 제공한다
- 트레일링 스톱으로 수익 보호 메커니즘을 추가한다
- 백테스팅으로 동적 TP/SL의 성능을 기존 고정 방식과 비교 검증한다

---

## 1. 환경 (Environment)

### 1.1 기존 인프라

| 모듈 | 현재 상태 | SPEC-AI-005에서의 역할 |
|------|-----------|----------------------|
| `paper_trading.py` | 고정 +10%/-5% 폴백, `DEFAULT_TARGET_PCT=0.10` | ATR 기반 동적 계산으로 교체 |
| `fund_manager.py` | AI 프롬프트에서 target_price/stop_loss 요청 (라인 1658) | 프롬프트 강화 + Few-shot 예시 추가 |
| `technical_indicators.py` | RSI, MACD, Bollinger Band 계산 완비 | ATR 계산 함수 추가 |
| `naver_finance.py` | 실시간/과거 주가 데이터 조회 | ATR 계산용 과거 가격 데이터 제공 |
| `fund_signals` 모델 | `target_price`, `stop_loss`, `confidence` 필드 존재 | `tp_sl_method` 필드 추가 (산출 방식 추적) |

### 1.2 기존 코드 위치

- `backend/app/services/paper_trading.py` 라인 33-34: `DEFAULT_TARGET_PCT`, `DEFAULT_STOP_LOSS_PCT` 상수
- `backend/app/services/paper_trading.py` 라인 199-200: 시그널 target_price 없을 시 폴백 적용
- `backend/app/services/paper_trading.py` 라인 280-281: 포지션 체크 시 effective_target/stop_loss 폴백
- `backend/app/services/fund_manager.py` 라인 1658-1659: AI 프롬프트 내 target_price/stop_loss 요청문
- `backend/app/services/fund_manager.py` 라인 1687-1688: AI 응답 파싱 시 폴백 `price_at_signal * 1.10`
- `backend/app/services/fund_manager.py` 라인 2129-2130: 브리핑 프롬프트 내 target_price/stop_loss
- `backend/app/services/fund_manager.py` 라인 2168: 프롬프트 규칙 7번 (고정 범위 지시)

### 1.3 기술적 지표 현황

`technical_indicators.py`에 이미 구현된 지표:
- RSI (Relative Strength Index)
- MACD (Moving Average Convergence Divergence)
- Bollinger Bands (상단/하단/밴드폭)
- **ATR은 미구현** -- 본 SPEC에서 추가

---

## 2. 가정 (Assumptions)

- **A1**: `naver_finance.py`에서 최근 20일 이상의 일봉 데이터(고가, 저가, 종가)를 조회할 수 있다
- **A2**: ATR 14일 기준이 한국 주식 시장의 변동성을 합리적으로 반영한다
- **A3**: 섹터별 변동성 프로파일은 `sectors` 테이블의 `id`로 분류 가능하며, 초기에는 5개 카테고리(바이오/IT/금융/제조/기타)로 구분한다
- **A4**: AI(Gemini)는 Few-shot 예시와 명시적 계산 지시를 포함하면 target_price/stop_loss 반환율이 크게 향상된다
- **A5**: 트레일링 스톱은 포지션 체크 주기(현재 스케줄러 기반)에서 실행되며, 실시간 틱 단위 모니터링은 불필요하다
- **A6**: 기존 21개 포지션의 시그널 데이터로 고정 vs 동적 방식의 백테스트 비교가 유의미하다

---

## 3. 요구사항 (Requirements)

### 3.1 ATR 기반 동적 목표가/손절가 계산

> **REQ-TPSL-001 [Event-Driven]**: **WHEN** `FundSignal`이 생성되고 `target_price`가 null 또는 0일 때 **THEN** 시스템은 해당 종목의 14일 ATR을 계산하여 `target_price = entry_price + (ATR * 2.0)`, `stop_loss = entry_price - (ATR * 1.5)`로 설정해야 한다.
> WHY: ATR 2.0배는 통상적인 변동성의 2배이므로 노이즈를 넘는 실질 상승 목표가 되며, ATR 1.5배 손절은 일상적 변동으로 인한 조기 손절을 방지한다.

> **REQ-TPSL-002 [Ubiquitous]**: 시스템은 **항상** `technical_indicators.py`에 `calculate_atr(prices: list[dict], period: int = 14) -> float` 함수를 제공해야 한다.
> WHY: ATR은 목표가/손절가 뿐 아니라 향후 포지션 사이징, 리스크 관리 등에도 재사용된다.

> **REQ-TPSL-003 [Unwanted]**: 시스템은 ATR 계산에 필요한 가격 데이터가 `period + 1`일 미만일 때 ATR 기반 계산을 수행**하지 않아야 한다**. 이 경우 섹터 기본값 폴백을 사용해야 한다.
> WHY: 데이터 부족 시 ATR이 왜곡되어 비현실적인 목표가/손절가가 산출된다.

### 3.2 AI 프롬프트 개선

> **REQ-TPSL-004 [Event-Driven]**: **WHEN** AI에게 종목 분석을 요청할 때 **THEN** 프롬프트에 Few-shot 예시(최소 2개)와 구체적 계산 지시("현재가 X원이면 target_price는 X*1.08=Y원처럼 구체 숫자를 반드시 기입")를 포함해야 한다.
> WHY: AI가 추상적 범위(+5%~+20%)만 보면 구체 숫자 대신 0이나 null을 반환하는 패턴이 관찰되었다.

> **REQ-TPSL-005 [Event-Driven]**: **WHEN** AI가 `target_price`를 0 또는 null로 반환할 때 **THEN** 시스템은 `fund_signals.tp_sl_method = "atr_fallback"`으로 기록하고 ATR 기반 계산을 적용해야 한다.
> WHY: 어떤 방식으로 목표가/손절가가 결정되었는지 추적하여 AI 반환율 개선 모니터링에 활용한다.

> **REQ-TPSL-006 [Event-Driven]**: **WHEN** AI가 유효한 `target_price`와 `stop_loss`를 반환할 때 **THEN** 시스템은 `fund_signals.tp_sl_method = "ai_provided"`로 기록해야 한다.

### 3.3 Confidence 기반 손절 폭 조정

> **REQ-TPSL-007 [State-Driven]**: **IF** 시그널 `confidence >= 0.8` (고확신) **THEN** 손절 배수를 `ATR * 1.0`으로 축소하고, 목표가 배수를 `ATR * 2.5`로 확대해야 한다.
> WHY: 고확신 시그널은 방향성에 대한 확신이 높으므로 타이트한 손절과 넓은 목표가가 Risk-Reward를 극대화한다.

> **REQ-TPSL-008 [State-Driven]**: **IF** 시그널 `confidence < 0.5` (저확신) **THEN** 손절 배수를 `ATR * 2.0`으로 확대하고, 목표가 배수를 `ATR * 1.5`로 축소해야 한다.
> WHY: 저확신 시그널은 넓은 손절로 노이즈 필터링이 필요하고, 보수적 목표가로 조기 익절을 유도한다.

### 3.4 섹터별 기본값

> **REQ-TPSL-009 [State-Driven]**: **IF** ATR 계산이 불가능하고(데이터 부족) 해당 종목의 섹터가 "바이오/제약" **THEN** 목표가 `entry_price * 1.15`, 손절가 `entry_price * 0.92`를 적용해야 한다.
> WHY: 바이오 섹터는 평균 일간 변동성이 5~8%로 높아 넓은 범위가 필요하다.

> **REQ-TPSL-010 [State-Driven]**: **IF** ATR 계산이 불가능하고 해당 종목의 섹터가 "금융/은행" **THEN** 목표가 `entry_price * 1.06`, 손절가 `entry_price * 0.97`를 적용해야 한다.
> WHY: 금융 섹터는 평균 일간 변동성이 1~2%로 낮아 좁은 범위가 적절하다.

> **REQ-TPSL-011 [State-Driven]**: **IF** ATR 계산이 불가능하고 섹터가 위 두 가지에 해당하지 않음 **THEN** 기존 `entry_price * 1.10 / entry_price * 0.95` 기본값을 유지해야 한다.
> WHY: 기존 로직과의 하위 호환성을 보장한다.

### 3.5 트레일링 스톱

> **REQ-TPSL-012 [Event-Driven]**: **WHEN** 포지션의 현재 수익률이 +5% 이상 도달했을 때 **THEN** 시스템은 해당 포지션의 손절가를 `최고가 - (ATR * 1.5)`의 트레일링 스톱으로 전환해야 한다.
> WHY: 수익이 발생한 포지션에서 고정 손절가는 수익 반납 리스크가 크다. 트레일링 스톱은 최고가를 추적하며 수익을 보호한다.

> **REQ-TPSL-013 [State-Driven]**: **IF** 트레일링 스톱이 활성화된 상태에서 현재가가 트레일링 손절가 이하로 하락 **THEN** 시스템은 해당 포지션을 자동 매도(익절)해야 한다.

> **REQ-TPSL-014 [Unwanted]**: 시스템은 트레일링 스톱 활성화 후 트레일링 손절가가 이전 트레일링 손절가보다 낮아지는 방향으로 업데이트**하지 않아야 한다**.
> WHY: 트레일링 스톱은 단조 증가(monotonically increasing)해야 수익 보호 목적이 달성된다.

### 3.6 백테스트 검증

> **REQ-TPSL-015 [Event-Driven]**: **WHEN** `/api/v1/portfolio/tp-sl-backtest` API가 호출될 때 **THEN** 시스템은 기존 시그널 데이터를 기반으로 고정 방식(+10%/-5%) vs 동적 방식(ATR 기반)의 승률, 평균 수익률, 최대 손실률을 비교 반환해야 한다.

> **REQ-TPSL-016 [State-Driven]**: **IF** 백테스트 결과에서 동적 방식의 승률이 고정 방식보다 낮을 **THEN** 시스템은 결과에 경고 플래그(`needs_review: true`)를 포함해야 한다.
> WHY: ATR 파라미터 튜닝이 필요하다는 신호로 활용한다.

### 3.7 기존 포지션 마이그레이션

> **REQ-TPSL-017 [Event-Driven]**: **WHEN** 시스템이 업데이트된 후 기존 포지션의 `target_price`/`stop_loss`가 고정 폴백(+10%/-5%)으로 설정되어 있을 때 **THEN** 스케줄러 작업을 통해 ATR 기반 값으로 재계산하여 업데이트해야 한다.

> **REQ-TPSL-018 [Unwanted]**: 시스템은 AI가 설정한 `target_price`/`stop_loss`(`tp_sl_method="ai_provided"`)를 ATR 기반 값으로 덮어쓰**지 않아야 한다**.
> WHY: AI가 명시적으로 설정한 값은 해당 종목의 맥락을 반영한 판단이므로 존중해야 한다.

---

## 4. 사양 (Specifications)

### 4.1 `technical_indicators.py` ATR 함수 추가

**위치**: `backend/app/services/technical_indicators.py`

| 함수 | 설명 |
|------|------|
| `calculate_atr(prices: list[dict], period: int = 14) -> float` | High/Low/Close 데이터로 ATR 계산. 각 dict는 `{"high": int, "low": int, "close": int}` |

ATR 계산 로직:
1. True Range = max(high - low, abs(high - prev_close), abs(low - prev_close))
2. ATR = SMA(True Range, period) (초기), 이후 EMA 방식

### 4.2 새 서비스: `dynamic_tp_sl.py`

**위치**: `backend/app/services/dynamic_tp_sl.py`

| 함수 | 설명 |
|------|------|
| `calculate_dynamic_tp_sl(stock_code: str, entry_price: int, confidence: float, sector_id: int, db: Session) -> dict` | ATR + confidence + 섹터 기반 동적 TP/SL 계산. 반환: `{"target_price": int, "stop_loss": int, "method": str}` |
| `get_sector_defaults(sector_id: int) -> dict` | 섹터별 기본 목표가/손절가 비율 반환 |
| `calculate_trailing_stop(high_water_mark: int, atr: float) -> int` | 트레일링 손절가 계산 |
| `should_activate_trailing_stop(entry_price: int, current_price: int) -> bool` | +5% 수익률 달성 여부 확인 |

### 4.3 `paper_trading.py` 수정

- `DEFAULT_TARGET_PCT`, `DEFAULT_STOP_LOSS_PCT` 상수를 `dynamic_tp_sl.py` 호출로 대체
- 라인 199-200: `signal.target_price or dynamic_tp_sl.calculate_dynamic_tp_sl(...)` 로 변경
- 라인 280-281: 동일하게 동적 계산 적용
- 포지션 체크 로직에 트레일링 스톱 판정 추가

### 4.4 `fund_manager.py` 프롬프트 수정

- 라인 1658-1659: Few-shot 예시 추가 ("현재가 50,000원 → target_price: 55,000, stop_loss: 47,500")
- 라인 1687-1688: 폴백 시 `dynamic_tp_sl` 호출 + `tp_sl_method` 기록
- 라인 2168: 규칙 7번을 "반드시 구체적인 숫자로 기입. 0이나 null 금지." 로 변경
- 브리핑 프롬프트(라인 2129-2130)에도 동일한 Few-shot 예시 추가

### 4.5 DB 확장

```
ALTER TABLE fund_signals ADD COLUMN tp_sl_method VARCHAR(20) DEFAULT 'legacy_fixed';
-- 값: 'ai_provided', 'atr_fallback', 'sector_default', 'legacy_fixed'

ALTER TABLE virtual_trades ADD COLUMN trailing_stop_active BOOLEAN DEFAULT FALSE;
ALTER TABLE virtual_trades ADD COLUMN trailing_stop_price INT;
ALTER TABLE virtual_trades ADD COLUMN high_water_mark INT;
```

### 4.6 새 API 엔드포인트

**파일**: `backend/app/api/v1/portfolio.py`

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/api/v1/portfolio/tp-sl-backtest` | GET | 고정 vs 동적 TP/SL 백테스트 비교 결과 |
| `/api/v1/portfolio/tp-sl-stats` | GET | TP/SL 방식별(ai_provided, atr_fallback, sector_default) 성과 통계 |

### 4.7 섹터 변동성 프로파일 매핑

| 섹터 카테고리 | 대상 섹터 예시 | 목표가 배수 | 손절가 배수 |
|-------------|---------------|-----------|-----------|
| 고변동성 (바이오/제약) | 바이오, 제약, 게임 | +15% | -8% |
| 중고변동성 (IT/반도체) | IT, 반도체, 2차전지 | +12% | -6% |
| 중변동성 (제조/건설) | 제조, 건설, 화학 | +10% | -5% |
| 저변동성 (금융/유틸리티) | 은행, 보험, 전력 | +6% | -3% |
| 기타 | 미분류 | +10% | -5% |

---

## 5. 수용 기준 (Acceptance Criteria)

| ID | 기준 | 검증 방법 |
|----|------|-----------|
| AC-001 | `calculate_atr()`가 14일 가격 데이터로 올바른 ATR 값을 반환한다 | 단위 테스트 (알려진 ATR 값과 비교) |
| AC-002 | AI가 null 반환 시 `calculate_dynamic_tp_sl()`이 ATR 기반 TP/SL을 계산한다 | 단위 테스트 |
| AC-003 | `confidence >= 0.8`일 때 ATR 배수가 1.0/2.5로 조정된다 | 단위 테스트 |
| AC-004 | `confidence < 0.5`일 때 ATR 배수가 2.0/1.5로 조정된다 | 단위 테스트 |
| AC-005 | 바이오 섹터 종목에 ATR 불가 시 +15%/-8% 기본값이 적용된다 | 단위 테스트 |
| AC-006 | 금융 섹터 종목에 ATR 불가 시 +6%/-3% 기본값이 적용된다 | 단위 테스트 |
| AC-007 | 포지션 수익률 +5% 도달 시 트레일링 스톱이 활성화된다 | 통합 테스트 |
| AC-008 | 트레일링 손절가가 단조 증가만 한다 (하향 업데이트 불가) | 단위 테스트 |
| AC-009 | AI 프롬프트 수정 후 Few-shot 예시가 포함되어 있다 | 코드 리뷰 |
| AC-010 | `fund_signals.tp_sl_method`에 올바른 방식이 기록된다 | 통합 테스트 |
| AC-011 | `/api/v1/portfolio/tp-sl-backtest` API가 고정 vs 동적 비교 결과를 반환한다 | API 테스트 |
| AC-012 | 기존 `tp_sl_method="ai_provided"` 포지션은 재계산으로 덮어쓰지 않는다 | 단위 테스트 |
| AC-013 | 가격 데이터 부족(14일 미만) 시 ATR 계산을 시도하지 않고 섹터 기본값을 사용한다 | 단위 테스트 |
| AC-014 | `test_dynamic_tp_sl.py` 커버리지 >= 85% | pytest --cov |

---

## 6. 구현 우선순위

| 우선순위 | 요구사항 | 예상 구현 복잡도 |
|---------|---------|----------------|
| P1 | REQ-TPSL-001~003 (ATR 계산 + 동적 TP/SL) | 중간 |
| P1 | REQ-TPSL-004~006 (AI 프롬프트 개선 + 방식 추적) | 낮음 |
| P2 | REQ-TPSL-007~008 (Confidence 기반 조정) | 낮음 |
| P2 | REQ-TPSL-009~011 (섹터별 기본값) | 낮음 |
| P3 | REQ-TPSL-012~014 (트레일링 스톱) | 중간 |
| P3 | REQ-TPSL-015~016 (백테스트 검증) | 중간 |
| P3 | REQ-TPSL-017~018 (기존 포지션 마이그레이션) | 낮음 |

---

## 7. 기술 제약

- Python 3.13+, FastAPI, SQLAlchemy 2.0, APScheduler
- `naver_finance.py`의 과거 가격 조회가 최소 20일 데이터를 반환할 수 있어야 ATR 계산 가능
- OCI VM.Standard.E2.1.Micro (1 OCPU, 1GB RAM): ATR 계산은 경량 연산이므로 리소스 영향 미미
- Gemini AI 프롬프트 토큰 한도 내에서 Few-shot 예시 추가 (예시 2개 추가 시 약 200토큰 증가)
- Alembic 마이그레이션으로 `fund_signals`, `virtual_trades` 테이블 확장

---

## 8. 제외 사항 (Exclusions - What NOT to Build)

- Shall NOT implement 실시간 틱 단위 트레일링 스톱 모니터링 (reason: 기존 스케줄러 주기 체크로 충분하며 OCI VM 리소스 한계)
- Shall NOT implement 포지션 사이징 (ATR 기반 투자금 배분) (reason: 별도 SPEC으로 분리, 본 SPEC의 범위를 넘음)
- Shall NOT implement AI 모델 자체의 Fine-tuning (reason: 프롬프트 엔지니어링으로 해결, Fine-tuning은 비용 대비 효과 불명확)
- Will NOT be optimized for 선물/옵션 거래 (reason: 현재 시스템은 현물 주식만 대상)
- Shall NOT implement 사용자별 커스텀 TP/SL 설정 UI (reason: 현재 단일 사용자 시스템이며, 알고리즘 기반 자동화가 목적)

---

## 9. 관련 SPEC

- **SPEC-AI-003**: 기술적 선행 지표 탐지 -- `technical_indicators.py`에 ATR 함수를 추가하는 것은 이 모듈의 자연스러운 확장
- **SPEC-AI-004**: 공시 기반 미반영 호재 탐지 -- 공시 기반 시그널(`disclosure_impact`)에도 동적 TP/SL 적용 대상
