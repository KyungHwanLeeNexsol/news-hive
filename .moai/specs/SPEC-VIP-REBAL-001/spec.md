---
id: SPEC-VIP-REBAL-001
title: VIP 포트폴리오 비중 미러링 리밸런싱
status: Planned
priority: High
created: 2026-04-30
lifecycle: spec-anchored
---

# SPEC-VIP-REBAL-001: VIP 포트폴리오 비중 미러링 리밸런싱

## HISTORY

- 2026-04-30: 초안 작성. SPEC-VIP-001(VIP 추종 자동매매)의 후속 SPEC. 2차 매수 시 가용 현금 부족 문제를 VIP 종료 포지션 청산 + VIP 비중 미러링 리밸런싱으로 해결.

---

## Overview

**전략명**: VIP 포트폴리오 비중 미러링 리밸런싱 (VIP Weight-Mirroring Rebalancer)

**목표**: VIP 추종 매매(SPEC-VIP-001)에서 2차 매수 시점에 가용 현금이 부족할 경우, 단순히 매수를 포기하는 대신 (1) VIP가 이미 빠져나간 종목을 청산하고 (2) VIP의 보유 비율(`stake_pct`)에 비례한 목표 비중으로 포트폴리오를 재조정하여 현금을 확보한 뒤 2차 매수를 재시도한다.

**현재 문제**:
- `VIPPortfolio.current_cash`가 372,519 KRW까지 줄어 2차 매수 최소 단위(1,250,000 KRW)를 충족하지 못함
- `vip_follow_trading.py:417`의 "VIP 잔여 현금 부족" 로그가 매시간 누적되며 어떤 조치도 일어나지 않음
- VIP가 이미 종료(reduce / below5)한 종목이 그대로 보유되어 자본이 묶임

**범위**:
- `backend/app/services/vip_follow_trading.py`에 신규 헬퍼 함수 4개 추가
- 기존 `check_second_buy_pending()` 함수 동작 확장 (현금 부족 시 리밸런싱 시도 → 재매수)
- 기존 `_execute_vip_buy()` / `_execute_vip_sell()` 재사용 (신규 매매 로직 작성 금지)
- `VIPDisclosure.disclosure_type`과 `stake_pct` 컬럼 활용

**비범위 (Out of Scope)**:
- 데이터 모델 변경 없음 (스키마/마이그레이션 없음)
- 신규 API 엔드포인트 없음
- 1차 매수 로직 변경 없음 (1차 매수는 SPEC-VIP-001 그대로)
- 50% 익절 로직 변경 없음
- 새 스케줄러 작업 추가 없음 (기존 60분 주기 `check_second_buy_pending` 재사용)
- 백테스트/통계 API 추가 없음

---

## Environment

- **Backend**: FastAPI + SQLAlchemy + APScheduler (기존 인프라 그대로)
- **DB**: PostgreSQL (스키마 변경 없음, 기존 `vip_*` 테이블 재사용)
- **시세 조회**: `app/services/naver_finance.fetch_current_price` (기존 함수)
- **타임존**: Asia/Seoul (KST), 한국 거래시간 평일 09:00–18:00
- **수정 대상 파일**: `backend/app/services/vip_follow_trading.py` (단일 파일)

---

## Assumptions

1. `VIPDisclosure.stake_pct`는 신규 공시에서 항상 채워지지만, 과거 공시 일부에는 `None`이 존재할 수 있다.
2. 동일 종목에 대해 가장 최근 `VIPDisclosure` 한 건의 `disclosure_type`이 해당 VIP의 현재 보유 상태를 정확히 반영한다 (`accumulate` = 보유 중, `reduce`/`below5` = 종료 또는 축소).
3. 모든 오픈 포지션의 시가는 `naver_finance.fetch_current_price()`로 조회 가능하다.
4. 기존 `_execute_vip_sell(db, trade, price, qty, reason)`는 부분 매도(qty < trade.quantity)와 전량 매도(qty == trade.quantity)를 모두 정상 처리하며, 호출 후 `db.commit()`까지 완료한다.
5. 기존 `_execute_vip_buy(db, portfolio, disclosure, stock, split_sequence)`는 가용 현금 검증 후 매수를 수행한다.
6. 리밸런싱은 동기 흐름에서 실행해도 무방한 빈도이다 (60분 1회, 평균 2~5개 포지션 대상).
7. `REBALANCE_THRESHOLD = 0.03` (3%) 미만의 비중 차이는 거래비용/슬리피지 대비 효과가 없으므로 무시한다.

---

## Requirements (EARS Format)

### REQ-VIP-REBAL-001: VIP 종료 포지션 우선 청산 (Event-Driven)

**WHEN** 2차 매수가 가용 현금 부족으로 실패할 가능성이 감지되고 **AND** 포트폴리오에 보유 중인 종목 중 가장 최근 `VIPDisclosure.disclosure_type`이 `reduce` 또는 `below5`인 종목이 존재하는 경우, **THEN** 시스템은 해당 종목의 모든 `is_open=True`인 `VIPTrade`를 시장가 전량 매도해야 한다 (`exit_reason="vip_rebalance_exit"`).

**규칙**:
- 종목 단위로 그룹핑하여 한 번에 청산한다 (1차/2차 분할 모두 동시 청산).
- 청산 결과 확보된 현금은 `VIPPortfolio.current_cash` 누적 합계로 추적한다.
- 청산 대상이 없으면 0을 반환하고 다음 단계로 진행한다.

**WHY**: VIP가 이미 빠져나간 종목은 추종 전략의 근거가 사라진 자본 묶음이다.
**IMPACT**: 누락 시 자연스러운 청산 후보가 무시되어 불필요한 비중 조정 매매가 발생한다.

### REQ-VIP-REBAL-002: VIP 보유 비중 기반 목표 가중치 산출 (Ubiquitous)

시스템은 항상 다음 공식으로 각 보유 종목의 목표 비중을 계산해야 한다:

```
target_weight[stock_i] = stake_pct[stock_i] / Σ(stake_pct[stock_j] for j ∈ open_positions)
```

**규칙**:
- 분모는 현재 `is_open=True` 포지션을 가진 종목의 `stake_pct` 합계이다.
- 동일 종목에 여러 `VIPTrade`(1차/2차)가 있어도 종목 단위로 1개의 `stake_pct` (가장 최근 공시 기준)만 사용한다.
- `stake_pct`가 `None`인 종목은 다른 모든 보유 종목의 평균값을 임시 대체값으로 사용한다.
- 모든 `stake_pct`가 `None`이면 모든 종목에 동일 가중치(`1/N`)를 부여한다.

### REQ-VIP-REBAL-003: 임계치 기반 리밸런싱 매매 (State-Driven)

**IF** 어떤 보유 종목의 `|current_weight - target_weight| > REBALANCE_THRESHOLD (0.03)`인 경우, **THEN** 시스템은 해당 종목에 대해 다음 매매를 실행해야 한다:

- `current_weight > target_weight + REBALANCE_THRESHOLD`: 차이를 메우는 만큼 시장가 매도 (`exit_reason="vip_rebalance_trim"`)
- `current_weight < target_weight - REBALANCE_THRESHOLD`: 차이를 메우는 만큼 시장가 매수

**규칙**:
- `current_weight = position_market_value / total_portfolio_value`
- `total_portfolio_value = current_cash + Σ(open_position_market_values)`
- 매도 수량 = `floor((current_weight - target_weight) × total_portfolio_value / current_price)`
- 매수 수량 = `floor((target_weight - current_weight) × total_portfolio_value / current_price)`
- 매수는 매도 후 확보된 현금 한도 내에서만 실행한다 (현금 부족 시 가능한 만큼만 매수).
- 매도가 우선 처리되고, 매수가 그 뒤를 따른다 (현금 흐름 보장).

### REQ-VIP-REBAL-004: 단일 포지션 보호 (Unwanted)

시스템은 다음 조건에서 어떤 리밸런싱 매도도 실행해서는 안 된다:

- 포트폴리오의 오픈 포지션 종목 수가 1개 이하인 경우
- 모든 보유 종목의 `disclosure_type`이 `reduce` 또는 `below5`이고 청산 대상도 없는 경우 (논리적으로 불가능하나 안전장치로 명시)

**WHY**: 단일 포지션 전량 청산은 사실상 포트폴리오 전체 청산이며, 의도치 않은 자본 회수를 유발한다.
**IMPACT**: 미준수 시 1종목만 남은 포트폴리오가 통째로 청산되어 추종 전략이 정지한다.

### REQ-VIP-REBAL-005: 2차 매수 재시도 흐름 (Event-Driven)

**WHEN** `check_second_buy_pending()`가 임의의 펜딩 2차 매수 후보(`split_sequence=1`인 영업일 3일 경과 트레이드)를 감지하고 **AND** 가용 현금이 1차 매수 단가(`disclosure.avg_price` 또는 1차 트레이드 `entry_price`) × 1주 미만인 경우, **THEN** 시스템은 다음 순서로 처리해야 한다:

1. `_exit_vip_closed_positions()` 호출 (REQ-VIP-REBAL-001)
2. 그래도 부족하면 `_rebalance_to_vip_weights()` 호출 (REQ-VIP-REBAL-002, 003, 004)
3. 위 2단계로 확보된 현금이 2차 매수 최소액을 충족하면 `_execute_vip_buy(split_sequence=2)` 재호출
4. 여전히 부족하면 기존과 동일하게 "VIP 잔여 현금 부족" 로그를 남기고 다음 주기를 기다린다

**규칙**:
- 리밸런싱 트리거는 펜딩 2차 매수 1건당 1회만 실행한다 (동일 주기 내 무한 루프 방지).
- 재시도 매수는 동일 `disclosure` 와 동일 `stock`을 대상으로 한다.
- 리밸런싱 매매는 모두 `try/except` 블록으로 감싸서 부분 실패가 전체를 중단시키지 않도록 한다.

### REQ-VIP-REBAL-006: 결정 가능한 우선순위와 안정성 (Ubiquitous)

시스템은 항상 동일 입력에 대해 동일 결과(deterministic)를 보장해야 한다:

- 종료 포지션 청산 순서: `stock_id` 오름차순
- 리밸런싱 대상 종목 처리 순서: `|current_weight - target_weight|` 큰 순 → 같으면 `stock_id` 오름차순
- 모든 가격은 단일 시점(현재가) 스냅샷을 사용 (각 종목별 시세 재조회 금지, 한 사이클 내 캐시)

### REQ-VIP-REBAL-007: 로깅 및 관측성 (Ubiquitous)

시스템은 항상 다음 정보를 구조화된 로그로 기록해야 한다:

- 리밸런싱 진입 시점: 펜딩 2차 매수 종목, 부족 현금 금액
- VIP 종료 포지션 청산: 종목 코드, 수량, 매도가, 확보 현금 누적치
- 비중 산출 결과: 각 종목의 `current_weight`, `target_weight`, `delta`
- 리밸런싱 매매: trim/buy 구분, 종목, 수량, 금액
- 최종 결과: 확보된 현금 합계, 2차 매수 재시도 성공/실패

각 로그는 INFO 레벨, "vip_rebal" 접두사를 포함한다.

### REQ-VIP-REBAL-008: 기존 매매 함수 재사용 (Unwanted)

시스템은 신규 매수/매도 로직을 작성해서는 안 된다. 모든 매매는 기존의 `_execute_vip_buy()` 와 `_execute_vip_sell()`을 호출해야 한다.

**WHY**: 기존 함수는 PnL 계산, `partial_sold` 플래그, `is_open` 플래그, `current_cash` 누적, DB 커밋을 일관되게 처리한다.
**IMPACT**: 중복 구현 시 PnL/현금 잔액 불일치, `is_open` 미갱신 등 데이터 정합성 사고가 발생한다.

### REQ-VIP-REBAL-009: 리밸런싱 비활성화 안전장치 (Optional)

**WHERE** 환경변수 `VIP_REBALANCE_ENABLED=false`가 설정된 경우, **THEN** 시스템은 모든 리밸런싱 동작을 건너뛰고 기존 SPEC-VIP-001 동작 (현금 부족 로그 후 종료)을 그대로 유지해야 한다.

**규칙**:
- 기본값은 `true` (활성화).
- 플래그 평가 시점: `check_second_buy_pending()` 진입 직후 1회.
- 운영 중 문제 발생 시 즉시 롤백 가능한 킬 스위치 역할.

### REQ-VIP-REBAL-010: 동시성 및 재진입 보호 (Unwanted)

시스템은 동일 `VIPPortfolio`에 대해 리밸런싱이 진행 중인 동안 또 다른 리밸런싱 호출이 시작되어서는 안 된다.

**규칙**:
- in-process 모듈 레벨 `asyncio.Lock` 또는 단순 boolean 플래그로 보호.
- 락 획득 실패 시 즉시 반환 (대기 금지).
- 락 보유 시간은 한 사이클(< 30초) 이내로 제한.

---

## Specifications

### 신규 함수 시그니처

`backend/app/services/vip_follow_trading.py`에 추가:

```
def _get_vip_target_weights(db: Session, portfolio_id: int) -> dict[int, float]:
    """
    REQ-VIP-REBAL-002 구현.
    Returns: {stock_id: target_weight} (Σ = 1.0)
    """

async def _exit_vip_closed_positions(db: Session, portfolio: VIPPortfolio) -> int:
    """
    REQ-VIP-REBAL-001 구현.
    가장 최근 disclosure_type이 reduce/below5인 종목의 모든 오픈 포지션 청산.
    Returns: 확보된 현금 합계 (KRW)
    """

async def _rebalance_to_vip_weights(db: Session, portfolio: VIPPortfolio) -> int:
    """
    REQ-VIP-REBAL-002, 003, 004 구현.
    VIP 비중과 현재 비중을 비교하여 임계치 초과분만 매매.
    Returns: 확보된 순현금 합계 (매도금액 - 매수금액, 음수 가능)
    """

async def _try_rebalance_for_second_buy(
    db: Session,
    portfolio: VIPPortfolio,
    target_stock_id: int,
    required_cash: int,
) -> bool:
    """
    REQ-VIP-REBAL-005 구현. _exit → _rebalance 순으로 시도.
    Returns: 확보된 현금이 required_cash 이상이면 True
    """
```

### 기존 함수 수정

`check_second_buy_pending(db: Session) -> int`:
- 가용 현금 < 필요 현금 분기에서 기존 "VIP 잔여 현금 부족" 로그 직전에 다음 추가:
  1. `VIP_REBALANCE_ENABLED` 플래그 체크 (False면 기존 동작 유지)
  2. `_try_rebalance_for_second_buy(db, portfolio, stock.id, required)` 호출
  3. True 반환 시 `_execute_vip_buy(..., split_sequence=2)` 재시도 후 결과 카운트
  4. False 반환 시 기존 로그를 남기고 다음 종목으로 진행

### 환경변수

| 변수명 | 기본값 | 설명 |
|--------|--------|------|
| `VIP_REBALANCE_ENABLED` | `true` | 리밸런싱 활성화 여부 (REQ-VIP-REBAL-009) |
| `VIP_REBALANCE_THRESHOLD` | `0.03` | 비중 차이 임계치 (REQ-VIP-REBAL-003) — 선택적 오버라이드 |

### 모듈 상수

```
REBALANCE_THRESHOLD: float = 0.03            # 3% 비중 차이
MIN_REBALANCE_POSITIONS: int = 2             # 단일 포지션 보호 (REQ-VIP-REBAL-004)
REBALANCE_LOG_PREFIX: str = "[vip_rebal]"
```

### 데이터 흐름

```
check_second_buy_pending()
    │
    ├─ 펜딩 2차 매수 후보 조회 (기존 로직)
    │
    ▼
[가용 현금 부족 감지]
    │
    ├─ VIP_REBALANCE_ENABLED 확인
    │
    ▼
_try_rebalance_for_second_buy()
    │
    ├─ Lock 획득
    │
    ├─ Step 1: _exit_vip_closed_positions()
    │       └─ disclosure_type ∈ {reduce, below5} 종목 전량 매도
    │
    ├─ Step 2: 부족하면 _rebalance_to_vip_weights()
    │       ├─ _get_vip_target_weights()
    │       ├─ 현재 비중 계산
    │       └─ |delta| > THRESHOLD 종목 trim/buy
    │
    ├─ Step 3: 확보 현금 ≥ required면 True
    │
    └─ Lock 해제
    │
    ▼
True → _execute_vip_buy(split_sequence=2) 재시도
False → 기존 "VIP 잔여 현금 부족" 로그
```

---

## Exclusions (What NOT to Build)

- Shall NOT modify the database schema or add Alembic migrations (이유: 기존 컬럼만 사용)
- Shall NOT add new REST API endpoints (이유: 내부 로직만 변경)
- Shall NOT change 1st-buy or 50% profit-lock logic (이유: 본 SPEC은 2차 매수 현금 부족 해결에 한정)
- Shall NOT add a new scheduler job (이유: 기존 60분 `check_second_buy_pending` 주기에서 동작)
- Shall NOT introduce a separate rebalancer service module (이유: 단일 파일 내 헬퍼 함수로 충분)
- Shall NOT call external pricing APIs other than `naver_finance.fetch_current_price` (이유: 일관된 시세 소스)
- Will NOT support frontend visualization in this SPEC (이유: 백엔드 동작 안정화 우선)
- Will NOT rebalance positions held for less than 1 trading day (구현 단순성과 잡음 매매 방지) — 본 SPEC은 적용 대상에서 제외하지만 향후 개선 후보
- Shall NOT trigger rebalancing outside Korean market hours (이유: 기존 스케줄 제약 그대로)

---

## Acceptance Criteria

상세 acceptance 시나리오는 `acceptance.md` 참조. 핵심 기준:

- **AC-VIP-REBAL-001**: 가용 현금 < 1주 매수액 상황에서 `disclosure_type='reduce'`인 보유 종목이 존재하면, 해당 종목의 모든 `is_open=True` `VIPTrade`가 `exit_reason='vip_rebalance_exit'`로 청산된다.
- **AC-VIP-REBAL-002**: 보유 4종목(stake_pct = 7%, 5%, 6%, 6%)일 때 목표 비중이 각각 약 0.292 / 0.208 / 0.250 / 0.250으로 정규화된다 (합계 1.0 ± 0.001).
- **AC-VIP-REBAL-003**: 어떤 종목의 현재 비중이 목표 비중보다 5% 초과 시 trim 매도가 발생하고, 5% 부족 시 buy가 발생하며, 1.5% 차이는 어떤 매매도 발생하지 않는다.
- **AC-VIP-REBAL-004**: 보유 종목이 1개일 때 리밸런싱 매도가 절대 실행되지 않는다 (`_rebalance_to_vip_weights`가 0을 반환하고 매매가 없음을 단위 테스트로 확인).
- **AC-VIP-REBAL-005**: 펜딩 2차 매수 트레이드 1건 + 부족 현금 372,519 + 청산 가능 종목 1개가 존재하는 통합 시나리오에서, 청산 → 재매수 → `VIPTrade(split_sequence=2)`가 새로 생성된다.
- **AC-VIP-REBAL-006**: 모든 보유 종목의 `stake_pct`가 `None`인 경우, 동일 가중치(1/N)가 적용되며 예외가 발생하지 않는다.
- **AC-VIP-REBAL-007**: 청산 가능 종목이 없고 비중 차이도 임계치 미만이면 `_try_rebalance_for_second_buy`가 `False`를 반환하고 2차 매수가 재시도되지 않는다.
- **AC-VIP-REBAL-008**: `VIP_REBALANCE_ENABLED=false`로 설정되면 어떤 리밸런싱 함수도 호출되지 않고 기존 로그만 출력된다.
- **AC-VIP-REBAL-009**: 동일 사이클 내 리밸런싱 함수가 중복 진입을 시도하면 두 번째 호출은 즉시 반환한다 (락 보호).
- **AC-VIP-REBAL-010**: `_execute_vip_sell` / `_execute_vip_buy` 외의 직접 매매 SQL이나 잔액 조작이 신규 코드에 존재하지 않음을 코드 리뷰로 확인한다.

### 엣지 케이스

| 케이스 | 기대 동작 |
|--------|-----------|
| `stake_pct = None` (일부 종목) | 다른 종목 평균값으로 대체 |
| `stake_pct = None` (전체) | 동일 가중치 1/N 적용 |
| 청산 가능 종목 없음 | Step 1 결과 0 → Step 2 진행 |
| 청산만으로 충분한 경우 | Step 2 진입하지 않음 (조기 종료) |
| 단일 포지션 포트폴리오 | 모든 리밸런싱 매도 차단 |
| 시세 조회 실패 (1종목) | 해당 종목은 건너뛰고 나머지 진행, 경고 로그 |
| 모든 시세 조회 실패 | 리밸런싱 중단, False 반환, 기존 "현금 부족" 로그 |
| 락 획득 실패 | 즉시 False 반환, 다음 60분 주기 대기 |
| 매도 후 매수 시 현금 일시 부족 | 가능한 수량까지만 매수, 잔여는 다음 사이클 |

---

## Traceability

- **SPEC ID**: SPEC-VIP-REBAL-001
- **상위 SPEC**: SPEC-VIP-001 (VIP투자자문 지분 추종 자동매매)
- **수정 파일**: `backend/app/services/vip_follow_trading.py`
- **재사용 함수**: `_execute_vip_buy`, `_execute_vip_sell`, `naver_finance.fetch_current_price`
- **참조 모델**: `VIPPortfolio`, `VIPTrade`, `VIPDisclosure` (스키마 변경 없음)
- **테스트**: `backend/tests/test_vip_follow_trading.py` (확장)
- **상위 도메인**: 자동매매 / 포트폴리오 리밸런싱 / 자본 효율화
