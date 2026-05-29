---
id: SPEC-AI-021
version: 0.1.0
status: implemented
created: 2026-05-29
updated: 2026-05-29
author: MoAI
priority: High
issue_number: 0
title: 손절 후 회복 종목 시그널 누락 방지 (Post-Stop-Loss Recovery Signal Capture)
---

# SPEC-AI-021: 손절 후 회복 종목 시그널 누락 방지

## HISTORY

- 2026-05-29 (v0.1.0): 초안 작성. 2026-05-29 오전 09:02 KST 라이브 분석에서 LG전자(066570) 및 삼성에스디에스(018260) 두 최대 급등 종목이 `min_probability=0.30` 임계값 미만으로 매수 후보에서 탈락한 사건을 기반으로 한 backend-only 조정 SPEC. 손절 종목의 익일 신호 약화 패턴을 보정하기 위한 confidence_boost 및 threshold 동적 조정 로직을 정의한다.

---

## Overview

`surge_trading_service.py`의 현재 매수 파이프라인은 `min_probability=0.30` 단일 임계값으로 모든 시그널을 필터링한다. 그러나 직전 영업일에 손절(`stop_loss`)된 종목은 다음 영업일 carry-over 로직에서 제외(`fund_manager._gather_leading_candidates`)되어 신규 carry-over 시그널 없이 fresh signal만 받게 된다. 이때 fresh signal은 combo 점수나 즉시 공시 점수 누적이 없어 theme_cluster 단일 basis로 0.25~0.27 수준의 약한 신호로 평가되며, 결국 매수 임계값을 통과하지 못한 채 누락된다.

### Problem Background (2026-05-29 KST 실제 사례)

2026-05-29 09:02 KST 스케줄러가 총 54개 surge_candidate 시그널을 생성했으나, 당일 가장 큰 폭으로 급등한 두 종목이 매수에서 누락되었다:

| 종목 | 당일 시그널 conf | 필터 사유 | 전일 청산 사유 | 당일 종가 등락 |
|------|------------------|----------|----------------|----------------|
| LG전자 (066570) | 0.2576 | `< min_probability 0.30` | 2026-05-28 stop_loss (-5.22%) | **+18.85%** |
| 삼성에스디에스 (018260) | 0.2464 | `< min_probability 0.30` | 2026-05-28 stop_loss (-6.88%) | **+17.71%** |

당일 모든 매수 실행 시그널은 carry_over=True 종목으로만 구성되었고, fresh signal로 매수된 종목은 없었다. 손절된 두 종목은 carry-over 후보에서 제외된 채 약한 fresh signal만 받았고 0.30 임계값을 통과하지 못해 매수 큐에서 탈락했다. 결과적으로 시스템은 두 자릿수 급등을 두 건 놓쳤다.

### Root Cause Analysis

1. **Stop-loss carry_over 제외**: `_gather_leading_candidates`(`fund_manager.py` L1409-1495)는 전일 surge_candidate 시그널 중 `confidence >= 0.28`인 항목만 carry-over 대상으로 삼는다. stop_loss 된 종목은 보통 손절가가 -5%대로 청산되며, 다음날 fresh signal이 새로 생성될 때 carry-over 시그널과의 결합 보너스(combo bonus)를 받지 못한다.
2. **고정 min_probability 임계값**: 0.30은 "신규 약한 신호"와 "손절 후 구조적으로 강한 회복 종목"을 구분하지 못한다. 후자는 carry-over 보너스를 받지 못해 점수가 평가절하되지만 회복 모멘텀은 강하다.
3. **균일한 손절 임계값**: 현재 `check_exit_conditions(stop_loss_pct=Decimal("-0.05"))`는 보유 기간과 무관하게 -5%로 손절한다. (입력 요구사항의 "-7%" 표기는 호출 측 override 시 사용되는 max값을 참조한 것으로 해석한다.) 당일 손절(holding_days=0)과 다일 보유 후 손절(holding_days>=1)은 thesis 신뢰도가 다르며 동일 임계값을 사용하는 것은 thesis-failure 신호와 시간 가치 손실을 혼동시킨다.

본 SPEC은 위 3가지 근본 원인을 보정하는 4개의 backend-only 요구사항을 정의한다. DB 마이그레이션은 추가하지 않으며, 기존 `surge_trades` 테이블의 `is_open=False AND exit_reason='stop_loss' AND exit_date>=N`을 조회하여 기능을 구현한다.

### 전제 조건 (Assumptions)

- `surge_trades` 테이블은 `is_open: bool`, `exit_reason: str`, `exit_date: date`, `entry_date: date` 컬럼을 이미 보유한다 (SPEC-AI-013 마이그레이션).
- `get_today_signals(db, min_probability)`는 `list[tuple[FundSignal, Stock, float]]` 형태로 반환하며 호출자(`execute_buy_orders`)는 tuple unpacking으로 소비한다. 본 SPEC은 tuple 시그니처를 확장한다.
- `surge_metadata` JSON은 `surge_basis: list[str]` 필드를 포함하며 값은 `["theme_cluster"]`, `["volume_news_combo"]`, `["immediate_disclosure"]`, `["carry_over"]` 또는 이들의 조합으로 구성된다.
- 기존 API 계약(`POST /surge/execute`, `GET /surge/portfolio` 등)의 응답 스키마는 변경하지 않는다.

---

## EARS Requirements

### REQ-AI021-001: 손절 후 회복 confidence_boost

**WHERE** `get_today_signals(db, min_probability)`가 surge_candidate 시그널을 평가할 때, the system SHALL 해당 종목이 직전 3 영업일(calendar days 기준 3일) 이내에 `SurgeTrade(is_open=False, exit_reason='stop_loss')`로 청산된 이력이 있는지 검사한다.

**WHEN** 손절 이력이 발견되면, the system SHALL 해당 시그널의 평가용 confidence 점수에 `+0.10`의 `confidence_boost`를 가산한 값으로 `min_probability` 필터를 검사한다.

**IF** 부스트 적용 후 `effective_confidence = original_confidence + 0.10`이 `min_probability` 임계값(REQ-AI021-002 적용 후 값) 이상이면, **then** the system SHALL 해당 시그널을 매수 후보로 통과시킨다.

**WHEN** 부스트가 적용된 시그널을 결과 tuple에 추가할 때, the system SHALL `surge_probability_score` 필드(DB 저장값)는 원본 `original_confidence` 값을 유지하고, 부스트 정보(`boost_applied=0.10`, `boost_reason='post_stop_loss_recovery'`)는 로그 및 details JSON에만 기록한다.

**WHERE** 동일 종목이 3 영업일 이내 stop_loss 이력이 없거나 `is_open=True`(현재 보유 중)인 경우, the system SHALL 부스트를 적용하지 않는다.

`[MODIFY]` `backend/app/services/surge_trading_service.py` — `get_today_signals()` 시그니처 및 필터링 로직

---

### REQ-AI021-002: theme_cluster 단일 basis 임계값 완화

**WHERE** 시그널의 `surge_metadata.surge_basis`가 정확히 `["theme_cluster"]` 단일 값(volume_news_combo, immediate_disclosure, carry_over 모두 부재)일 때, AND **WHERE** 해당 종목이 REQ-AI021-001의 손절 후 회복 조건을 충족할 때, the system SHALL 해당 시그널에 한해 `min_probability` 임계값을 기본값 `0.30`에서 `0.25`로 완화한다.

**WHEN** 두 조건(theme_cluster 단일 basis AND post-stop-loss recovery) 중 하나라도 충족되지 않을 때, the system SHALL 기본 `min_probability` 임계값(0.30)을 그대로 적용한다.

**IF** 시그널이 임계값 완화 대상이면, **then** REQ-AI021-001의 confidence_boost와 본 요구사항의 임계값 완화는 동시에 적용된다. 즉 통과 조건은 `(original_confidence + 0.10) >= 0.25`이며 이는 `original_confidence >= 0.15`와 등가이다. 다만 REQ-AI021-002는 임계값 0.25에 부스트된 값을 비교하는 시맨틱을 유지한다.

**WHERE** 시그널에 carry_over basis가 포함된 경우, the system SHALL theme_cluster 단일 basis 조건을 충족하지 않는 것으로 판정하여 임계값 완화를 적용하지 않는다(carry-over 보너스를 이미 받고 있으므로).

**WHERE** 위 조건들의 적용은, the system SHALL `get_today_signals()` 내부에서 시그널별로 효과적 `min_probability_effective`를 계산하는 방식으로 수행한다.

`[MODIFY]` `backend/app/services/surge_trading_service.py` — `get_today_signals()` 필터 로직

---

### REQ-AI021-003: 손절 임계값 보유 기간 분기

**WHERE** `check_exit_conditions(db, stop_loss_pct, take_profit_pct, max_holding_days)`가 오픈 포지션의 손절 여부를 평가할 때, the system SHALL 해당 포지션의 보유 일수(`calculate_trading_days_elapsed(trade.entry_date, today)`)를 산출한다.

**IF** 보유 일수가 0일(`holding_days == 0`, 당일 진입 후 당일 손절 후보)이면, **then** the system SHALL `same_day_stop_loss_pct=-0.05` 임계값을 사용한다.

**IF** 보유 일수가 1일 이상(`holding_days >= 1`, 다일 보유 중)이면, **then** the system SHALL `multi_day_stop_loss_pct=-0.07` 임계값을 사용한다.

**WHEN** 손절 임계값을 적용할 때, the system SHALL `pnl_pct <= 적용_임계값`인 경우에만 `exit_reason='stop_loss'`로 매도를 트리거한다.

**WHERE** 기존 `stop_loss_pct` 인자는, the system SHALL 하위 호환성을 위해 함수 시그니처에 유지하되, 새 인자 `same_day_stop_loss_pct: Decimal = Decimal("-0.05")` 및 `multi_day_stop_loss_pct: Decimal = Decimal("-0.07")`을 기본값과 함께 추가한다. 신규 인자가 명시되면 신규 분기 로직을 사용하고, 신규 인자 모두 부재하고 기존 `stop_loss_pct`만 전달되면 기존 단일 임계값 동작을 유지한다.

**WHERE** 익절(`take_profit_pct`) 및 최대 보유 기간(`max_holding_days`) 분기 로직은, the system SHALL 변경하지 않는다.

`[MODIFY]` `backend/app/services/surge_trading_service.py` — `check_exit_conditions()` 시그니처 및 손절 분기 로직

---

### REQ-AI021-004: 손절 이력 조회 헬퍼 및 시그널 튜플 확장

**WHERE** REQ-AI021-001 및 REQ-AI021-002가 사용하는 손절 이력 정보는, the system SHALL `_get_recent_stop_loss_codes(db, lookback_days: int = 3) -> set[str]` 신규 내부 헬퍼를 통해 일괄 조회한다. 반환값은 `lookback_days` 이내 `exit_date`를 가진 `stop_loss` 청산 trade의 `stock_code` 집합이다.

**WHEN** `get_today_signals()`가 호출될 때, the system SHALL 시그널 평가 루프 진입 전에 `_get_recent_stop_loss_codes(db)`를 1회 호출하여 집합을 캐시하고, 각 시그널 평가 시 `stock.stock_code in cache` 형태로 O(1) 검사한다.

**WHEN** `get_today_signals()`가 시그널 tuple을 반환할 때, the system SHALL 기존 3-튜플 `(signal, stock, probability)`를 4-튜플 `(signal, stock, probability, recovery_context)`로 확장한다. `recovery_context`는 `{"is_post_stop_loss": bool, "boost_applied": float, "min_probability_effective": float, "boost_reason": str | None}` 구조의 dict이다.

**WHEN** `execute_buy_orders()`가 `get_today_signals()`의 반환을 unpacking할 때, the system SHALL 새 4-튜플 시그니처에 맞춰 `for signal, stock, probability, recovery_context in today_signals:` 형태로 변경한다.

**WHEN** `execute_buy_orders()`가 매수 결과 details에 항목을 추가할 때, the system SHALL `recovery_context.is_post_stop_loss=True`인 경우 `details` 항목에 `"recovery_boost": True, "boost_applied": 0.10, "min_probability_effective": 0.25` 필드를 추가하여 관측 가능성을 확보한다.

**WHERE** 외부 API 응답(`POST /surge/execute`)의 최상위 스키마는, the system SHALL 변경하지 않는다 (details 항목의 추가 키는 응답 통과). 라우터/스키마 모델 변경 없음.

`[MODIFY]` `backend/app/services/surge_trading_service.py` — `_get_recent_stop_loss_codes()` 신규 헬퍼, `get_today_signals()` 반환 시그니처 확장, `execute_buy_orders()` 튜플 unpacking 및 로그 보강

---

## Acceptance Criteria

각 요구사항별 검증 가능한 인수 기준. 모든 테스트는 `backend/tests/test_surge_trading_recovery.py`(신규 파일) 또는 기존 `test_surge_trading.py`에 추가한다. 외부 의존성(DB, 가격 API)은 mock으로 격리한다.

### AC-001: 손절 후 회복 부스트 적용 (REQ-AI021-001)

**Given** `SurgeTrade(stock_code="066570", is_open=False, exit_reason="stop_loss", exit_date=today-1)`이 DB에 존재하고
**When** `get_today_signals(db, min_probability=Decimal("0.30"))`이 호출되며 종목 066570에 대해 `surge_metadata={"surge_probability_score": 0.2576, "surge_basis": ["theme_cluster"]}`인 FundSignal이 있을 때
**Then** 결과 list에 066570 항목이 포함되고, `recovery_context.is_post_stop_loss == True`, `recovery_context.boost_applied == 0.10`이며, 매수 후보로 분류된다.

### AC-002: 손절 이력 부재 시 부스트 미적용 (REQ-AI021-001)

**Given** 종목 005930에 대한 stop_loss 이력이 lookback_days(3일) 내에 부재하고
**When** `get_today_signals(db, min_probability=Decimal("0.30"))`이 호출되며 005930에 대해 `surge_probability_score=0.2576`인 FundSignal이 있을 때
**Then** 결과 list에 005930은 포함되지 않는다 (0.2576 < 0.30이므로 탈락, 부스트 미적용).

### AC-003: theme_cluster 단일 basis + 손절 회복 동시 충족 시 임계값 0.25 적용 (REQ-AI021-002)

**Given** 종목 018260이 직전 1일 이내 stop_loss 청산되었고 시그널 `surge_basis=["theme_cluster"]`, `surge_probability_score=0.2464`일 때
**When** `get_today_signals(db, min_probability=Decimal("0.30"))`이 호출될 때
**Then** `recovery_context.min_probability_effective == 0.25`이고 `effective_confidence = 0.2464 + 0.10 = 0.3464 >= 0.25`이므로 매수 후보에 포함된다.

### AC-004: theme_cluster + volume_news_combo 복합 basis 시 임계값 완화 미적용 (REQ-AI021-002)

**Given** 종목 035720이 직전 1일 stop_loss 이력 보유, `surge_basis=["theme_cluster", "volume_news_combo"]`, `surge_probability_score=0.27`일 때
**When** `get_today_signals(db, min_probability=Decimal("0.30"))`이 호출될 때
**Then** `recovery_context.min_probability_effective == 0.30`(완화 미적용)이고 `effective_confidence = 0.27 + 0.10 = 0.37 >= 0.30`이므로 매수 후보에 포함된다.

### AC-005: carry_over basis 포함 시 임계값 완화 미적용 (REQ-AI021-002)

**Given** 종목 000660이 직전 1일 stop_loss 이력 보유, `surge_basis=["theme_cluster", "carry_over"]`, `surge_probability_score=0.21`일 때
**When** `get_today_signals(db, min_probability=Decimal("0.30"))`이 호출될 때
**Then** `recovery_context.min_probability_effective == 0.30`이고 `effective_confidence = 0.21 + 0.10 = 0.31 >= 0.30`으로 통과하지만, carry_over 보너스 보유로 임계값 완화 미적용임이 로그에 명시된다.

### AC-006: 당일 손절 임계값 -5% 적용 (REQ-AI021-003)

**Given** `SurgeTrade(stock_code="066570", entry_date=today, is_open=True, entry_price=100000)`이 있고 현재가가 95400(-4.60%)일 때
**When** `check_exit_conditions(db, same_day_stop_loss_pct=Decimal("-0.05"), multi_day_stop_loss_pct=Decimal("-0.07"))`이 호출될 때
**Then** 손절 트리거되지 않으며(`still_open` 카운트 +1).

**And Given** 동일 trade에서 현재가가 94900(-5.10%)일 때
**Then** `exit_reason='stop_loss'`로 매도 실행되고 `closed` 카운트 +1.

### AC-007: 다일 보유 손절 임계값 -7% 적용 (REQ-AI021-003)

**Given** `SurgeTrade(stock_code="018260", entry_date=today-2, is_open=True, entry_price=100000)`이 있고 현재가가 94000(-6.00%)일 때
**When** `check_exit_conditions(db, same_day_stop_loss_pct=Decimal("-0.05"), multi_day_stop_loss_pct=Decimal("-0.07"))`이 호출될 때
**Then** 손절 트리거되지 않는다.

**And Given** 현재가가 92900(-7.10%)일 때
**Then** `exit_reason='stop_loss'`로 매도 실행된다.

### AC-008: 신규 인자 부재 시 기존 동작 보존 (REQ-AI021-003 하위 호환성)

**Given** `SurgeTrade(stock_code="005930", entry_date=today-1, is_open=True, entry_price=100000)`이 있고 현재가 94000(-6.00%)일 때
**When** `check_exit_conditions(db, stop_loss_pct=Decimal("-0.05"))`만 명시하고 신규 인자를 전달하지 않을 때
**Then** 기존 단일 임계값 -5% 분기가 적용되어 손절 트리거된다 (테스트는 기존 동작이 깨지지 않음을 확인).

### AC-009: 손절 이력 헬퍼 정확성 (REQ-AI021-004)

**Given** DB에 (066570, exit_date=today-1, stop_loss), (018260, exit_date=today-2, stop_loss), (005930, exit_date=today-4, stop_loss), (000660, exit_date=today-1, take_profit) trade가 존재할 때
**When** `_get_recent_stop_loss_codes(db, lookback_days=3)`이 호출될 때
**Then** 반환값은 `{"066570", "018260"}` 정확히 일치한다 (today-4는 lookback 초과로 제외, take_profit은 stop_loss가 아님으로 제외).

### AC-010: execute_buy_orders 4-튜플 unpacking 정상 동작 (REQ-AI021-004)

**Given** `get_today_signals`가 mock으로 4-튜플 list를 반환하고 모든 다운스트림 필터(가격, 한도, 섹터, 현금)가 통과 가능 상태일 때
**When** `execute_buy_orders(db)`가 호출될 때
**Then** 매수 실행이 정상 완료되며 `details[i]`에 `recovery_boost: True, boost_applied: 0.10` 키가 존재(부스트 적용 종목에 한해), `executed >= 1`.

---

## Implementation Notes

### 수정 대상 함수 및 접근 방식

1. **`_get_recent_stop_loss_codes(db, lookback_days=3)`** (신규, surge_trading_service.py)
   - `today_kst - timedelta(days=lookback_days)` 이상 `exit_date`를 가진 `is_open=False, exit_reason='stop_loss'` trade를 조회
   - `SELECT DISTINCT stock_code FROM surge_trades WHERE ...` 형태로 단일 쿼리
   - 반환: `set[str]` (O(1) 검사용)

2. **`get_today_signals()` 수정** (surge_trading_service.py L141~)
   - 함수 진입 직후 `recent_stop_loss_codes = _get_recent_stop_loss_codes(db)` 호출
   - 시그널 평가 루프 내에서 각 시그널마다 다음 계산:
     - `is_post_stop_loss = stock.stock_code in recent_stop_loss_codes`
     - `_, active_detectors = _parse_surge_metadata(signal.surge_metadata)`
     - `is_theme_cluster_only = set(active_detectors) == {"theme_cluster"}`
     - `has_carry_over = "carry_over" in active_detectors`
     - `min_probability_effective = Decimal("0.25") if (is_post_stop_loss and is_theme_cluster_only and not has_carry_over) else min_probability`
     - `boost_applied = 0.10 if is_post_stop_loss else 0.0`
     - `effective_confidence = probability + boost_applied`
     - 필터: `if effective_confidence < float(min_probability_effective): continue`
   - 결과 tuple에 `recovery_context` 추가하여 4-튜플 반환

3. **`execute_buy_orders()` 수정** (surge_trading_service.py L491~)
   - `for signal, stock, probability in today_signals:` → `for signal, stock, probability, recovery_context in today_signals:`
   - 매수 실행 직후 `details` 항목 구성 시 `recovery_context.is_post_stop_loss` 분기로 보조 필드 추가
   - 부스트 적용 종목은 로그 라인에 `recovery_boost=True boost=0.10` 마커 추가 (REQ-AI016-002 [SURGE] 분해 로그와 양립)

4. **`check_exit_conditions()` 수정** (surge_trading_service.py L823~)
   - 시그니처 확장: 기존 `stop_loss_pct: Decimal = Decimal("-0.05")` 유지, 신규 `same_day_stop_loss_pct: Optional[Decimal] = None`, `multi_day_stop_loss_pct: Optional[Decimal] = None` 추가
   - 손절 분기 로직:
     ```
     holding_days = calculate_trading_days_elapsed(trade.entry_date, today)
     if same_day_stop_loss_pct is not None and multi_day_stop_loss_pct is not None:
         effective_stop = same_day_stop_loss_pct if holding_days == 0 else multi_day_stop_loss_pct
     else:
         effective_stop = stop_loss_pct
     if Decimal(str(pnl_pct)) <= effective_stop:
         exit_reason = "stop_loss"
     ```
   - 호출 측(스케줄러 등)에서 신규 인자 전달은 별도 PR/SPEC으로 처리 (본 SPEC은 함수 변경만 포함)

### Pydantic v2 및 타입 힌트

- 신규 헬퍼 `_get_recent_stop_loss_codes`는 type hints 필수: `def _get_recent_stop_loss_codes(db: Session, lookback_days: int = 3) -> set[str]:`
- `recovery_context`는 단순 `dict[str, Any]`로 처리 (TypedDict 선언은 선택). 호출 측에서는 dict access 패턴 사용.

### @MX Tag 계획

- `get_today_signals()`: 기존 `@MX:NOTE` 추가 — `# @MX:NOTE: SPEC-AI-021 손절 후 회복 종목 부스트 및 임계값 동적 조정`
- `_get_recent_stop_loss_codes()`: 신규 함수 `@MX:NOTE` + `@MX:SPEC: SPEC-AI-021 REQ-004` 추가
- `check_exit_conditions()`: 기존 `@MX:ANCHOR` 유지 (fan_in >= 3), 시그니처 변경 후 `@MX:NOTE` 추가하여 신규 분기 설명

### 테스트 전략

- 테이블 기반 테스트(`@pytest.mark.parametrize`) 활용: 손절 이력 유무 × surge_basis 조합 × confidence 값 매트릭스
- 기존 `test_surge_trading.py` 헬퍼 (`_make_db`, `_make_portfolio`, `_make_trade`, `_make_fund_signal`, `_make_stock`) 재사용
- 신규 테스트 파일: `backend/tests/test_surge_trading_recovery.py` (가독성)
- 목표 coverage: SPEC-AI-021 신규/수정 함수에 대해 90%+, 전체 모듈 85%+ 유지

---

## Exclusions (What NOT to Build)

- **DB 마이그레이션 추가**: 기존 `surge_trades` 테이블의 `is_open`, `exit_reason`, `exit_date`, `entry_date` 컬럼만으로 충분. 신규 컬럼 추가 금지.
- **`fund_manager._gather_leading_candidates`의 stop_loss 제외 규칙 변경**: carry-over 로직 자체는 본 SPEC 범위 외. 본 SPEC은 매수 단계에서 보정한다.
- **min_probability 임계값 0.30의 전역 변경**: 본 SPEC은 시그널별 조건부 완화(0.25)만 정의. 전역 default 변경 금지.
- **confidence_boost 값 ML/통계 기반 동적 산출**: +0.10은 라이브 사례(LG전자/삼성에스디에스) 기반 휴리스틱 상수. ML 기반 산출은 별도 SPEC.
- **lookback_days 동적 조정**: 3 calendar days로 고정. configuration 외부화는 별도 SPEC.
- **외부 API 응답 스키마 변경**: `POST /surge/execute` 응답의 details 키 추가는 backward-compatible (기존 클라이언트 무영향). 라우터/Pydantic schema 변경 금지.
- **`check_exit_conditions` 호출 측(스케줄러/라우터)에 신규 인자 주입**: 본 SPEC은 함수 시그니처 확장만 포함. 호출 측 wiring은 별도 후속 작업.
- **다른 exit_reason(take_profit, max_holding_period)에 대한 분기**: 본 SPEC은 stop_loss에 한정.
- **익절 임계값 보유 기간 분기**: 명시적 제외 (`take_profit_pct`는 단일 임계값 유지).
- **프론트엔드 변경**: backend-only SPEC. UI 영향 없음.

---

## Delta Markers Summary

| Marker | File | Requirements |
|--------|------|--------------|
| `[MODIFY]` | `backend/app/services/surge_trading_service.py` | REQ-AI021-001, 002, 003, 004 |
| `[NEW]` | `backend/tests/test_surge_trading_recovery.py` | AC-001 ~ AC-010 검증 |
| `[MODIFY]` | `backend/tests/test_surge_trading.py` | check_exit_conditions 하위 호환성 회귀 테스트 추가 (AC-008) |

---

## Related SPECs

- **SPEC-AI-013** (선행): 급등예측 모의투자 포트폴리오 서비스 — `surge_trading_service.py` 베이스 라인.
- **SPEC-AI-014** (선행): 가격 모멘텀 사전 필터 — `get_today_signals()`의 5일/1일 변화율 필터 보존.
- **SPEC-AI-016** (선행): 탐지기별 분해 로그 및 섹터 비중 가드 — 매수 로그 포맷 호환 유지.
- **SPEC-AI-018** (병렬): 시장 레짐 분류 — 본 SPEC과 독립. 임계값 완화는 레짐과 무관하게 적용.

---

## Verification Checklist

- [ ] 모든 EARS 요구사항이 검증 가능한 인수 기준을 가진다 (AC-001 ~ AC-010)
- [ ] DB 마이그레이션 추가 없음 확인
- [ ] 기존 API 응답 스키마 변경 없음 확인
- [ ] `check_exit_conditions` 하위 호환성(기존 단일 인자) 회귀 테스트 포함
- [ ] mock 기반 격리 테스트로 외부 의존성(가격 API, DB) 차단
- [ ] target coverage 85%+ 명시
- [ ] @MX 태그 계획 포함
