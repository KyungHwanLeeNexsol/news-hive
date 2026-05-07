---
id: SPEC-AI-013
version: 1.0.0
status: Implemented
created: 2026-05-07
updated: 2026-05-07
author: MoAI
priority: High
issue_number: 0
title: Surge Prediction Paper Trading Portfolio (급등예측 모의투자 포트폴리오)
tags: [surge-trading, paper-trading, portfolio, surge-candidate, auto-execution]
dependencies: [SPEC-AI-012, SPEC-KS200-001]
---

# SPEC-AI-013: 급등예측 모의투자 포트폴리오

## HISTORY

- 2026-05-07 (v1.0.0): 초기 SPEC 작성 — SPEC-AI-012 급등예측 시그널 기반 4번째 모의투자 포트폴리오 추가

---

## 0. 배경 및 목적 (Background)

### 0.1 배경

현재 NewsHive는 3개의 독립적인 모의투자 포트폴리오 모델을 운영 중이다:

1. **AI Fund (Paper)**: AI 펀드매니저 기반, `virtual_portfolios` / `virtual_trades` 테이블, `paper_trading.py` 서비스
2. **VIP Follow**: 기관/외국인 매수 추종, `vip_portfolios` / `vip_trades` 테이블, `vip_follow_trading.py` 서비스
3. **KS200**: 코스피200 종목 풀 기반, `ks200_portfolios` / `ks200_trades` 테이블, `ks200_trading_service.py` 서비스

SPEC-AI-012에서 **급등예측 시스템**이 도입되어 `FundSignal(signal_type="surge_candidate")` 레코드가 자동 생성되고 있으나, 해당 시그널을 추적하는 독립 모의투자 모델이 없어 시그널 정확도와 수익성 검증이 어려운 상황이다.

### 0.2 목적

- **4번째 모의투자 포트폴리오** 추가: 급등예측(Surge Prediction) 모델 신설
- **신호 소스**: SPEC-AI-012가 생성한 `FundSignal(signal_type="surge_candidate")` 레코드
- **자동 실행**: 룰 기반(rule-based) 자동 매매, 한국 정규장(09:00~15:30 KST)에만 진입
- **독립성**: 기존 3개 모델과 자본·포지션·종료조건 완전 분리
- **검증 목적**: 급등예측 시그널의 실전 적용 시 수익성·정확도 측정

### 0.3 비즈니스 가치

- 급등예측 시그널의 객관적 성과 측정
- 사용자에게 급등 추종 전략 시각화 제공
- 다중 전략 비교(VIP/KS200/AI Fund/Surge) 기반 인사이트

---

## 1. 환경 (Environment)

### 1.1 기존 모델·테이블 (참조 대상)

| 모델 | 테이블 | 서비스 | 라우터 |
|---|---|---|---|
| AI Fund (Paper) | `virtual_portfolios`, `virtual_trades` | `paper_trading.py` | `/paper/*` |
| VIP Follow | `vip_portfolios`, `vip_trades` | `vip_follow_trading.py` | `/vip/*` |
| KS200 | `ks200_portfolios`, `ks200_trades`, `ks200_signals` | `ks200_trading_service.py` | `/ks200/*` |
| **Surge (신규)** | `surge_portfolios`, `surge_trades` | `surge_trading_service.py` | `/surge/*` |

### 1.2 시그널 소스 (SPEC-AI-012)

`FundSignal` 테이블 (기존 모델, 변경 없음):

```python
class FundSignal(Base):
    __tablename__ = "fund_signals"
    id: int (PK)
    stock_code: str            # 종목 코드 (예: "005930")
    stock_name: str            # 종목명 (예: "삼성전자")
    signal_type: str           # "surge_candidate" | "buy" | "sell" 등
    surge_metadata: str (JSON) # {"surge_basis": "...", "surge_probability_score": 0.75}
    paper_executed: bool       # AI Fund 전용 (Surge에서는 사용 안 함)
    created_at: datetime
```

**중요**: SPEC-AI-013은 `FundSignal.paper_executed` 필드를 **수정·재사용하지 않는다**. 대신 `SurgeTrade` 조회로 중복 진입을 차단한다(Option B, Section 4.5).

### 1.3 가격 조회 (기존 함수)

- `app.services.naver_finance.fetch_current_price(stock_code: str) -> Optional[Decimal]`
- `app.services.naver_finance.fetch_current_price_with_change(stock_code: str) -> Optional[Tuple[Decimal, Decimal]]`

### 1.4 스케줄러 (기존)

`app/scheduler.py`에 APScheduler 기반 잡 등록 패턴 존재. 신규 잡 2종 추가 필요:

- `surge_execute_buys` (매수 실행, 정규장 동안 주기적)
- `surge_check_exits` (종료 조건 체크, 정규장 동안 주기적)

### 1.5 정규장 시간 정의

- 한국 표준시(KST, UTC+9)
- 정규장: **평일 09:00~15:30**
- 매수/매도 주문은 정규장 시간 외에는 실행되지 않음 (큐잉 X, 단순 스킵)

### 1.6 프론트엔드 (기존)

- `frontend/src/app/trading/page.tsx`: 현재 `Tab = 'vip' | 'ks200' | 'paper' | 'compare'`
- API 클라이언트: `frontend/src/lib/api.ts` 또는 도메인별 분리 파일

---

## 2. 요구사항 (Requirements) — EARS 형식

### 2.1 데이터 모델 요구사항

**REQ-SURGE-TRADE-001 (Ubiquitous)**: 시스템은 단일 인스턴스의 `SurgePortfolio` 레코드를 유지해야 한다(`id=1`, `initial_capital=5_000_000` KRW).

**REQ-SURGE-TRADE-002 (Ubiquitous)**: 시스템은 모든 매수·매도 거래를 `SurgeTrade` 테이블에 기록해야 한다.

**REQ-SURGE-TRADE-003 (Ubiquitous)**: `SurgeTrade` 레코드는 진입가(`entry_price`), 수량(`quantity`), 진입일(`entry_date`), 종료일(`exit_date` nullable), 종료가(`exit_price` nullable), 보유 여부(`is_open`), 종료 사유(`exit_reason` nullable)를 포함해야 한다.

**REQ-SURGE-TRADE-004 (Ubiquitous)**: 시스템은 `surge_portfolios`, `surge_trades` 테이블을 다른 모의투자 모델 테이블(`virtual_*`, `vip_*`, `ks200_*`)과 완전히 분리하여 운영해야 한다.

### 2.2 시그널 선택 요구사항

**REQ-SURGE-TRADE-010 (Event-Driven)**: When `surge_execute_buys` 잡이 실행될 때, the 시스템은 `FundSignal.signal_type == "surge_candidate"` AND `created_at::date == today (KST)` 조건을 만족하는 시그널만 조회해야 한다.

**REQ-SURGE-TRADE-011 (State-Driven)**: While 시그널의 `surge_metadata.surge_probability_score < 0.6`인 동안, 시스템은 해당 시그널을 매수 후보에서 제외해야 한다(임계값은 설정 가능, 기본 0.6).

**REQ-SURGE-TRADE-012 (State-Driven)**: While 동일 종목(`stock_code`)에 대해 `SurgeTrade.is_open == True`인 포지션이 존재하는 동안, 시스템은 해당 종목의 신규 시그널을 무시해야 한다(중복 진입 차단).

**REQ-SURGE-TRADE-013 (Ubiquitous)**: 시스템은 하루(KST 기준) 최대 N개(기본 5개)의 신규 매수 포지션만 진입해야 한다(설정 가능).

**REQ-SURGE-TRADE-014 (Optional)**: Where 동일 종목에 대해 이미 같은 날(`entry_date == today`) 매수가 이루어진 경우, 시스템은 해당 종목 재진입을 시도하지 않아야 한다.

### 2.3 매수 실행 요구사항

**REQ-SURGE-TRADE-020 (State-Driven)**: While 현재 시각이 KST 평일 09:00~15:30 범위 내인 동안에만, 시스템은 매수 주문을 실행해야 한다.

**REQ-SURGE-TRADE-021 (State-Driven)**: While 정규장 시간이 아닌 동안, 시스템은 매수 시도를 단순 스킵해야 한다(큐잉하지 않음).

**REQ-SURGE-TRADE-022 (Ubiquitous)**: 시스템은 1포지션당 `initial_capital * position_pct`(기본 0.20, 즉 100만원)를 투자해야 한다.

**REQ-SURGE-TRADE-023 (Unwanted)**: If 현재 가용 현금(`current_cash`)이 1포지션 투자금액보다 부족하면, then 시스템은 해당 시그널 매수를 실행하지 않아야 한다.

**REQ-SURGE-TRADE-024 (Ubiquitous)**: 시스템은 매수 시 `naver_finance.fetch_current_price(stock_code)`로 현재가를 조회하고, `quantity = floor(투자금액 / 현재가)`로 수량을 계산해야 한다.

**REQ-SURGE-TRADE-025 (Unwanted)**: If 현재가 조회가 실패하면(None 반환), then 시스템은 해당 시그널 매수를 실행하지 않고 다음 시그널로 넘어가야 한다.

**REQ-SURGE-TRADE-026 (Ubiquitous)**: 매수 성공 시 시스템은 `SurgePortfolio.current_cash`를 차감하고 `SurgeTrade(is_open=True, entry_price=..., entry_date=today, quantity=...)`를 생성해야 한다.

### 2.4 종료 조건 요구사항

**REQ-SURGE-TRADE-030 (Event-Driven)**: When `surge_check_exits` 잡이 정규장 시간에 실행될 때, the 시스템은 모든 `SurgeTrade.is_open == True` 포지션에 대해 종료 조건을 체크해야 한다.

**REQ-SURGE-TRADE-031 (State-Driven)**: While 포지션의 `(current_price - entry_price) / entry_price <= -0.08` 조건이 만족되는 동안, 시스템은 해당 포지션을 즉시 매도해야 한다(`exit_reason = "stop_loss"`).

**REQ-SURGE-TRADE-032 (State-Driven)**: While 포지션의 `(current_price - entry_price) / entry_price >= 0.15` 조건이 만족되는 동안, 시스템은 해당 포지션을 즉시 매도해야 한다(`exit_reason = "take_profit"`).

**REQ-SURGE-TRADE-033 (Event-Driven)**: When 포지션의 보유일수(`trading_days_since_entry`)가 5거래일 이상이고 다음 정규장 개장 시점이 되면, the 시스템은 해당 포지션을 시가에 매도해야 한다(`exit_reason = "max_holding_period"`).

**REQ-SURGE-TRADE-034 (Ubiquitous)**: 거래일수 계산은 한국 거래소 영업일 기준이며, 평일 카운팅을 사용한다(주말·공휴일 제외). 단순화를 위해 평일만 카운팅(주말 제외)하며, 공휴일은 1차 구현에서 무시한다.

**REQ-SURGE-TRADE-035 (Ubiquitous)**: 매도 성공 시 시스템은 `SurgeTrade.is_open=False`, `exit_date=today`, `exit_price=current_price`, `exit_reason=...`로 업데이트하고 `SurgePortfolio.current_cash`에 매도 대금을 가산해야 한다.

**REQ-SURGE-TRADE-036 (Unwanted)**: If 종료 조건 체크 중 현재가 조회가 실패하면, then 시스템은 해당 포지션을 다음 체크 사이클로 연기해야 한다(매도 강제 X).

### 2.5 API 엔드포인트 요구사항

**REQ-SURGE-TRADE-040 (Ubiquitous)**: 시스템은 `GET /surge/portfolio` 엔드포인트로 포트폴리오 통계(현재 평가액, 현금, 수익률, 총 거래수)를 제공해야 한다.

**REQ-SURGE-TRADE-041 (Ubiquitous)**: 시스템은 `GET /surge/positions` 엔드포인트로 보유 중 포지션 목록(종목코드, 종목명, 진입가, 현재가, PnL%, 진입일, 보유일수)을 제공해야 한다.

**REQ-SURGE-TRADE-042 (Ubiquitous)**: 시스템은 `GET /surge/trades` 엔드포인트로 종료된 거래 이력 목록을 페이징하여 제공해야 한다.

**REQ-SURGE-TRADE-043 (Ubiquitous)**: 시스템은 `GET /surge/performance` 엔드포인트로 누적 수익률 시계열을 제공해야 한다.

**REQ-SURGE-TRADE-044 (Optional)**: Where 관리자 권한이 확인된 경우, the 시스템은 `POST /surge/execute` 엔드포인트로 수동 매수 실행을 트리거해야 한다.

### 2.6 스케줄러 요구사항

**REQ-SURGE-TRADE-050 (Event-Driven)**: When 애플리케이션이 시작될 때, the 시스템은 `surge_execute_buys`(매수 실행)와 `surge_check_exits`(종료 체크) 두 개의 APScheduler 잡을 등록해야 한다.

**REQ-SURGE-TRADE-051 (State-Driven)**: While 정규장 시간(평일 09:00~15:30 KST)인 동안, `surge_execute_buys`는 매 30분 간격으로 실행되어야 한다.

**REQ-SURGE-TRADE-052 (State-Driven)**: While 정규장 시간(평일 09:00~15:30 KST)인 동안, `surge_check_exits`는 매 5분 간격으로 실행되어야 한다.

**REQ-SURGE-TRADE-053 (Ubiquitous)**: 두 잡 모두 정규장 외 시간 트리거 시에는 즉시 반환(no-op)해야 한다.

### 2.7 보안·운영 요구사항

**REQ-SURGE-TRADE-060 (Unwanted)**: If `POST /surge/execute` 엔드포인트가 관리자 인증 토큰 없이 호출되면, then 시스템은 401 Unauthorized를 반환해야 한다.

**REQ-SURGE-TRADE-061 (Ubiquitous)**: 시스템은 모든 매수·매도 시도(성공/실패 포함)를 `logger.info` 또는 `logger.warning`으로 기록해야 한다(stock_code, signal_id, action, reason 포함).

**REQ-SURGE-TRADE-062 (Ubiquitous)**: 시스템은 데이터베이스 트랜잭션을 사용하여 `current_cash` 차감과 `SurgeTrade` 생성을 원자적으로 수행해야 한다.

---

## 3. 인수 조건 (Acceptance Criteria) — Given/When/Then

### 3.1 매수 시나리오

**AC-SURGE-TRADE-001**: 정규장 중 유효 시그널 매수 성공
- **Given**: 현재 시각이 KST 화요일 10:00이고, `FundSignal(stock_code="005930", signal_type="surge_candidate", surge_probability_score=0.75, created_at=today)` 레코드가 존재하며, 005930에 대해 `is_open=True`인 `SurgeTrade`가 없고, `SurgePortfolio.current_cash >= 1_000_000`이며, `naver_finance.fetch_current_price("005930") = 75000`을 반환한다
- **When**: `surge_execute_buys` 잡이 실행된다
- **Then**: 새 `SurgeTrade(stock_code="005930", entry_price=75000, quantity=13, entry_date=today, is_open=True)` 레코드가 생성되고, `SurgePortfolio.current_cash`는 `975_000` 차감되어야 한다(13 * 75000 = 975000)

**AC-SURGE-TRADE-002**: 정규장 외 시간 매수 스킵
- **Given**: 현재 시각이 KST 토요일 14:00이다
- **When**: `surge_execute_buys` 잡이 실행된다
- **Then**: `SurgeTrade` 레코드가 생성되지 않고, `current_cash` 변화가 없어야 한다

**AC-SURGE-TRADE-003**: 확률 임계값 미달 시그널 무시
- **Given**: `FundSignal(surge_probability_score=0.45, created_at=today)` 레코드만 존재한다
- **When**: `surge_execute_buys` 잡이 실행된다
- **Then**: 어떤 `SurgeTrade`도 생성되지 않아야 한다

**AC-SURGE-TRADE-004**: 동일 종목 중복 진입 차단
- **Given**: `SurgeTrade(stock_code="005930", is_open=True)` 가 이미 존재하고, 동일 종목 신규 시그널이 들어왔다
- **When**: `surge_execute_buys` 잡이 실행된다
- **Then**: 신규 `SurgeTrade`는 생성되지 않아야 한다

**AC-SURGE-TRADE-005**: 일일 최대 진입 한도 적용
- **Given**: 오늘 이미 5개의 `SurgeTrade.entry_date == today` 레코드가 존재하고, 6번째 시그널이 들어왔다
- **When**: `surge_execute_buys` 잡이 실행된다
- **Then**: 6번째 시그널에 대해서는 `SurgeTrade`가 생성되지 않아야 한다

**AC-SURGE-TRADE-006**: 현금 부족 시 매수 스킵
- **Given**: `SurgePortfolio.current_cash = 500_000`이고 1포지션 필요 자금은 1_000_000이다
- **When**: `surge_execute_buys` 잡이 실행된다
- **Then**: 신규 `SurgeTrade`가 생성되지 않고, 경고 로그가 기록되어야 한다

### 3.2 종료 조건 시나리오

**AC-SURGE-TRADE-010**: 손절 트리거
- **Given**: `SurgeTrade(stock_code="005930", entry_price=100000, quantity=10, is_open=True)` 가 존재하고, 현재가가 91000이다(-9%)
- **When**: `surge_check_exits` 잡이 정규장 중 실행된다
- **Then**: 해당 `SurgeTrade.is_open=False`, `exit_price=91000`, `exit_reason="stop_loss"`로 업데이트되고, `SurgePortfolio.current_cash`에 910_000이 가산되어야 한다

**AC-SURGE-TRADE-011**: 익절 트리거
- **Given**: `SurgeTrade(entry_price=100000, quantity=10, is_open=True)` 가 존재하고, 현재가가 116000이다(+16%)
- **When**: `surge_check_exits` 잡이 정규장 중 실행된다
- **Then**: 해당 `SurgeTrade.is_open=False`, `exit_reason="take_profit"`로 업데이트되어야 한다

**AC-SURGE-TRADE-012**: 5거래일 보유 종료
- **Given**: `SurgeTrade(entry_date=2026-04-28 (월요일), is_open=True)` 가 존재하고, 현재 일자가 2026-05-07 (5영업일 경과)이다
- **When**: 정규장 개장 직후 `surge_check_exits` 잡이 실행된다
- **Then**: 해당 `SurgeTrade.exit_reason="max_holding_period"`로 매도되어야 한다

**AC-SURGE-TRADE-013**: 정규장 외 종료 조건 체크 안 함
- **Given**: 현재 시각이 KST 일요일 11:00이고, `is_open=True`인 포지션이 존재한다
- **When**: `surge_check_exits` 잡이 실행된다
- **Then**: 어떤 종료 처리도 일어나지 않아야 한다

**AC-SURGE-TRADE-014**: 가격 조회 실패 시 종료 연기
- **Given**: `SurgeTrade(is_open=True)` 가 존재하고, `naver_finance.fetch_current_price()`가 None을 반환한다
- **When**: `surge_check_exits` 잡이 실행된다
- **Then**: 해당 포지션은 `is_open=True` 상태를 유지하고 다음 사이클로 연기되어야 한다

### 3.3 API 시나리오

**AC-SURGE-TRADE-020**: 포트폴리오 통계 조회
- **Given**: `SurgePortfolio(initial_capital=5_000_000, current_cash=3_500_000)` 가 존재하고, `is_open=True`인 포지션의 현재 평가액 합이 1_700_000이다
- **When**: 클라이언트가 `GET /surge/portfolio` 호출한다
- **Then**: 응답은 `{"current_value": 5_200_000, "current_cash": 3_500_000, "return_pct": 4.0, "total_trades": ...}` 형식이어야 한다

**AC-SURGE-TRADE-021**: 보유 포지션 조회
- **Given**: 2개의 `is_open=True` 포지션이 존재한다
- **When**: 클라이언트가 `GET /surge/positions` 호출한다
- **Then**: 2개 포지션의 `stock_code, stock_name, entry_price, current_price, pnl_pct, entry_date, days_held` 배열이 반환되어야 한다

**AC-SURGE-TRADE-022**: 종료 거래 이력 조회
- **Given**: 5개의 `is_open=False` 종료 거래가 존재한다
- **When**: 클라이언트가 `GET /surge/trades?limit=10&offset=0` 호출한다
- **Then**: 5개 거래의 상세 정보(`exit_reason`, `pnl_pct`, `holding_days` 포함)가 반환되어야 한다

**AC-SURGE-TRADE-023**: 관리자 수동 실행
- **Given**: 유효한 관리자 토큰이 있다
- **When**: 클라이언트가 `POST /surge/execute` 호출한다
- **Then**: `surge_execute_buys` 잡이 즉시 실행되고 결과 요약이 반환되어야 한다

**AC-SURGE-TRADE-024**: 무권한 접근 거부
- **Given**: 토큰 없이 요청을 보낸다
- **When**: 클라이언트가 `POST /surge/execute` 호출한다
- **Then**: 401 Unauthorized 응답이 반환되어야 한다

### 3.4 데이터 격리 시나리오

**AC-SURGE-TRADE-030**: 다른 모델과 자본 격리
- **Given**: `VirtualPortfolio.current_cash = 10_000_000`이다
- **When**: `SurgePortfolio.current_cash`를 1_000_000 차감하는 매수가 실행된다
- **Then**: `VirtualPortfolio.current_cash`는 변경되지 않아야 한다

**AC-SURGE-TRADE-031**: FundSignal.paper_executed 미사용
- **Given**: 신규 `surge_candidate` 시그널이 존재하고, `FundSignal.paper_executed=False`이다
- **When**: `surge_execute_buys` 잡이 해당 시그널로 매수를 실행한다
- **Then**: `FundSignal.paper_executed`는 변경되지 않아야 한다(여전히 False)

---

## 4. 기술 설계 (Technical Design)

### 4.1 데이터베이스 스키마

#### `surge_portfolios` 테이블

```sql
CREATE TABLE surge_portfolios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    initial_capital NUMERIC(15, 2) NOT NULL DEFAULT 5000000,
    current_cash NUMERIC(15, 2) NOT NULL DEFAULT 5000000,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

- 단일 레코드(`id=1`) 가정
- `initial_capital`: 초기 자본 (5,000,000 KRW)
- `current_cash`: 현재 가용 현금 (매수 시 차감, 매도 시 가산)

#### `surge_trades` 테이블

```sql
CREATE TABLE surge_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id INTEGER NOT NULL REFERENCES surge_portfolios(id),
    stock_code VARCHAR(20) NOT NULL,
    stock_name VARCHAR(100) NOT NULL,
    signal_id INTEGER REFERENCES fund_signals(id),
    entry_price NUMERIC(15, 2) NOT NULL,
    quantity INTEGER NOT NULL,
    entry_date DATE NOT NULL,
    exit_date DATE,
    exit_price NUMERIC(15, 2),
    is_open BOOLEAN NOT NULL DEFAULT TRUE,
    exit_reason VARCHAR(50),
    surge_probability_score NUMERIC(5, 4),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_surge_trades_open ON surge_trades(is_open) WHERE is_open = TRUE;
CREATE INDEX idx_surge_trades_stock_code ON surge_trades(stock_code);
CREATE INDEX idx_surge_trades_entry_date ON surge_trades(entry_date);
```

- `signal_id`: 매수 트리거가 된 `FundSignal` ID (역추적용)
- `exit_reason`: `"stop_loss" | "take_profit" | "max_holding_period" | "manual"`
- `surge_probability_score`: 진입 시점의 시그널 확률(역분석용 스냅샷)

### 4.2 SQLAlchemy 모델

`backend/app/models/surge_portfolio.py`:

```python
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import Column, Integer, String, Numeric, Boolean, DateTime, Date, ForeignKey
from sqlalchemy.orm import relationship
from app.db import Base


class SurgePortfolio(Base):
    __tablename__ = "surge_portfolios"

    id = Column(Integer, primary_key=True, autoincrement=True)
    initial_capital = Column(Numeric(15, 2), nullable=False, default=Decimal("5000000"))
    current_cash = Column(Numeric(15, 2), nullable=False, default=Decimal("5000000"))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    trades = relationship("SurgeTrade", back_populates="portfolio")


class SurgeTrade(Base):
    __tablename__ = "surge_trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    portfolio_id = Column(Integer, ForeignKey("surge_portfolios.id"), nullable=False)
    stock_code = Column(String(20), nullable=False, index=True)
    stock_name = Column(String(100), nullable=False)
    signal_id = Column(Integer, ForeignKey("fund_signals.id"), nullable=True)
    entry_price = Column(Numeric(15, 2), nullable=False)
    quantity = Column(Integer, nullable=False)
    entry_date = Column(Date, nullable=False, index=True)
    exit_date = Column(Date, nullable=True)
    exit_price = Column(Numeric(15, 2), nullable=True)
    is_open = Column(Boolean, nullable=False, default=True, index=True)
    exit_reason = Column(String(50), nullable=True)
    surge_probability_score = Column(Numeric(5, 4), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    portfolio = relationship("SurgePortfolio", back_populates="trades")
```

### 4.3 서비스 레이어 (`surge_trading_service.py`)

`backend/app/services/surge_trading_service.py`:

핵심 함수 시그니처:

```python
from datetime import date, datetime, time
from decimal import Decimal
from typing import List, Optional
from sqlalchemy.orm import Session
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
MARKET_OPEN = time(9, 0)
MARKET_CLOSE = time(15, 30)


def is_market_hours(now: Optional[datetime] = None) -> bool:
    """KST 평일 09:00~15:30 여부 확인"""
    now = now or datetime.now(KST)
    if now.weekday() >= 5:  # 토(5), 일(6)
        return False
    current_time = now.time()
    return MARKET_OPEN <= current_time <= MARKET_CLOSE


def get_or_create_portfolio(db: Session) -> SurgePortfolio:
    """단일 SurgePortfolio 인스턴스 조회 또는 생성"""


def get_today_signals(
    db: Session,
    min_probability: Decimal = Decimal("0.6"),
) -> List[FundSignal]:
    """오늘 생성된 surge_candidate 시그널 중 임계값 이상 반환"""


def get_open_position(db: Session, stock_code: str) -> Optional[SurgeTrade]:
    """해당 종목의 오픈 포지션 조회 (중복 진입 차단용)"""


def count_today_entries(db: Session) -> int:
    """오늘(today) 진입한 포지션 수"""


def execute_buy_orders(
    db: Session,
    max_daily_entries: int = 5,
    position_pct: Decimal = Decimal("0.20"),
    min_probability: Decimal = Decimal("0.6"),
) -> dict:
    """
    매수 실행 메인 함수.

    1. 정규장 시간 체크 (아닐 시 즉시 반환)
    2. 오늘 시그널 조회
    3. 임계값/중복/한도 필터링
    4. 각 시그널에 대해 매수 시도 (가격 조회 → 수량 계산 → 트랜잭션)
    5. 결과 요약 반환

    Returns: {"executed": int, "skipped": int, "failed": int, "details": [...]}
    """


def calculate_trading_days_elapsed(entry_date: date, today: Optional[date] = None) -> int:
    """평일 카운팅 (단순화: 주말 제외, 공휴일 무시)"""


def check_exit_conditions(
    db: Session,
    stop_loss_pct: Decimal = Decimal("-0.08"),
    take_profit_pct: Decimal = Decimal("0.15"),
    max_holding_days: int = 5,
) -> dict:
    """
    종료 조건 체크 메인 함수.

    1. 정규장 시간 체크 (아닐 시 즉시 반환)
    2. 모든 is_open=True 포지션 순회
    3. 현재가 조회 → PnL 계산
    4. 손절/익절/만기 조건 체크 → 매도 실행
    5. 결과 요약 반환

    Returns: {"closed": int, "still_open": int, "errors": int, "details": [...]}
    """


def execute_sell(
    db: Session,
    trade: SurgeTrade,
    exit_price: Decimal,
    exit_reason: str,
) -> SurgeTrade:
    """매도 실행 (트랜잭션 처리, current_cash 가산)"""


def get_portfolio_stats(db: Session) -> dict:
    """
    포트폴리오 통계 계산.

    Returns:
        {
            "initial_capital": Decimal,
            "current_cash": Decimal,
            "open_positions_value": Decimal,  # 평가액 합
            "current_value": Decimal,         # current_cash + open_positions_value
            "return_pct": float,              # (current_value - initial_capital) / initial_capital * 100
            "total_trades": int,              # 누적 거래수
            "open_trades": int,
            "closed_trades": int,
        }
    """


def get_open_positions_detail(db: Session) -> List[dict]:
    """
    보유 포지션 상세 (현재가, PnL% 포함).

    Returns: [
        {
            "stock_code": str,
            "stock_name": str,
            "entry_price": Decimal,
            "current_price": Decimal,
            "quantity": int,
            "pnl_pct": float,
            "entry_date": date,
            "days_held": int,
            "surge_probability_score": Decimal,
        }, ...
    ]
    """
```

### 4.4 라우터 (`surge_trading.py`)

`backend/app/routers/surge_trading.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List
from app.db import get_db
from app.services import surge_trading_service
from app.auth import require_admin  # 기존 admin 인증 의존성

router = APIRouter(prefix="/surge", tags=["surge-trading"])


@router.get("/portfolio")
def get_portfolio(db: Session = Depends(get_db)):
    """포트폴리오 통계"""
    return surge_trading_service.get_portfolio_stats(db)


@router.get("/positions")
def get_positions(db: Session = Depends(get_db)):
    """보유 포지션 목록"""
    return surge_trading_service.get_open_positions_detail(db)


@router.get("/trades")
def get_trades(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """종료 거래 이력 (페이징)"""
    return surge_trading_service.get_closed_trades(db, limit=limit, offset=offset)


@router.get("/performance")
def get_performance(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """누적 수익률 시계열"""
    return surge_trading_service.get_performance_timeseries(db, days=days)


@router.post("/execute", dependencies=[Depends(require_admin)])
def trigger_execute(db: Session = Depends(get_db)):
    """관리자 수동 매수 트리거"""
    return surge_trading_service.execute_buy_orders(db)
```

### 4.5 시그널 중복 진입 차단 전략 (Option B)

**선택**: Option B — `SurgeTrade` 조회 기반 중복 차단

**근거**:
- `FundSignal.paper_executed`는 AI Fund 모델 전용으로, 재사용 시 의미 충돌
- `SurgeTrade.is_open + stock_code` 조합 인덱스로 O(1) 조회 가능
- `FundSignal` 스키마 변경 불필요(다른 모델에 영향 X)

**구현**:
```python
def get_open_position(db: Session, stock_code: str) -> Optional[SurgeTrade]:
    return db.query(SurgeTrade).filter(
        SurgeTrade.stock_code == stock_code,
        SurgeTrade.is_open == True,
    ).first()
```

매수 실행 전 항상 호출하여 None인 경우에만 진입.

### 4.6 거래일수 계산 (단순화)

**1차 구현**: 주말만 제외, 공휴일은 무시

```python
def calculate_trading_days_elapsed(entry_date: date, today: Optional[date] = None) -> int:
    today = today or date.today()
    if today <= entry_date:
        return 0
    days = 0
    current = entry_date
    while current < today:
        current += timedelta(days=1)
        if current.weekday() < 5:  # 0=월, 4=금
            days += 1
    return days
```

**확장 여지**: 한국 거래소 공휴일 캘린더 통합은 별도 SPEC으로 분리.

### 4.7 스케줄러 통합

`backend/app/scheduler.py` 추가:

```python
from app.services import surge_trading_service

def schedule_surge_jobs(scheduler):
    # 매수 실행: 평일 09:00~15:30 동안 30분 간격
    scheduler.add_job(
        func=lambda: _run_with_session(surge_trading_service.execute_buy_orders),
        trigger="cron",
        day_of_week="mon-fri",
        hour="9-15",
        minute="0,30",
        timezone="Asia/Seoul",
        id="surge_execute_buys",
        replace_existing=True,
    )
    # 종료 체크: 평일 09:00~15:30 동안 5분 간격
    scheduler.add_job(
        func=lambda: _run_with_session(surge_trading_service.check_exit_conditions),
        trigger="cron",
        day_of_week="mon-fri",
        hour="9-15",
        minute="*/5",
        timezone="Asia/Seoul",
        id="surge_check_exits",
        replace_existing=True,
    )
```

각 서비스 함수 내부에서도 `is_market_hours()` 가드를 두어 부정확한 트리거(15:35 등)에서도 안전.

### 4.8 API 응답 스키마

**GET /surge/portfolio 응답**:
```json
{
  "initial_capital": "5000000.00",
  "current_cash": "3500000.00",
  "open_positions_value": "1700000.00",
  "current_value": "5200000.00",
  "return_pct": 4.0,
  "total_trades": 12,
  "open_trades": 2,
  "closed_trades": 10
}
```

**GET /surge/positions 응답**:
```json
[
  {
    "id": 5,
    "stock_code": "005930",
    "stock_name": "삼성전자",
    "entry_price": "75000.00",
    "current_price": "78500.00",
    "quantity": 13,
    "pnl_pct": 4.67,
    "entry_date": "2026-05-05",
    "days_held": 2,
    "surge_probability_score": "0.7500"
  }
]
```

**GET /surge/trades 응답**:
```json
{
  "items": [
    {
      "id": 3,
      "stock_code": "035420",
      "stock_name": "NAVER",
      "entry_price": "200000.00",
      "exit_price": "230000.00",
      "quantity": 5,
      "entry_date": "2026-04-25",
      "exit_date": "2026-04-30",
      "exit_reason": "take_profit",
      "pnl_pct": 15.0,
      "holding_days": 5
    }
  ],
  "total": 10,
  "limit": 20,
  "offset": 0
}
```

---

## 5. 마이그레이션 (Migration)

### 5.1 마이그레이션 파일

**파일명**: `backend/alembic/versions/052_spec_ai_013_surge_portfolio.py`

**revision**: `052_spec_ai_013_surge_portfolio`
**down_revision**: 직전 최신 마이그레이션 (확인 필요, 추정 `051_*`)

### 5.2 마이그레이션 내용

```python
"""SPEC-AI-013: 급등예측 모의투자 포트폴리오

Revision ID: 052_spec_ai_013_surge_portfolio
Revises: 051_<latest>
Create Date: 2026-05-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import func

revision = "052_spec_ai_013_surge_portfolio"
down_revision = "051_<latest>"  # 실제 최신 revision 확인 후 교체
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "surge_portfolios",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("initial_capital", sa.Numeric(15, 2), nullable=False, server_default="5000000"),
        sa.Column("current_cash", sa.Numeric(15, 2), nullable=False, server_default="5000000"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=func.now()),
    )

    op.create_table(
        "surge_trades",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("portfolio_id", sa.Integer, sa.ForeignKey("surge_portfolios.id"), nullable=False),
        sa.Column("stock_code", sa.String(20), nullable=False),
        sa.Column("stock_name", sa.String(100), nullable=False),
        sa.Column("signal_id", sa.Integer, sa.ForeignKey("fund_signals.id"), nullable=True),
        sa.Column("entry_price", sa.Numeric(15, 2), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("entry_date", sa.Date, nullable=False),
        sa.Column("exit_date", sa.Date, nullable=True),
        sa.Column("exit_price", sa.Numeric(15, 2), nullable=True),
        sa.Column("is_open", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("exit_reason", sa.String(50), nullable=True),
        sa.Column("surge_probability_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=func.now()),
    )

    op.create_index("idx_surge_trades_open", "surge_trades", ["is_open"])
    op.create_index("idx_surge_trades_stock_code", "surge_trades", ["stock_code"])
    op.create_index("idx_surge_trades_entry_date", "surge_trades", ["entry_date"])

    # 초기 포트폴리오 레코드 생성
    op.execute(
        "INSERT INTO surge_portfolios (initial_capital, current_cash) "
        "VALUES (5000000, 5000000)"
    )


def downgrade():
    op.drop_index("idx_surge_trades_entry_date", table_name="surge_trades")
    op.drop_index("idx_surge_trades_stock_code", table_name="surge_trades")
    op.drop_index("idx_surge_trades_open", table_name="surge_trades")
    op.drop_table("surge_trades")
    op.drop_table("surge_portfolios")
```

### 5.3 마이그레이션 검증 절차

1. `cd backend && uv run alembic upgrade head`
2. `psql` 또는 SQLite 클라이언트로 두 테이블 생성 확인
3. `SELECT * FROM surge_portfolios;` 결과가 1행(initial 5_000_000) 확인
4. 롤백 테스트: `uv run alembic downgrade -1` 후 테이블 삭제 확인

---

## 6. 프론트엔드 (Frontend)

### 6.1 탭 추가

`frontend/src/app/trading/page.tsx`:

```typescript
type Tab = 'vip' | 'ks200' | 'paper' | 'surge' | 'compare';

const tabs: { key: Tab; label: string }[] = [
  { key: 'vip', label: 'VIP 추종' },
  { key: 'ks200', label: 'KS200' },
  { key: 'paper', label: 'AI 펀드' },
  { key: 'surge', label: '급등예측' },  // 신규
  { key: 'compare', label: '비교' },
];
```

### 6.2 API 클라이언트

`frontend/src/lib/api/surge-trading.ts` (신규):

```typescript
import { apiClient } from '../api';

export interface SurgePortfolioStats {
  initial_capital: string;
  current_cash: string;
  open_positions_value: string;
  current_value: string;
  return_pct: number;
  total_trades: number;
  open_trades: number;
  closed_trades: number;
}

export interface SurgePosition {
  id: number;
  stock_code: string;
  stock_name: string;
  entry_price: string;
  current_price: string;
  quantity: number;
  pnl_pct: number;
  entry_date: string;
  days_held: number;
  surge_probability_score: string;
}

export interface SurgeTradeRecord {
  id: number;
  stock_code: string;
  stock_name: string;
  entry_price: string;
  exit_price: string;
  quantity: number;
  entry_date: string;
  exit_date: string;
  exit_reason: 'stop_loss' | 'take_profit' | 'max_holding_period' | 'manual';
  pnl_pct: number;
  holding_days: number;
}

export const surgeApi = {
  getPortfolio: () => apiClient.get<SurgePortfolioStats>('/surge/portfolio'),
  getPositions: () => apiClient.get<SurgePosition[]>('/surge/positions'),
  getTrades: (limit = 20, offset = 0) =>
    apiClient.get<{ items: SurgeTradeRecord[]; total: number }>(
      `/surge/trades?limit=${limit}&offset=${offset}`
    ),
  getPerformance: (days = 30) =>
    apiClient.get(`/surge/performance?days=${days}`),
};
```

### 6.3 SurgeTab 컴포넌트

`frontend/src/app/trading/components/SurgeTab.tsx` (신규):

기본 구조:

```typescript
'use client';

import { useEffect, useState } from 'react';
import { surgeApi, SurgePortfolioStats, SurgePosition, SurgeTradeRecord } from '@/lib/api/surge-trading';

export default function SurgeTab() {
  const [stats, setStats] = useState<SurgePortfolioStats | null>(null);
  const [positions, setPositions] = useState<SurgePosition[]>([]);
  const [trades, setTrades] = useState<SurgeTradeRecord[]>([]);

  useEffect(() => {
    Promise.all([
      surgeApi.getPortfolio(),
      surgeApi.getPositions(),
      surgeApi.getTrades(),
    ]).then(([s, p, t]) => {
      setStats(s);
      setPositions(p);
      setTrades(t.items);
    });
  }, []);

  return (
    <div className="space-y-6">
      {/* 1. 포트폴리오 통계 카드 (초기자본/현재가치/수익률) */}
      {/* 2. 보유 포지션 테이블 (종목명/진입가/현재가/PnL%/보유일) */}
      {/* 3. 종료 거래 이력 테이블 (페이징) */}
      {/* 4. 누적 수익률 차트 (recharts 또는 기존 차트 라이브러리 재사용) */}
    </div>
  );
}
```

기존 `KS200Tab.tsx` / `PaperTab.tsx`의 UI 패턴을 차용하되, **급등예측 시그널 확률(`surge_probability_score`)** 컬럼을 포지션 테이블에 추가하여 변별성을 부각.

### 6.4 페이지 통합

`frontend/src/app/trading/page.tsx`:

```typescript
{activeTab === 'surge' && <SurgeTab />}
```

`compare` 탭에는 4개 모델(VIP/KS200/AI Fund/Surge) 동시 비교 카드를 표시(기존 `CompareTab` 확장).

---

## Exclusions (What NOT to Build)

이 SPEC은 명시적으로 **다음을 포함하지 않는다**:

1. **실거래 통합 제외**: 실제 증권사 API 연동, 실주문 전송 (모의투자 한정)
2. **고급 ML 모델 제외**: 자체 머신러닝 기반 급등예측 모델 (SPEC-AI-012의 룰 기반 시그널만 소비)
3. **알림 시스템 제외**: 카카오톡·텔레그램 매수/매도 알림 (별도 SPEC으로 분리)
4. **백테스팅 엔진 제외**: 본 포트폴리오 전용 백테스트 — 기존 `/fund/surge-backtest` (SPEC-AI-012) 사용
5. **공휴일 캘린더 제외**: 한국 거래소 휴장일 정밀 카운팅 (1차는 평일만, 추후 별도 SPEC)
6. **포지션 사이징 동적 조정 제외**: 변동성 기반 비중 조절, 켈리 공식 등 (정액 20% 고정)
7. **부분 매도 제외**: 분할 익절·트레일링 스탑 (전량 매도만)
8. **다중 SurgePortfolio 인스턴스 제외**: 사용자별 독립 포트폴리오 (단일 인스턴스, `id=1`)
9. **자동 자본 재투입 제외**: 손실 시 외부 자본 추가 (`initial_capital` 고정)
10. **`FundSignal.paper_executed` 필드 수정 제외**: 다른 모델 영향 차단을 위해 절대 변경 금지

---

## Configuration Reference

기본값 (서비스 함수 파라미터로 노출, 추후 `app/config.py`로 이동 가능):

| 설정 키 | 기본값 | 설명 |
|---|---|---|
| `SURGE_INITIAL_CAPITAL` | 5_000_000 KRW | 초기 자본 |
| `SURGE_POSITION_PCT` | 0.20 | 1포지션당 자본 비중 |
| `SURGE_MIN_PROBABILITY` | 0.6 | 시그널 확률 최소 임계값 |
| `SURGE_MAX_DAILY_ENTRIES` | 5 | 일일 최대 진입 수 |
| `SURGE_STOP_LOSS_PCT` | -0.08 | 손절 임계값 |
| `SURGE_TAKE_PROFIT_PCT` | 0.15 | 익절 임계값 |
| `SURGE_MAX_HOLDING_DAYS` | 5 | 최대 보유 거래일수 |

---

## Definition of Done

- [ ] DB 마이그레이션 052 작성 및 적용 성공
- [ ] `SurgePortfolio`, `SurgeTrade` 모델 정의 완료
- [ ] `surge_trading_service.py` 핵심 함수 구현 (매수/매도/통계)
- [ ] `surge_trading.py` 라우터 5개 엔드포인트 구현
- [ ] 스케줄러 잡 2종(`surge_execute_buys`, `surge_check_exits`) 등록
- [ ] 정규장 시간 가드(`is_market_hours()`) 통합
- [ ] 단위 테스트: 모든 EARS 요구사항(REQ-SURGE-TRADE-*)에 대한 pytest 케이스 작성, 85% 이상 커버리지
- [ ] 인수 테스트: 모든 AC-SURGE-TRADE-* 시나리오 검증
- [ ] 프론트엔드 SurgeTab 컴포넌트 구현 및 trading page 통합
- [ ] 다른 모델(VIP/KS200/AI Fund) 회귀 테스트 통과
- [ ] `FundSignal.paper_executed` 필드 미변경 확인
- [ ] CHANGELOG 항목 추가
- [ ] 백엔드 quality gate 통과: `uv run pytest tests/ --tb=short -q -m "not slow"`, `uv run ruff check .`, `uv run mypy app/`
- [ ] 프론트엔드 lint 통과: `npm run lint`
