# SPEC-AI-021 Research: surge_trading_service.py 분석

생성일: 2026-05-29
대상 파일: `backend/app/services/surge_trading_service.py` (~1112 lines)
관련 모듈: `backend/app/services/fund_manager.py` (carry-over 로직), `backend/tests/test_surge_trading.py` (테스트 패턴)

---

## 1. 모듈 개요

`surge_trading_service.py`는 SPEC-AI-013에서 도입된 급등예측 모의투자 포트폴리오 서비스의 핵심 비즈니스 로직 모듈이다. FundSignal(`signal_type="surge_candidate"`)을 입력으로 받아 매수/매도/포지션 관리를 수행한다.

### 주요 상수 (L29-L33)

| 상수 | 값 | 용도 |
|------|-----|------|
| `MARKET_OPEN` | `time(9, 0)` | 정규장 시작 |
| `MARKET_CLOSE` | `time(15, 30)` | 정규장 종료 |
| `BUY_CUTOFF` | `time(11, 0)` | 신규 매수 마감 (1차 파동 후 추격 매수 차단) |
| `INTRADAY_CRASH_LIMIT` | `-3.0` | 전일비 -3% 이하: 테마 thesis 붕괴 매수 제외 |
| `INTRADAY_OVERHEAT_LIMIT` | `15.0` | 전일비 +15% 초과: 과열 매수 제외 |
| `MAX_SECTOR_PORTFOLIO_PCT` | `Decimal("0.40")` | 섹터 비중 최대 40% (env override 가능) |

---

## 2. 핵심 함수 분석

### 2.1 `get_today_signals(db, min_probability=0.30)` (L141-L245)

**역할**: 오늘 또는 직전 영업일 15:00 이후 생성된 surge_candidate 시그널을 필터링하여 매수 후보 리스트 반환.

**현재 필터 흐름**:
1. 직전 영업일 15:00 KST 이후 created_at 시그널만 포함 (L155-L186)
2. `surge_metadata.surge_probability_score < min_probability` 제외 (L190-L192)
3. **단일 탐지기 + probability < 0.30 제외** (L196-L204) — REQ-AI014-004
4. **5일 +15% 초과 (과열)** 제외 (L218-L226) — REQ-AI014-005
5. **1일 -5% 미만 (낙폭과대)** 제외 (L228-L236) — REQ-AI014-005

**반환**: `list[tuple[FundSignal, Stock, float]]` (L241). probability 내림차순 정렬.

**SPEC-AI-021 변경 지점**:
- 시그널 평가 루프 진입 전 `_get_recent_stop_loss_codes(db)` 1회 호출
- 각 시그널마다 `is_post_stop_loss`, `is_theme_cluster_only`, `has_carry_over` 계산
- `min_probability_effective` 동적 산출
- `effective_confidence = probability + boost_applied` 비교
- 결과 튜플을 3-튜플 → 4-튜플 확장 (recovery_context 추가)

### 2.2 `_parse_surge_metadata(surge_metadata)` (L262-L274)

surge_metadata JSON에서 `(probability, active_detectors)` 반환. `active_detectors`는 `surge_basis` 키의 list.

**관측된 basis 값**: `theme_cluster`, `volume_news_combo`, `immediate_disclosure`, `carry_over` (fund_manager.py L1483 확인).

SPEC-AI-021에서 활용: `set(active_detectors) == {"theme_cluster"}` 검사로 단일 basis 판정.

### 2.3 `_has_stop_loss_today(db)` (L353-L366)

오늘(KST) 손절 종료 포지션 존재 여부 단일 boolean 반환. is_buy_eligible_hours에서 11시 이후 재진입 허용 판정에 사용.

**SPEC-AI-021 관계**: 본 SPEC의 `_get_recent_stop_loss_codes(db, lookback_days=3)`는 다른 목적(종목 코드 집합 반환)을 가지며 기존 함수와 독립적으로 신규 추가한다.

### 2.4 `execute_buy_orders(db, ...)` (L491-L755)

**시그니처**:
```
def execute_buy_orders(
    db: Session,
    max_daily_entries: int = 6,
    max_open_positions: int = 7,
    position_pct: Decimal = Decimal("0.14"),
    min_probability: Decimal = Decimal("0.30"),
    max_same_sector: int = 2,
) -> dict
```

**호출 패턴**: `today_signals = get_today_signals(db, min_probability=min_probability)` (L516) → `for signal, stock, probability in today_signals:` (L554)

**SPEC-AI-021 변경**: tuple unpacking을 4-튜플로 변경 (`signal, stock, probability, recovery_context`). 매수 details에 recovery 관련 키 추가.

**주의**: 라이브 분석 정보(사용자 요구사항)에서 `max_open_positions=7, position_pct=0.14`로 적시되어 있으나, 함수 시그니처 default는 `max_daily_entries=6, max_open_positions=7, position_pct=0.14`이다. NewsHive 메모리에 따르면 `max_open_positions=7, position_pct=0.14` 정합. `max_daily_entries=5` 메모리 기록과 함수 default 6은 불일치하나, 실제 호출 측(스케줄러/라우터)에서 override되는 것으로 추정. 본 SPEC은 default를 변경하지 않는다.

### 2.5 `check_exit_conditions(db, stop_loss_pct, take_profit_pct, max_holding_days)` (L823-L919)

**시그니처**:
```
def check_exit_conditions(
    db: Session,
    stop_loss_pct: Decimal = Decimal("-0.05"),
    take_profit_pct: Decimal = Decimal("0.09"),
    max_holding_days: int = 3,
) -> dict
```

**현재 손절 분기** (L880-L881):
```
if Decimal(str(pnl_pct)) <= stop_loss_pct:
    exit_reason = "stop_loss"
```

단일 임계값. 보유 일수 무관.

**중요 관측**: 함수 default `stop_loss_pct=-0.05`이며 입력 요구사항의 "현재 ALL stops use -7%" 표현과 불일치. 실제 호출 측 스케줄러가 `stop_loss_pct=-0.07`로 override 가능성. 따라서 SPEC은 함수 시그니처 확장만 다루고 호출 측은 명시적으로 OUT OF SCOPE으로 설정한다.

**SPEC-AI-021 변경**:
- `same_day_stop_loss_pct: Optional[Decimal] = None`, `multi_day_stop_loss_pct: Optional[Decimal] = None` 추가
- `holding_days = calculate_trading_days_elapsed(trade.entry_date, today)` 계산
- 분기: 신규 인자 둘 다 제공 시 신규 로직, 부재 시 기존 단일 임계값
- 익절(take_profit_pct) 및 max_holding_days 로직은 보존

### 2.6 `calculate_trading_days_elapsed(entry_date, today)` (L758-L776)

평일 카운팅 헬퍼. 토/일 제외, 공휴일 무시. `entry_date` 다음 평일부터 카운트.

**활용 패턴**: REQ-AI021-003에서 `holding_days == 0`(당일 진입) 분기 판정에 사용.

---

## 3. carry-over 로직 (fund_manager.py)

### 3.1 `_gather_leading_candidates` carry-over 블록 (L1409-L1495)

**핵심 로직**:
- 전일(`yesterday_start = today_start - timedelta(days=1)`) surge_candidate 시그널 중 `confidence >= 0.28`인 항목 조회 (L1418-L1422)
- 오늘 동일 종목 시그널이 이미 있으면 skip (L1431-L1437)
- `decayed_score = round(original_conf * 0.95, 4)` (L1440), `< 0.265`이면 skip
- surge_metadata에 carry-over 메타 주입: `carry_over=True, decay_applied=0.05, original_date=...` (L1455-L1460)
- `active_detectors=["carry_over"]` 마킹 (L1483)

**Stop-Loss 종목 누락 메커니즘**:
1. 종목 A가 2026-05-28에 -5.22% 손절됨
2. 2026-05-29 새벽: 전일 시그널 confidence 검사 → 손절 자체는 시그널 조건이 아니므로 carry-over에는 자체로는 제외되지 않음 ⚠️
3. 그러나 fresh signal 생성 단계에서 stop_loss 정보는 confidence 계산에 영향 없음
4. 결과: 종목 A는 fresh theme_cluster 단일 basis 시그널만 받음 (combo 보너스 부재)
5. confidence ~0.25-0.27, `min_probability 0.30` 임계값 미달 → 매수 후보 탈락

**관측**: 실제 코드 상 stop_loss 종목이 carry-over에서 *직접* 제외되는 명시적 분기는 없으나, 입력 요구사항에 따르면 효과적으로 누락된다. 본 SPEC은 매수 단계에서 보정(confidence_boost + 임계값 완화)하는 접근을 택한다. carry-over 로직 자체 변경은 OUT OF SCOPE.

---

## 4. 테스트 패턴 (test_surge_trading.py)

### 4.1 헬퍼

- `_make_db()`: SQLAlchemy Session MagicMock
- `_make_portfolio(initial_capital, current_cash, portfolio_id)`: SurgePortfolio mock
- `_make_trade(stock_code, entry_price, quantity, entry_date, is_open, ...)`: SurgeTrade mock
- `_make_fund_signal(signal_id, stock_id, probability)`: FundSignal mock with surge_metadata JSON
- `_make_stock(stock_id, stock_code, name)`: Stock mock

### 4.2 클래스 패턴

`TestIsMarketHours`, `TestExecuteBuyOrders` 등 함수별 그룹. 메서드명 `test_characterize_*` (DDD 특성화 테스트) 또는 `test_spec_aiXXX_*` (SPEC 인수 테스트).

### 4.3 SPEC-AI-021 신규 테스트 파일 구조 제안

```
backend/tests/test_surge_trading_recovery.py

class TestGetRecentStopLossCodes:
    - test_returns_empty_when_no_stop_loss
    - test_returns_codes_within_lookback_window
    - test_excludes_codes_beyond_lookback_window
    - test_excludes_non_stop_loss_exits

class TestGetTodaySignalsRecoveryBoost:
    - test_post_stop_loss_boost_applied (AC-001)
    - test_no_history_no_boost (AC-002)
    - test_theme_cluster_only_threshold_relaxed (AC-003)
    - test_complex_basis_no_threshold_relax (AC-004)
    - test_carry_over_basis_excludes_relax (AC-005)
    - test_4_tuple_signature

class TestCheckExitConditionsHoldingDayBranches:
    - test_same_day_stop_loss_minus_5_pct (AC-006)
    - test_multi_day_stop_loss_minus_7_pct (AC-007)
    - test_legacy_single_pct_preserved (AC-008)

class TestExecuteBuyOrdersWithRecovery:
    - test_unpacks_4_tuple_correctly (AC-010)
    - test_details_includes_recovery_boost_fields
```

---

## 5. 의존성 및 위험 평가

### 5.1 변경 파급 범위

| 변경 함수 | 호출 측 | 영향 평가 |
|----------|---------|----------|
| `get_today_signals` (3→4 tuple) | `execute_buy_orders` (L516) | unpacking 동기 수정 필요 |
| `get_today_signals` (3→4 tuple) | 외부 caller (라우터 등) | 검색 필요. 단일 caller로 추정 |
| `check_exit_conditions` (시그니처 확장) | 스케줄러 (`surge_check_exits`), 라우터 | 신규 인자 default=None으로 하위 호환 |
| `_get_recent_stop_loss_codes` (신규) | 내부 only | 영향 없음 |

### 5.2 검증해야 할 가정

1. ✅ `surge_trades.exit_date` 컬럼 존재 — SurgeTrade 모델 import 확인 (L20)
2. ✅ `surge_trades.exit_reason` 컬럼 존재 — `_has_stop_loss_today` L362에서 활용 확인
3. ⚠️ `get_today_signals` 외부 caller 존재 여부 — 본 모듈 외 호출 grep 필요 (구현 시점에 확인)
4. ✅ `check_exit_conditions` `stop_loss_pct` default `-0.05` — L825에서 확인. 입력 요구사항의 "-7%" 표현과 불일치하나 호출 측 override 가정으로 해소

### 5.3 위험 요소

- **위험 H1**: `get_today_signals`의 외부 caller가 존재하면 4-튜플 변경 시 런타임 오류. 구현 전 grep으로 검증 필요.
- **위험 M1**: `recovery_context` dict access 패턴이 일관되지 않으면 KeyError 가능. TypedDict 사용 또는 dict.get() 패턴 강제.
- **위험 M2**: `_get_recent_stop_loss_codes`의 lookback_days=3은 calendar days 기준. 주말이 포함되면 영업일 기준 1일 ~ 2일 wide variance. 본 SPEC은 calendar days 기준 명시.
- **위험 L1**: 손절 직후 회복은 false-positive 발생 가능 (e.g., 단기 데드캣 바운스). +0.10 부스트는 conservative 휴리스틱이며 ML 기반 산출은 별도 SPEC.

---

## 6. 핵심 인사이트 요약

1. **현재 시스템은 stop_loss를 negative signal로 취급하지 않으며** carry-over에서도 직접 제외하지 않는다. 누락은 *간접적*으로 발생: 손절된 종목이 다음 영업일 fresh signal을 받을 때 carry-over 보너스 부재로 단일 basis 약신호로 평가된다.

2. **매수 단계 보정이 가장 안전한 개입 지점이다**. carry-over 로직(fund_manager.py)이나 surge_metadata 생성 단계(fund_manager 다른 부분)에 손대지 않고 `get_today_signals` 필터만 조정하면 됨.

3. **4-튜플 확장은 backward-compatible하지 않다** (caller 동기 수정 필요). 그러나 caller는 `execute_buy_orders` 단일로 추정되어 비용 낮음.

4. **`check_exit_conditions` 시그니처 확장은 backward-compatible** (신규 인자 None default). 안전한 변경.

5. **테스트 헬퍼는 이미 존재**하여 신규 테스트 작성 비용 낮음.

---

## 7. 구현 우선순위

1. **High**: `_get_recent_stop_loss_codes` 신규 헬퍼 (다른 모든 요구사항의 의존)
2. **High**: `get_today_signals` 4-튜플 확장 + 부스트/임계값 로직
3. **High**: `execute_buy_orders` unpacking 동기 수정 (필수: 미수정 시 ImportError 동급 런타임 오류)
4. **Medium**: `check_exit_conditions` 시그니처 확장 (독립적, 보유 기간 분기)
5. **Medium**: 테스트 작성 (AC-001 ~ AC-010)
6. **Low**: @MX 태그 보강 및 로그 메시지 정비

---

생성: manager-spec 분석 결과
참고: SPEC-AI-013, SPEC-AI-014, SPEC-AI-016 (호환 유지)
