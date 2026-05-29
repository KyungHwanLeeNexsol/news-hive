---
id: SPEC-AI-023
version: 0.1.0
status: planned
created: 2026-05-29
updated: 2026-05-29
author: MoAI
priority: High
issue_number: 0
title: 상한가 근접 종목 익일 carry-forward 시그널 (Near-Limit-Up Carry-Forward Signal)
---

# SPEC-AI-023: 상한가 근접 종목 익일 carry-forward 시그널

## HISTORY

- 2026-05-29 (v0.1.0): 초안 작성. 2026-05-29 KST 라이브 사례 — LG씨엔에스(064400, +29.91%)와 같이 상한가(+30%)에 1tick 미달한 강한 모멘텀 종목이 익일 시그널을 받지 못하는 사각지대를 보완하기 위한 backend-only SPEC. 기존 carry-over(전일 시그널 decay 재발행) 메커니즘과 직교(orthogonal)하며, 시그널 이력과 무관하게 **종가 등락률 그 자체**로 익일 후보를 식별한다.

---

## Overview

기존 `_carry_over_strong_signals` 메커니즘은 "전일에 surge_candidate 시그널을 받았던 종목"의 confidence를 decay하여 재발행하는 방식이다. 그러나 다음 시나리오는 커버되지 않는다:

- 당일 시그널이 전혀 발행되지 않았으나 (예: 뉴스/공시 부재로 모든 탐지기 침묵)
- 종가 기준 +25% ~ +29.99% 의 강한 모멘텀을 기록한 종목 (상한가 미달)

이런 종목은 매수 잔량이 익일로 이월되어 추가 상승 가능성이 통계적으로 높으나, 현재 시스템은 익일 매수 후보에 자동 포함시키지 않는다.

본 SPEC은 매일 장 종료 후 (15:30 KST 이후) `_run_coverage_expansion`과 동일한 try/except 격리 패턴으로 실행되는 **신규 탐지기 1개**를 도입하여, 종가 등락률 기반으로 익일 surge_candidate 시그널을 생성한다.

### Problem Background (2026-05-29 KST 실제 사례)

| 종목 | 코드 | 당일 종가 등락 | 비고 |
|------|------|----------------|------|
| LG씨엔에스 | 064400 | +29.91% | 상한가 1tick 미달, 매수 물량 잔존 |
| (예시) | — | +25.0% ~ +29.99% | 동일 패턴 |

전일 시그널이 있는 종목은 `_carry_over_strong_signals`가 처리하지만, 위 종목들은 당일 시그널이 없으면 익일 후보로 등록되지 않는다.

### Root Cause

`surge_candidate` 탐지 파이프라인은 뉴스+공시+거래량+선행 패턴의 결합 신호에 의존한다. 종가 등락률 그 자체는 입력 신호로 사용되지 않으므로, **뉴스/공시 부재 + 강한 종가 모멘텀** 조합은 어떤 탐지기도 발동시키지 않는다.

### 설계 원칙

- **가법적 확장 (Additive)**: 기존 `surge_candidate` / `theme_propagation` / `volume_anomaly` 생성 로직을 변경하지 않는다.
- **기존 carry_over와 직교**: `_carry_over_strong_signals`가 이미 발행한 종목은 중복 생성하지 않는다.
- **try/except 격리**: `_run_coverage_expansion`과 동일 패턴으로 실행하여, 본 단계의 실패가 상위 파이프라인에 영향을 주지 않는다.
- **paper_executed 정책 미변경**: 신규 시그널의 `paper_executed` 기본값은 surge_candidate와 동일하게 `True`로 설정하여 매수 큐 진입을 허용한다 (SPEC-AI-022와 다름 — 본 SPEC은 즉시 매수 후보).
- **WHAT/WHY only**: 시그널 생성 조건과 confidence 공식만 정의. detector 함수의 내부 구현(쿼리 최적화, 캐시 전략)은 RUN 단계에서 결정.

### 전제 조건 (Assumptions)

- `fund_signals` 테이블은 `signal_type`, `confidence`, `surge_metadata`, `paper_executed` 컬럼을 보유한다 (SPEC-AI-004, SPEC-AI-012).
- `stocks` 테이블은 `id`, `stock_code`, `name`, `market_cap` 컬럼을 보유한다.
- `naver_finance.fetch_current_price_with_change_sync(code) -> dict | None`은 `{"current_price": int, "change_rate": float}`을 반환한다.
- `app.services.fund_manager._run_coverage_expansion`은 `run_surge_signal_generation` 내 surge_candidate persist 직후 호출된다.
- `surge_trading_service.get_today_signals`는 `signal_type='surge_candidate'`만 필터링하므로, 본 SPEC의 신규 시그널도 동일 `signal_type='surge_candidate'`로 발행되어 자동으로 익일 매수 큐에 포함된다.
- 본 SPEC은 새 DB 컬럼/마이그레이션을 추가하지 않는다.
- 외부 API(`naver_finance`) 호출 비용은 시총 상위 500종목 제한으로 관리한다.

---

## EARS Requirements

### REQ-AI023-001: 상한가 근접 종목 익일 carry-forward 시그널 생성

**WHERE** 시스템이 `run_surge_signal_generation()` 내 surge_candidate persist 및 `_run_coverage_expansion()` 완료 직후, the system SHALL `detect_near_limit_up_carries(db, config) -> int` 신규 탐지기를 호출하여 상한가 근접 종목에 대한 익일 surge_candidate 시그널을 생성한다.

**WHEN** 본 탐지기가 실행될 때, the system SHALL 다음 조건을 모두 충족하는 종목군을 식별한다:
- (a) 종목이 `stocks` 테이블에 존재하고 `market_cap >= 300` (억원, `NearLimitUpConfig.min_market_cap_eok` 기본값) 또는 `market_cap IS NULL` 허용
- (b) 종목 후보 집합이 `NearLimitUpConfig.max_candidates_per_day` (기본 `500`)을 초과할 경우 시가총액 내림차순 상위 N개로 절단
- (c) 종목의 당일 종가 등락률이 `NearLimitUpConfig.near_limit_up_min_pct` (기본 `25.0`) 이상 `29.99` 이하

**WHEN** 각 후보 종목의 당일 종가 등락률을 조회할 때, the system SHALL `fetch_current_price_with_change_sync(stock_code)`의 반환 dict에서 `change_rate` 필드를 읽어 사용한다.

**IF** 가격 조회가 None을 반환하거나 예외가 발생하면, **then** the system SHALL 해당 종목을 스킵하고 다음 종목 처리를 계속한다 (예외 전파 금지).

**WHERE** 다음 중 하나라도 해당하는 종목은, the system SHALL 신규 시그널 생성에서 제외한다 (중복 방지):
- (a) 동일 종목에 오늘 (KST 00:00:00 이후) 이미 `signal_type='surge_candidate'` 시그널이 존재 (기존 carry_over 또는 일반 surge_candidate가 이미 처리한 케이스)
- (b) 동일 종목에 오늘 `signal_type='theme_propagation'` 또는 `signal_type='volume_anomaly'` 시그널이 존재 (다른 커버리지 확장이 이미 처리)

**IF** 위 모든 조건 (REQ-AI023-001 a/b/c 충족 + 중복 부재 + 가격 조회 성공)을 만족하면, **then** the system SHALL 다음 값으로 신규 `FundSignal` 레코드를 생성한다:
- `signal_type = "surge_candidate"`
- `signal = "buy"`
- `confidence = round(change_rate / 30.0 * 0.5, 4)` (범위: 약 0.4167 ~ 0.4998)
- `reasoning = f"[SPEC-AI-023 상한가근접 carry] 당일 종가 +{change_rate:.2f}% — 상한가 미달 매수 잔량 carry-forward"`
- `paper_executed = True`
- `surge_metadata`(JSON 문자열): `{"surge_basis": ["near_limit_up_carry"], "yesterday_change_pct": round(change_rate, 2), "near_limit_up_carry": true}`
- 기타 필드 (`target_price`, `stop_loss`, `price_at_signal`, `news_summary`, `financial_summary`, `market_summary`, `disclosure_id`, `factor_scores`, `composite_score`, `ai_model`, `tp_sl_method`, `prompt_version`, `trend_alignment`, `volatility_level`): NULL 또는 기본값

**WHEN** 탐지기 실행이 완료될 때, the system SHALL 평가 종목 수, 가격 조회 실패 수, 생성된 시그널 수를 로깅한다 (`logger.info("[근접carry] 평가=%d 실패=%d 생성=%d", ...)`).

**WHERE** 본 단계는, the system SHALL `_run_coverage_expansion()` 내부 또는 그 직후의 별도 `try/except` 블록으로 격리되어 실행되며, 본 단계에서 발생한 예외는 surge_candidate, theme_propagation, volume_anomaly 시그널을 손상시키지 않는다.

`[NEW]` `backend/app/services/surge_detector.py` — `detect_near_limit_up_carries(db, config) -> int` 신규 함수 (생성된 시그널 수 반환)
`[MODIFY]` `backend/app/services/fund_manager.py` — `_run_coverage_expansion()` 내 volume_anomaly 호출 이후 `detect_near_limit_up_carries()` 호출 추가 (별도 try/except 블록)
`[NEW]` `backend/app/surge_config/surge_settings.py` — `NearLimitUpConfig(BaseModel)` 신규 Pydantic 클래스 추가

---

### REQ-AI023-002: NearLimitUpConfig 설정 클래스

**WHERE** 본 SPEC의 파라미터를 런타임에 조정할 수 있도록, the system SHALL `app.surge_config.surge_settings`에 다음 Pydantic 모델을 추가한다:

```python
class NearLimitUpConfig(BaseModel):
    """SPEC-AI-023: 상한가 근접 종목 익일 carry-forward 시그널 설정."""
    enabled: bool = True
    near_limit_up_min_pct: float = 25.0
    max_candidates_per_day: int = 500
    min_market_cap_eok: int = 300
```

**WHERE** `NearLimitUpConfig` 인스턴스는, the system SHALL `_run_coverage_expansion()` 내부에서 직접 instantiate하여 `detect_near_limit_up_carries(db, NearLimitUpConfig())` 형태로 호출한다 (SPEC-AI-022 `ThemePropagationConfig` / `VolumeAnomalyConfig`과 동일 패턴).

**WHERE** `SurgeDetectionConfig` 본체에는, the system SHALL `NearLimitUpConfig` 필드를 추가하지 않는다 — 본 SPEC의 config는 독립적으로 instantiate된다 (호출자가 직접 생성).

**IF** `NearLimitUpConfig.enabled == False`이면, **then** the system SHALL 탐지기를 호출하지 않고 즉시 0을 반환한다.

`[MODIFY]` `backend/app/surge_config/surge_settings.py` — `NearLimitUpConfig` 클래스 정의 (REQ-AI023-001과 동일 파일)

---

### REQ-AI023-003: 통합 지점 격리

**WHERE** `fund_manager._run_coverage_expansion()` 헬퍼는, the system SHALL 본 SPEC의 탐지기 호출을 다음 위치에 추가한다:

```
_run_coverage_expansion(db, surge_results)
├── try: propagate_theme_group_signals (기존)
├── try: detect_volume_anomaly_dormant_stocks (기존)
└── try: detect_near_limit_up_carries (신규)
```

**WHEN** 신규 try/except 블록이 실행될 때, the system SHALL:
- 실패 시 `logger.warning("[커버리지확장] 상한가근접 carry 실패 (다른 시그널 결과 보존됨): %s", e)` 로깅
- DB 세션 무결성을 위해 필요 시 `db.rollback()` 후에도 후속 코드(이 함수 종료) 진행
- 본 try 블록이 실패해도 이미 commit된 surge_candidate / theme_propagation / volume_anomaly 시그널은 보존된다

**WHERE** `detect_near_limit_up_carries()` 내부에서 단일 종목 처리가 실패하면, the system SHALL 해당 종목만 스킵하고 다음 종목을 계속 처리한다. 단일 종목의 DB add 실패 시에는 해당 row만 `db.rollback()` 후 다음으로 진행하며, 모든 종목 처리 완료 후 일괄 commit 또는 함수 종료 시점에 commit한다.

**WHERE** `db.commit()` 호출 위치는, the system SHALL 다음 중 한 가지 패턴을 따른다:
- (a) 함수 내 모든 시그널 add 완료 후 함수 종료 직전 한 번 commit
- (b) 각 종목 add 후 즉시 flush + commit (실패 시 rollback 후 다음 진행)

`[NO NEW FILE]` REQ-AI023-001/002의 파일 변경에 포함

---

## Acceptance Criteria

각 요구사항별 검증 가능한 인수 기준. 외부 의존성(DB, naver_finance API)은 mock으로 격리.

### AC-001: +27% 종목에 대해 surge_candidate 시그널 생성 (REQ-AI023-001)

**Given**:
- 종목 X가 stocks 테이블에 `market_cap=500`(억원)로 존재
- 종목 X에 당일 (KST 00:00:00 이후) 어떤 signal_type의 FundSignal도 부재
- `fetch_current_price_with_change_sync("X")` mock이 `{"current_price": 12700, "change_rate": 27.0}` 반환

**When**: `detect_near_limit_up_carries(db, NearLimitUpConfig())` 호출

**Then**:
- 종목 X에 대해 `signal_type="surge_candidate"`, `signal="buy"` 시그널 1건 생성
- `confidence == round(27.0 / 30.0 * 0.5, 4)` (대략 `0.45`)
- `surge_metadata` JSON 파싱 시 `surge_basis == ["near_limit_up_carry"]`, `yesterday_change_pct == 27.0`, `near_limit_up_carry == True` 포함
- `paper_executed == True`
- 함수 반환값 `>= 1`

### AC-002: +30% (상한가) 종목은 시그널 생성 안 함 (REQ-AI023-001)

**Given**:
- 종목 Y가 dormant 조건 충족하고 당일 시그널 부재
- `fetch_current_price_with_change_sync("Y")` mock이 `{"change_rate": 30.0}` 반환 (정확히 상한가)

**When**: `detect_near_limit_up_carries(db, NearLimitUpConfig())` 호출

**Then**:
- 종목 Y에 대해 시그널 생성 안 함 (범위 초과: `change_rate > 29.99`)

### AC-003: +20% 종목은 시그널 생성 안 함 (REQ-AI023-001)

**Given**:
- 종목 Z가 dormant 조건 충족하고 당일 시그널 부재
- `fetch_current_price_with_change_sync("Z")` mock이 `{"change_rate": 20.0}` 반환

**When**: `detect_near_limit_up_carries(db, NearLimitUpConfig())` 호출

**Then**:
- 종목 Z에 대해 시그널 생성 안 함 (`near_limit_up_min_pct=25.0` 미달)

### AC-004: 당일 surge_candidate 시그널이 이미 존재하면 중복 생성 안 함 (REQ-AI023-001)

**Given**:
- 종목 W가 +28%로 카운트 범위 내
- 종목 W에 당일 `signal_type="surge_candidate"` 시그널이 이미 존재 (carry_over 또는 일반 surge_candidate)

**When**: `detect_near_limit_up_carries(db, NearLimitUpConfig())` 호출

**Then**:
- 종목 W에 대해 시그널 생성 안 함 (중복 방지)
- 기존 시그널의 confidence/metadata 변경 없음

### AC-005: 당일 theme_propagation 또는 volume_anomaly 시그널이 존재하면 중복 생성 안 함 (REQ-AI023-001)

**Given**:
- 종목 V가 +29%로 범위 내
- 종목 V에 당일 `signal_type="theme_propagation"` 시그널 존재

**When**: `detect_near_limit_up_carries(db, NearLimitUpConfig())` 호출

**Then**:
- 종목 V에 대해 신규 시그널 생성 안 함

### AC-006: 가격 조회 실패 시 해당 종목 스킵, 다른 종목 계속 처리 (REQ-AI023-001)

**Given**:
- 종목 A, B 모두 후보 집합에 포함, 당일 시그널 부재
- `fetch_current_price_with_change_sync("A")` mock이 None 반환 (API 실패)
- `fetch_current_price_with_change_sync("B")` mock이 `{"change_rate": 26.5}` 반환

**When**: `detect_near_limit_up_carries(db, NearLimitUpConfig())` 호출

**Then**:
- 종목 A는 스킵 (시그널 미생성, 예외 미전파)
- 종목 B는 시그널 1건 생성 (`confidence ≈ 0.4417`)
- 함수 반환값 `== 1`

### AC-007: detect_near_limit_up_carries 예외 발생 시 다른 시그널 파이프라인 미영향 (REQ-AI023-003)

**Given**:
- `_run_coverage_expansion()` 진입 시 surge_candidate 시그널이 이미 DB에 commit됨
- `detect_near_limit_up_carries()` 내부에서 예외 발생 (예: DB 연결 끊김 mock)

**When**: `_run_coverage_expansion(db, surge_results)` 호출

**Then**:
- 함수가 예외를 raise하지 않고 정상 반환
- 기존 surge_candidate 시그널 row가 DB에 그대로 보존됨
- `logger.warning` 호출 발생 (메시지에 "상한가근접 carry 실패" 포함)
- propagate_theme_group_signals / detect_volume_anomaly_dormant_stocks 결과도 보존됨

### AC-008: enabled=False 시 탐지기 호출 없이 0 반환 (REQ-AI023-002)

**Given**: `NearLimitUpConfig(enabled=False)` 인스턴스

**When**: `detect_near_limit_up_carries(db, config)` 호출

**Then**:
- 즉시 0 반환
- `fetch_current_price_with_change_sync` 호출 0회 (mock assert)
- DB add 호출 0회

### AC-009: max_candidates_per_day 절단 적용 (REQ-AI023-001)

**Given**:
- stocks 테이블에 `market_cap >= 300`인 종목 1000개 존재
- `NearLimitUpConfig.max_candidates_per_day = 500`

**When**: `detect_near_limit_up_carries(db, config)` 호출

**Then**:
- `fetch_current_price_with_change_sync`는 최대 500회만 호출됨 (mock call count assert)
- 시가총액 내림차순 상위 500종목만 평가됨

### AC-010: confidence 공식 정확성 (REQ-AI023-001)

**Given**: 다양한 change_rate 입력에 대한 confidence 계산

**When**: 수식 `round(change_rate / 30.0 * 0.5, 4)` 적용

**Then**:
- `change_rate=25.0` → `confidence == 0.4167`
- `change_rate=28.0` → `confidence == 0.4667`
- `change_rate=29.0` → `confidence == 0.4833`
- `change_rate=29.99` → `confidence == 0.4998` (`< 0.5` 보장)

### AC-011: 기존 surge_candidate / theme_propagation / volume_anomaly 회귀 없음 (Cross-cutting)

**Given**: 기존 `run_surge_signal_generation()` 시나리오에 본 SPEC 적용

**When**: SPEC-AI-023 통합 후 `run_surge_signal_generation()` 호출

**Then**:
- 기존 surge_candidate row 수·내용·persist 순서 변경 없음
- 기존 theme_propagation / volume_anomaly row 수·내용 변경 없음
- 본 SPEC이 추가하는 신규 시그널은 `signal_type='surge_candidate'`이며 `surge_metadata.surge_basis == ["near_limit_up_carry"]`로 식별 가능

### AC-012: get_today_signals가 신규 시그널을 익일 매수 큐에 포함 (Cross-cutting)

**Given**:
- 본 SPEC의 시그널이 `confidence=0.45`, `signal_type="surge_candidate"`, `paper_executed=True`로 발행됨

**When**: 익일 09:05 KST `get_today_signals(db, min_probability=Decimal("0.30"))` 호출 — 단, "오늘"이 신호 생성 다음 거래일임을 가정

**Then**:
- (`min_probability=0.30` 통과 시) 본 시그널이 결과 list에 포함됨
- `surge_metadata.surge_basis == ["near_limit_up_carry"]`로 백테스트에서 식별 가능
- `get_today_signals` 코드는 변경 없이 자동 통과

---

## Implementation Notes

### 신규 함수 시그니처

```python
# backend/app/services/surge_detector.py
def detect_near_limit_up_carries(
    db: Session,
    config: "NearLimitUpConfig",  # noqa: F821 (지연 임포트)
) -> int:
    """SPEC-AI-023 REQ-001: 상한가 근접(+25% ~ +29.99%) 종목에 익일 surge_candidate 시그널 생성.

    Returns: 생성된 시그널 수
    """
```

### Pydantic 설정 클래스 (surge_settings.py)

```python
class NearLimitUpConfig(BaseModel):
    """SPEC-AI-023: 상한가 근접 종목 익일 carry-forward 시그널 설정."""
    enabled: bool = True
    near_limit_up_min_pct: float = 25.0
    max_candidates_per_day: int = 500
    min_market_cap_eok: int = 300
```

### fund_manager._run_coverage_expansion 통합 지점

```python
def _run_coverage_expansion(db: Session, surge_results: list[dict]) -> None:
    # ... 기존 try: propagate_theme_group_signals
    # ... 기존 try: detect_volume_anomaly_dormant_stocks

    try:
        from app.surge_config.surge_settings import NearLimitUpConfig
        from app.services.surge_detector import detect_near_limit_up_carries

        near_config = NearLimitUpConfig()
        near_count = detect_near_limit_up_carries(db, near_config)
        logger.info("[커버리지확장] 상한가근접 carry 시그널 %d개 생성", near_count)
    except Exception as e:
        logger.warning("[커버리지확장] 상한가근접 carry 실패 (다른 시그널 결과 보존됨): %s", e)
```

### @MX Tag 계획

- `detect_near_limit_up_carries()`: `@MX:NOTE` + `@MX:SPEC: SPEC-AI-023 REQ-001`. fan_in 예상 1 (`_run_coverage_expansion`에서만 호출).
- 만약 `naver_finance.fetch_current_price_with_change_sync` 호출 빈도가 일 500회를 초과하면 `@MX:WARN` + `@MX:REASON: rate-limited Naver API, 시총 상위 500 절단으로 관리`. 본 SPEC은 `@MX:WARN` 추가 권고 (REQ-AI023-001 (b)의 절단 로직 안전망).
- `NearLimitUpConfig`: `@MX:NOTE` + `@MX:SPEC: SPEC-AI-023 REQ-002`.

### 테스트 전략

- `backend/tests/test_near_limit_up_carry.py` (신규) — REQ-AI023-001 (AC-001 ~ AC-006, AC-008, AC-009, AC-010)
- `backend/tests/test_coverage_expansion_integration.py` (확장 또는 신규) — REQ-AI023-003 (AC-007), Cross-cutting (AC-011, AC-012)
- 외부 의존성 mock: `fetch_current_price_with_change_sync`을 `monkeypatch`로 대체 (기존 `_price_change_provider` 패턴 미적용 — 본 함수는 별도 비동기/동기 어댑터 없음 → 직접 패치)
- 목표 coverage: 신규 함수 90%+, 수정 파일 (`fund_manager.py`, `surge_settings.py`) 85%+

### 운영 고려사항

- **호출 시점**: `_run_coverage_expansion()`은 `run_surge_signal_generation()` 내부에서 호출되며, scheduler 기준 평일 15:20 KST. 본 SPEC의 탐지기는 15:30 (장 종료) 이후 데이터로 동작해야 의미가 있으므로 scheduler 시간이 15:30 이후로 조정되어 있는지 확인 필요. (현재 15:20 → 15:35 또는 16:00로 후속 조정 권장, 단 본 SPEC 범위 외).
- **API 호출 비용**: 시총 상위 500종목 × `fetch_current_price_with_change_sync` 500회 × 평균 200ms = 약 100초. 단 대다수 종목은 등락률 범위 밖이므로 캐시 효과 없음. naver_finance 레이트 리미트는 동기 호출로 충분히 흡수 가능 (`volume_anomaly`보다 적은 부하).
- **DB 부담**: 일 평균 신규 시그널 5~30건 예상 (강세장 기준). 기존 surge_candidate(68건/일) 대비 작음.
- **paper_executed=True 정책**: 본 SPEC의 시그널은 익일 매수 큐에 자동 진입한다 (SPEC-AI-022와 다름). 백테스트로 적중률 검증 후 정책 조정은 별도 SPEC.

---

## Exclusions (What NOT to Build)

- **`_carry_over_strong_signals` 로직 변경**: 기존 carry_over는 전일 시그널을 decay하여 재발행. 본 SPEC은 별도 탐지기로 독립 동작.
- **`fund_signals.near_limit_up_carry` 컬럼 추가**: 신규 컬럼 추가 금지. `surge_metadata` JSON 내 표기로 충분.
- **신규 마이그레이션 추가**: 본 SPEC은 DB 스키마 변경 없음.
- **상한가(+30%) 종목 처리**: 상한가는 익일 매도 압력 우세 가능성으로 본 SPEC에서 제외. 별도 정책 SPEC 필요.
- **익일 가격 검증/적중률 추적 로직**: `price_after_1d/3d/5d` 자동 채움은 본 SPEC 범위 외 (`signal_verifier` 등 기존 시스템에 위임).
- **신규 signal_type 도입**: `signal_type='surge_candidate'`를 그대로 사용. 새 enum 값 도입 금지.
- **target_price/stop_loss 자동 산정**: NULL로 발행. TP/SL은 매수 단계의 `surge_trading_service`에서 별도 산정.
- **`SurgeDetectionConfig`에 `near_limit_up` 필드 추가**: `NearLimitUpConfig`은 독립 instantiate. SurgeDetectionConfig 본체 변경 금지.
- **scheduler.py 호출 시간 변경**: 15:30 이후 실행 보장은 별도 작업. 본 SPEC은 함수 시그니처와 로직만 정의.
- **프론트엔드 변경**: backend-only SPEC. 새 시그널의 UI 표시는 surge_basis 필드를 기존 UI가 처리.
- **외부 알림 (이메일/슬랙) 발송**: 본 SPEC은 시그널 생성만. 알림은 기존 briefing 시스템에 위임.
- **상한가 근접 패턴의 ML 기반 적중률 학습**: 본 SPEC은 고정 confidence 공식 (`change_rate / 30 * 0.5`). 동적 학습은 후속 SPEC.
- **다중 거래일 모멘텀 분석 (예: 3일 연속 +20%)**: 본 SPEC은 단일 거래일 종가 등락률만 평가.
- **거래량 조건 추가**: 본 SPEC은 등락률만 기준. 거래량 조건은 `detect_volume_anomaly_dormant_stocks`에 위임.

---

## Delta Markers Summary

| Marker | File | Requirements |
|--------|------|--------------|
| `[NEW]` | `backend/app/services/surge_detector.py` (`detect_near_limit_up_carries` 함수 추가) | REQ-AI023-001 |
| `[MODIFY]` | `backend/app/services/fund_manager.py` (`_run_coverage_expansion`에 호출 추가) | REQ-AI023-001, REQ-AI023-003 |
| `[MODIFY]` | `backend/app/surge_config/surge_settings.py` (`NearLimitUpConfig` 클래스 추가) | REQ-AI023-002 |
| `[NEW]` | `backend/tests/test_near_limit_up_carry.py` | AC-001 ~ AC-006, AC-008 ~ AC-010 |
| `[NEW or MODIFY]` | `backend/tests/test_coverage_expansion_integration.py` | AC-007, AC-011, AC-012 |

---

## Related SPECs

- **SPEC-AI-012** (선행, 필수): 급등 징후 탐지 — `surge_candidate` signal_type과 `surge_metadata.surge_basis` 패턴의 reference.
- **SPEC-AI-013** (선행): 급등예측 모의투자 포트폴리오 — `surge_trading_service.get_today_signals`의 signal_type 필터 (본 SPEC의 신규 시그널이 자동 통과).
- **SPEC-AI-018** (선행): 시장 레짐 분류와 recent_surge_penalty — 본 SPEC은 페널티 미적용 (이미 +25% 이상으로 모멘텀 종목임을 명시).
- **SPEC-AI-022** (선행, 필수): 시그널 커버리지 확장 — `_run_coverage_expansion()` 통합 지점과 try/except 격리 패턴. 본 SPEC은 동일 패턴으로 3번째 탐지기를 추가.
- **SPEC-AI-021** (관련): 손절 후 회복 confidence_boost — surge_trading_service 단의 보정. 본 SPEC과 독립적으로 동작.
- **SPEC-AI-004** (관련): 공시 기반 시그널 — 다른 carry-forward 패턴(`disclosure_impact`) reference.

---

## Verification Checklist

- [ ] 모든 EARS 요구사항이 검증 가능한 인수 기준을 가진다 (AC-001 ~ AC-012)
- [ ] 신규 DB 마이그레이션 없음 확인 (스키마 무변경)
- [ ] 기존 `signal_type='surge_candidate'` 컬럼 의미 무변경 (필터 자동 통과)
- [ ] `surge_metadata` JSON 스키마에 `near_limit_up_carry`, `yesterday_change_pct` 키 추가만 (기존 키 변경 없음)
- [ ] `_run_coverage_expansion()` 내 별도 try/except 격리로 다른 시그널 회귀 방지
- [ ] mock 기반 격리 테스트로 외부 의존성(`fetch_current_price_with_change_sync`) 차단
- [ ] target coverage 85%+ 명시, 신규 함수 90%+
- [ ] @MX 태그 계획 포함 (NOTE / SPEC, 외부 API 호출 빈도 따라 WARN 권고)
- [ ] `paper_executed=True` 기본값 (익일 매수 큐 진입 허용)
- [ ] confidence 공식 검증 가능 (`round(change_rate / 30 * 0.5, 4)`, 범위 0.4167 ~ 0.4998)
- [ ] 상한가 (+30%) 종목 제외 보장 (`change_rate <= 29.99`)
- [ ] 중복 방지: 동일 종목에 당일 surge_candidate / theme_propagation / volume_anomaly 존재 시 스킵
