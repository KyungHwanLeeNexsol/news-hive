---
id: SPEC-AI-035
version: 0.1.0
status: draft
created: 2026-06-02
updated: 2026-06-02
author: MoAI
priority: Medium
issue_number: 0
title: 장중 실시간 그룹 cascade 감지 (Intraday Real-Time Group Cascade Detection)
---

# SPEC-AI-035: 장중 실시간 그룹 cascade 감지

## HISTORY

- 2026-06-02 (v0.1.0): 초안 작성. SPEC-AI-027 그룹 cascade 탐지기는 15:20 KST 장 마감 배치에서만 동작하므로, 대장주(anchor)가 이미 당일 상승을 끝낸 시점에 계열사 cascade 시그널을 발행한다. 결과적으로 당일(same-day) 계열사 동반 상승 구간을 놓친다. 본 SPEC은 장중(09:30~11:00 KST) 실시간으로 대장주 등락률을 점검하여, 아직 당일 시그널이 없는 계열사에 `surge_candidate` 시그널을 즉시 발행함으로써 당일 매수 실행(`surge_execute_buys` 30분 간격)에 곧바로 활용되도록 한다. 근거: 6/2 데이터에서 삼성에스디에스 +15% 등 그룹 cascade 패턴이 당일 시차 상승으로 실현(삼성전자 강세 → 삼성 계열사 동반). backend-only SPEC. 신규 마이그레이션 없음.

---

## Overview

현행 그룹 cascade 탐지기(`detect_group_cascade_signals`, SPEC-AI-027)는 **15:20 KST 장 마감 배치**(`_run_surge_signal_generate` → `_run_coverage_expansion`)에서만 실행된다. 이 시점에는 대장주가 **이미 당일 상승을 완료**한 상태이므로, 발행된 cascade 시그널은 **익일(next-day)** 매수 큐에만 사용된다. 그러나 한국 시장에서 대장주 급등에 따른 계열사 동반 상승은 **같은 날 30~60분 내**에 발생하는 경우가 빈번하다(예: 삼성전자 10:00 +5% → 삼성전기·삼성SDS 동반). 따라서 당일 cascade 기회가 구조적으로 누락된다.

본 SPEC은 **장중에 주기적으로(09:30, 10:00, 10:30, 11:00 KST) 실행되는 신규 탐지기** `detect_intraday_cascade(db, config)`를 추가한다. 각 `ThemeGroup`의 대장주(`anchor_stock`) 당일 등락률을 시세 조회(`_fetch_price_change_sync`)로 점검하여, 등락률이 트리거 임계값 이상이면 **당일 아직 시그널이 없는** 계열사(`StockThemeGroup` 멤버)에 `signal_type="surge_candidate"`, `surge_basis=["group_cascade_intraday"]` 시그널을 즉시 발행한다. 발행된 시그널은 `created_at`이 현재 시각이므로 `surge_trading_service.get_today_signals()`가 곧바로 인식하고, 30분 주기 `surge_execute_buys`가 당일 매수를 실행한다.

### Problem Background

| 시나리오 | 기존(15:20 배치) 처리 | 본 SPEC(장중) 처리 |
|---|---|---|
| 삼성전자 10:00 +5.2%, 삼성전기·삼성SDS 신호 부재 | 15:20에야 cascade 발행 → 익일 매수. 당일 동반 상승(예: 삼성SDS +15%) 구간 누락 | 10:00 잡이 anchor +5.2% 감지 → 삼성전기·삼성SDS에 즉시 cascade 발행 → 30분 내 당일 매수 |
| LG 대장주 09:30 +6%, 계열사 다수 | 익일 진입만 가능 | 09:30 잡이 즉시 cascade 발행 → 당일 1차 파동 진입 |
| anchor가 11:00 이후 +5% 도달 | 익일 진입 | BUY_CUTOFF(11:00) 이후이므로 신규 cascade 발행 안 함(추격 매수 차단 정책 유지) |

### Root Cause

- SPEC-AI-027 cascade 탐지기는 `_run_coverage_expansion(db, surge_results)` 내부에서만 호출되며, 이 함수는 **15:20 배치 단 1회** 실행된다.
- cascade 입력 `surge_results`는 당일 장 데이터가 확정된 후 `_gather_surge_candidates()`로 산출되므로, 장중 실시간 anchor 등락률을 반영할 수 없다.
- `surge_execute_buys`는 09:00~15:30 사이 30분 간격으로 이미 동작하지만, **읽을 당일 cascade 시그널이 장중에 존재하지 않아** 그룹 cascade 매수가 익일로 지연된다.
- `ThemeGroup.anchor_stock_id` / `StockThemeGroup`(SPEC-AI-027 인프라)는 그룹-계열사 관계를 명시적으로 보유하므로, 접두사 매칭 없이 장중 실시간 cascade 식별에 직접 활용 가능하다.

### 설계 원칙 (Design Principles)

- **가법적 확장 (Additive)**: SPEC-AI-027 `detect_group_cascade_signals()`(15:20 배치) 및 기존 6개 탐지기 로직 변경 절대 금지. 본 SPEC은 **독립된 장중 탐지기**(`detect_intraday_cascade`)와 **신규 스케줄러 잡 4개**만 추가한다.
- **신규 signal_type 도입 금지**: `signal_type="surge_candidate"`를 그대로 사용. 식별은 `surge_metadata.surge_basis=["group_cascade_intraday"]`로 수행. 따라서 `get_today_signals`의 `signal_type='surge_candidate'` 필터를 자동 통과한다.
- **신규 마이그레이션 없음**: `ThemeGroup`, `StockThemeGroup`, `Stock`, `FundSignal` 기존 컬럼만 사용. DB 스키마 무변경.
- **장중 한정 실행**: `is_buy_eligible_hours()` 윈도(09:00~11:00 KST) 내에서만 신규 cascade 발행. BUY_CUTOFF(11:00) 이후 추격 매수 차단 정책과 일관.
- **당일 동일 시그널 재발행 금지**: 계열사가 당일 이미 임의 signal_type 시그널을 보유하면 스킵(중복 발행 방지).
- **over-signaling 방지**: anchor당 30분 내 1회로 발행을 제한하고, ThemeGroup당 하루 최대 2건으로 cascade 상한 설정.
- **WHAT/WHY only**: 시그널 발행 조건과 가드만 정의. 시세 조회 캐싱, 쿼리 최적화, 스케줄러 등록 세부 코드는 RUN 단계에서 결정.

### 전제 조건 (Assumptions)

- `theme_groups` 테이블은 `id`, `name`, `anchor_stock_id`(nullable) 컬럼과 `anchor_stock`/`stocks` 관계를 보유한다(SPEC-AI-022/027).
- `stock_theme_groups` 테이블은 `stock_id`, `theme_group_id`, `weight` 컬럼을 보유한다(SPEC-AI-022/027).
- `stocks` 테이블은 `id`, `name`, `stock_code`, `market_cap` 컬럼을 보유한다.
- `fund_signals` 테이블은 `signal_type`, `signal`, `confidence`, `reasoning`, `surge_metadata`, `paper_executed`, `stock_id`, `created_at` 컬럼을 보유한다(SPEC-AI-004/012/013/027).
- `_fetch_price_change_sync(stock_code) -> dict | None`는 당일 등락률을 동기 조회하며, 테스트에서는 `_price_change_provider` 주입으로 모킹 가능하다(SPEC-AI-014). 반환 dict는 등락률 필드(`change_rate` 또는 동등 키)를 포함한다.
- `surge_trading_service.is_buy_eligible_hours(now, db)`는 평일(공휴일 제외) 09:00~11:00 신규 매수 가능 시간을 판정한다(MARKET_OPEN=09:00, BUY_CUTOFF=11:00).
- `surge_trading_service.is_market_hours(now)`는 평일(공휴일 제외) 09:00~15:30 정규장 시간을 판정한다.
- `surge_trading_service.get_today_signals(db, min_probability)`는 `signal_type='surge_candidate'` 시그널을 직전 영업일 15:00 이후 `created_at` 기준으로 조회하므로, **당일 장중에 발행된** cascade 시그널을 즉시 포함한다.
- `surge_execute_buys` 잡은 평일 09:00~15:30 KST 30분 간격(`minute="0,30"`)으로 `execute_buy_orders(db)`를 호출하므로, 장중 cascade 발행 후 최대 30분 내 당일 매수가 시도된다.
- `surge_trading_service.execute_buy_orders`는 현재 보유 포지션(open positions)을 조회 가능하다(anchor 보유 가드용).
- 본 SPEC은 새 DB 컬럼/마이그레이션을 추가하지 않는다.

---

## EARS Requirements

### REQ-AI035-001: 장중 cascade 탐지기 진입 및 시간 가드

**WHERE** 시스템이 장중 cascade 탐지를 수행할 때, the system SHALL `backend/app/services/surge_detector.py`에 신규 함수 `detect_intraday_cascade(db: Session, config: "IntradayCascadeConfig") -> list[FundSignal]`를 제공한다.

**IF** `IntradayCascadeConfig.enabled == False`이면, **then** the system SHALL 즉시 빈 리스트를 반환하고 DB 변경(add/commit)을 수행하지 않는다.

**IF** 호출 시점이 `is_buy_eligible_hours()` 윈도(평일 09:00~11:00 KST, 공휴일 제외) 밖이면, **then** the system SHALL 신규 cascade 시그널을 발행하지 않고 빈 리스트를 반환한다.

**IF** `is_market_hours()`가 False(휴장/장외)이면, **then** the system SHALL 시세 조회를 신뢰할 수 없는 것으로 간주하여 cascade 발행을 스킵한다(stale change_rate 가드).

`[NEW]` `backend/app/services/surge_detector.py` — `detect_intraday_cascade(db, config) -> list[FundSignal]` 신규 함수

---

### REQ-AI035-002: 대장주(anchor) 장중 급등 조건 판정

**WHEN** 탐지기가 실행될 때, the system SHALL 모든 `ThemeGroup`을 순회하며 `anchor_stock_id`가 NULL이 아닌 그룹에 대해 대장주 종목코드를 확보한다.

**WHEN** 대장주 종목코드가 확보될 때, the system SHALL `_fetch_price_change_sync(anchor_stock_code)`로 당일 등락률(`change_rate`)을 조회한다.

**IF** 시세 조회 결과가 None 이거나 등락률 필드를 추출할 수 없으면, **then** the system SHALL 해당 그룹의 cascade 발행을 스킵하고 다음 그룹 처리를 계속한다(예외 전파 금지).

**WHEN** 대장주 등락률이 `IntradayCascadeConfig.trigger_pct`(기본 5.0%) 이상일 때, the system SHALL 해당 그룹을 cascade 발행 대상으로 식별한다.

**IF** 대장주 등락률이 `trigger_pct` 미만이면, **then** the system SHALL 해당 그룹의 cascade 발행을 스킵한다.

`[NO NEW FILE]` REQ-AI035-001 함수 내부에 포함

---

### REQ-AI035-003: 계열사 후보 식별 및 시그널 생성

**WHEN** 그룹이 cascade 발행 대상으로 식별될 때, the system SHALL `StockThemeGroup`을 통해 동일 `theme_group_id`에 속하되 대장주 자신을 제외한 계열사 목록을 조회한다.

**WHEN** 계열사 후보가 확정되고 가드(REQ-AI035-004)를 통과할 때, the system SHALL 각 후보에 대해 다음 값으로 신규 `FundSignal` 레코드를 생성한다:
- `signal_type = "surge_candidate"`
- `signal = "buy"`
- `confidence` = 대장주 등락률 강도에서 도출한 `surge_probability_score`(REQ-AI035-005 공식)
- `reasoning = f"[SPEC-AI-035 장중캐스케이드] 대장주 {anchor_name}({anchor_code}) {change_rate:.2f}% 장중 급등 → 계열사 동반 기대"`
- `paper_executed = True` (당일 매수 큐 자동 포함)
- `surge_metadata`(JSON 문자열): `{"surge_basis": ["group_cascade_intraday"], "anchor_stock_code": anchor_code, "anchor_change_rate": round(change_rate, 4), "theme_group_id": group_id, "surge_probability_score": confidence, "detected_at_kst": <ISO-8601 KST>}`
- 기타 필드(`target_price`, `stop_loss`, `price_at_signal`, `news_summary`, `financial_summary`, `market_summary`, `disclosure_id`, `factor_scores`, `composite_score`, `ai_model`, `tp_sl_method`, `prompt_version`, `trend_alignment`, `volatility_level`): NULL 또는 기본값

**WHEN** `created_at`이 설정될 때, the system SHALL 현재 KST 시각(또는 동등한 UTC 변환값)을 사용하여 `get_today_signals()`가 당일 시그널로 즉시 인식하도록 한다.

**WHEN** 탐지기 실행이 완료될 때, the system SHALL 점검한 그룹 수, 트리거된 그룹 수, 생성된 시그널 수를 로깅한다(`logger.info("[intraday_cascade] groups=%d triggered=%d 생성=%d", ...)`).

`[NO NEW FILE]` REQ-AI035-001 함수 내부에 포함

---

### REQ-AI035-004: 가드 조건 (Guard Conditions)

**IF** 대장주가 이미 현재 보유 포지션(open position)에 존재하면, **then** the system SHALL 해당 그룹의 cascade 발행을 스킵한다(이미 진입한 그룹 추가 발행 금지).

**IF** 계열사 후보가 당일(KST 00:00 이후) 이미 임의의 `signal_type` 시그널을 보유하면, **then** the system SHALL 해당 후보에 대한 cascade 시그널 생성을 스킵한다(중복 발행 방지).

**IF** 동일 대장주가 직전 발행 이후 `IntradayCascadeConfig.anchor_cooldown_minutes`(기본 30분) 이내이면, **then** the system SHALL 해당 대장주 기준 cascade 재발행을 스킵한다(over-signaling 방지).

**WHEN** 단일 그룹에 대해 cascade 시그널을 생성할 때, the system SHALL 당일 동일 `theme_group_id` 기준 누적 발행 건수가 `IntradayCascadeConfig.max_per_group_per_day`(기본 2건)를 초과하지 않도록 제한한다.

**WHERE** 단일 그룹·계열사 처리 중 예외가 발생하면, the system SHALL 해당 항목만 `db.rollback()` 후 스킵하고 다음 항목 처리를 계속한다(상위 잡으로 예외 전파 금지).

`[NO NEW FILE]` REQ-AI035-001 함수 내부에 포함

---

### REQ-AI035-005: 설정 클래스 및 confidence 도출

**WHERE** 장중 cascade 동작이 구성될 때, the system SHALL `backend/app/surge_config/surge_settings.py`에 신규 Pydantic 클래스 `IntradayCascadeConfig(BaseModel)`를 추가하며, 다음 기본값을 가진다:
- `enabled: bool = True`
- `trigger_pct: float = 5.0` — 대장주 장중 등락률 트리거 임계값(%)
- `check_hours: list[float] = [9.5, 10.0, 10.5, 11.0]` — 점검 시각(KST, 소수 시간 표기)
- `anchor_cooldown_minutes: int = 30` — anchor당 최소 재발행 간격(분)
- `max_per_group_per_day: int = 2` — ThemeGroup당 일일 최대 cascade 건수

**WHEN** 계열사 시그널 confidence(=`surge_probability_score`)를 산출할 때, the system SHALL 대장주 등락률 강도에 비례하는 결정론적(deterministic) 공식을 적용하되, 결과값을 `[0.0, 1.0]` 범위로 클램프한다. RUN 단계에서 확정할 기준 공식(예: `round(min(1.0, change_rate / 10.0), 4)`)을 사용한다(예: change_rate 5.0% → 0.50, 10.0% → 1.00).

**WHERE** `IntradayCascadeConfig`은 독립적으로 instantiate되며, the system SHALL `SurgeDetectionConfig` 또는 `GroupCascadeConfig` 본체에 필드를 추가하지 않는다.

`[MODIFY]` `backend/app/surge_config/surge_settings.py` — `IntradayCascadeConfig(BaseModel)` 신규 클래스 추가

---

### REQ-AI035-006: 스케줄러 잡 등록

**WHERE** `scheduler.py`의 잡 등록 구간(`start_scheduler` 또는 동등 함수)은, the system SHALL 장중 cascade 점검 잡을 평일(`day_of_week="mon-fri"`) 09:30, 10:00, 10:30, 11:00 KST(`hour="9-11"`, `minute="0,30"` 또는 `check_hours` 매핑)에 실행되도록 등록한다.

**WHEN** 각 잡이 트리거될 때, the system SHALL 신규 래퍼(예: `_run_intraday_cascade`)에서 DB 세션을 열어 `detect_intraday_cascade(db, IntradayCascadeConfig())`를 호출하고, 실패 시 `logger.error("[intraday_cascade] 잡 실패: %s", e)` 로깅 후 정상 종료한다(잡 예외가 스케줄러를 중단시키지 않음).

**IF** 잡 실행 시점이 주말/공휴일이거나 `is_buy_eligible_hours()` 밖이면, **then** the system SHALL REQ-AI035-001 시간 가드에 의해 빈 결과로 즉시 반환한다(무해한 no-op).

**WHERE** 잡 등록은 `max_instances=1`, `coalesce=True`, `replace_existing=True`, `timezone="Asia/Seoul"`로 설정하여, the system SHALL 기존 surge 잡(`surge_execute_buys` 등)과 동일한 안정성 규약을 따른다.

`[MODIFY]` `backend/app/services/scheduler.py` — `_run_intraday_cascade` 래퍼 + 잡 등록 추가

---

## Implementation Scope

| Marker | File | Requirements |
|--------|------|--------------|
| `[NEW]` | `backend/app/services/surge_detector.py` (`detect_intraday_cascade` 함수 추가) | REQ-AI035-001, 002, 003, 004 |
| `[MODIFY]` | `backend/app/surge_config/surge_settings.py` (`IntradayCascadeConfig` 클래스 추가) | REQ-AI035-005 |
| `[MODIFY]` | `backend/app/services/scheduler.py` (`_run_intraday_cascade` 래퍼 + 09:30/10:00/10:30/11:00 잡 등록) | REQ-AI035-006 |
| `[NEW]` | `backend/tests/test_intraday_cascade.py` | AC-001 ~ AC-010 |

### 신규 함수 시그니처 (참고)

```python
# backend/app/services/surge_detector.py
def detect_intraday_cascade(
    db: Session,
    config: "IntradayCascadeConfig",  # noqa: F821 (지연 임포트)
) -> list[FundSignal]:
    """SPEC-AI-035: 장중(09:30~11:00 KST) 실시간 그룹 cascade 탐지.

    각 ThemeGroup의 anchor 당일 등락률을 _fetch_price_change_sync로 점검하여
    trigger_pct 이상이면 당일 시그널 없는 계열사에 surge_candidate를 즉시 발행한다.
    surge_basis=["group_cascade_intraday"], paper_executed=True, created_at=현재 KST.

    Returns: 생성된 FundSignal 목록
    """
```

### 신규 Pydantic 설정 클래스 (참고)

```python
class IntradayCascadeConfig(BaseModel):
    """SPEC-AI-035: 장중 실시간 그룹 cascade 감지 설정."""
    enabled: bool = True
    trigger_pct: float = 5.0                          # 대장주 장중 등락률 트리거 (%)
    check_hours: list[float] = [9.5, 10.0, 10.5, 11.0]  # 점검 시각 (KST)
    anchor_cooldown_minutes: int = 30                 # anchor당 최소 재발행 간격 (분)
    max_per_group_per_day: int = 2                    # ThemeGroup당 일일 최대 cascade 건수
```

### 스케줄러 잡 등록 (참고)

```python
# backend/app/services/scheduler.py — start_scheduler 내부
# SPEC-AI-035: 장중 실시간 그룹 cascade 점검 (평일 09:30/10:00/10:30/11:00 KST)
scheduler.add_job(
    _run_intraday_cascade,
    "cron",
    day_of_week="mon-fri",
    hour="9-11",
    minute="0,30",
    timezone="Asia/Seoul",
    id="intraday_cascade",
    max_instances=1,
    coalesce=True,
    replace_existing=True,
)
```

(`hour="9-11", minute="0,30"`은 09:00/09:30/10:00/10:30/11:00을 포함하며, 09:00은 `is_buy_eligible_hours` 통과 시 무해한 추가 점검이다. RUN 단계에서 `check_hours`와 정확히 매핑하는 별도 트리거 구성 가능.)

### @MX Tag 계획

- `detect_intraday_cascade()`: `@MX:ANCHOR` + `@MX:REASON: scheduler 4개 잡에서 호출(fan_in >= 3), ThemeGroup 순회 + anchor 시세 조회 + FundSignal 발행 포함` + `@MX:SPEC: SPEC-AI-035 REQ-001`.
- `IntradayCascadeConfig`: `@MX:NOTE` + `@MX:SPEC: SPEC-AI-035 REQ-005`.
- anchor 시세 동기 조회 루프가 ThemeGroup 수에 비례하여 외부 API를 호출하면 `@MX:WARN` + `@MX:REASON: 그룹 수 × 시세 조회 — Naver API rate limit 위험` 권고(RUN 단계 호출 빈도/캐싱 검토).

---

## Acceptance Criteria

각 요구사항별 검증 가능한 인수 기준. 외부 의존성(DB, 시세 조회, 시각)은 in-memory SQLite + `_price_change_provider` 주입 + `now` 인자 주입으로 격리한다.

| AC | 시나리오 | 기대 결과 | REQ |
|----|----------|-----------|-----|
| AC-001 | 10:00 KST, ThemeGroup "삼성그룹"(anchor=삼성전자) change_rate=5.2%(>=5.0), 계열사 삼성전기·삼성SDS 당일 신호 부재 | 삼성전기/삼성SDS 각각 1건 surge_candidate 생성. surge_basis=["group_cascade_intraday"], anchor_stock_code=삼성전자 코드, paper_executed=True, signal="buy" | REQ-002, 003 |
| AC-002 | anchor change_rate=4.5%(<5.0) | cascade 0건, DB add 0회 | REQ-002 |
| AC-003 | `_fetch_price_change_sync`가 None 반환(시세 조회 실패) | 해당 그룹 스킵, 예외 없음, 다음 그룹 처리 계속 | REQ-002 |
| AC-004 | 호출 시각 11:30 KST(`is_buy_eligible_hours` 밖) | 즉시 빈 리스트, DB add 0회 | REQ-001 |
| AC-005 | `IntradayCascadeConfig(enabled=False)` | 즉시 빈 리스트, DB add 0회 | REQ-001 |
| AC-006 | anchor change_rate=6%, 계열사 "삼성SDS"에 당일 이미 surge_candidate 시그널 존재 | 삼성SDS 스킵(중복 미생성), 기존 시그널 변경 없음 | REQ-004 |
| AC-007 | anchor 삼성전자가 이미 open position 보유 | "삼성그룹" cascade 스킵(0건) | REQ-004 |
| AC-008 | 동일 anchor가 10:00 발행 후 10:30 재점검(cooldown 30분 이내) | 10:30 재발행 스킵 | REQ-004 |
| AC-009 | anchor change_rate=7%, 계열사 5개 후보, max_per_group_per_day=2 | 해당 그룹 당일 누적 2건까지만 생성 | REQ-004 |
| AC-010 | change_rate=10.0% → confidence 산출 | surge_probability_score == round(min(1.0, 10.0/10.0), 4) == 1.0; change_rate=5.0% → 0.50 ([0,1] 클램프) | REQ-005 |

### AC 상세 — AC-001 (대표 케이스)

**Given**:
- `theme_groups`: "삼성그룹"(anchor_stock_id → 삼성전자 id)
- `stock_theme_groups`: 삼성전자, 삼성전기, 삼성SDS가 "삼성그룹"에 매핑
- `_price_change_provider`: 삼성전자 종목코드 → `{"change_rate": 5.2, ...}` 반환
- 삼성전기/삼성SDS에 당일 임의 signal_type 시그널 부재
- 삼성전자가 open position에 부재
- 호출 시각 `now = 10:00 KST`(평일, `is_buy_eligible_hours()` 통과)
- `IntradayCascadeConfig()` 기본값

**When**: `detect_intraday_cascade(db, IntradayCascadeConfig())` 호출(시각/시세 주입)

**Then**:
- 삼성전기/삼성SDS 각각 surge_candidate 시그널 1건(총 2건) 생성
- 각 `surge_metadata` 파싱 시 `surge_basis == ["group_cascade_intraday"]`, `anchor_stock_code == 삼성전자 코드`, `anchor_change_rate == 5.2`
- 각 `paper_executed == True`, `signal == "buy"`, `signal_type == "surge_candidate"`
- 각 `confidence == round(min(1.0, 5.2/10.0), 4) == 0.52`
- 함수 반환 리스트 길이 == 2
- 직후 `get_today_signals(db)` 호출 시 두 시그널이 포함됨(당일 즉시 인식)

---

## Non-Goals (Exclusions — What NOT to Build)

- **SPEC-AI-027 배치 cascade(`detect_group_cascade_signals`) 변경**: 15:20 배치 탐지기 및 접두사 매칭 로직 무변경. 본 SPEC은 ThemeGroup/StockThemeGroup 명시 관계만 사용하는 **독립 장중 탐지기**를 추가한다.
- **기존 6개 탐지기 / `_run_coverage_expansion` 변경**: surge_candidate / theme_propagation / volume_anomaly / near_limit_up_carry / insider_purchase / executive_disclosure / forum_mention_surge 어느 것도 수정하지 않는다.
- **신규 마이그레이션 / DB 스키마 변경**: `theme_groups`, `stock_theme_groups`, `stocks`, `fund_signals` 컬럼 추가 금지. `surge_metadata` JSON 표기로 충분.
- **신규 signal_type 도입**: `signal_type='surge_candidate'`를 그대로 사용. 새 enum 값(`group_cascade_intraday` 등) 도입 금지(식별은 `surge_basis`로).
- **실시간 틱/웹소켓 스트리밍 연동**: `_fetch_price_change_sync` 동기 폴링만 사용. 실시간 체결 스트림 연동은 별도 SPEC.
- **종목코드 / 그룹 하드코딩**: anchor·계열사를 코드에 직접 박지 않는다. `ThemeGroup.anchor_stock_id` 및 `StockThemeGroup` 관계만 사용.
- **접두사 매칭 fallback**: 본 SPEC은 명시적 ThemeGroup 관계에 의존한다. 접두사 매칭(SPEC-AI-027)은 본 장중 경로에 포함하지 않는다.
- **confidence 동적 학습**: 고정 결정론적 공식. 적중률 기반 동적 조정은 후속 SPEC.
- **target_price / stop_loss 자동 산정**: NULL로 발행. TP/SL은 매수 단계 `surge_trading_service`에서 별도 산정.
- **매수 실행 로직 변경**: `execute_buy_orders` / `surge_execute_buys` 잡 변경 금지. 본 SPEC은 시그널을 당일 생성만 하고, 기존 30분 주기 매수 잡이 이를 소비한다.
- **BUY_CUTOFF(11:00) 이후 신규 cascade 발행**: 추격 매수 차단 정책 유지. 11:00 이후는 발행하지 않는다.
- **프론트엔드 변경**: backend-only SPEC. 신규 시그널의 UI 표시는 기존 `surge_basis` 처리 로직에 위임.
- **외부 알림(이메일/슬랙) 발송**: 시그널 생성만. 알림은 기존 briefing 시스템에 위임.

---

## Related SPECs

- **SPEC-AI-027** (선행, 필수): 대기업 그룹 계열사 테마캐리 탐지기 — `detect_group_cascade_signals()`(15:20 배치), `GroupCascadeConfig`, `surge_basis` 식별 패턴, `theme_groups`/`stock_theme_groups` 인프라를 제공. 본 SPEC은 동일 cascade 개념을 **장중 실시간**으로 보완하며, 명시적 ThemeGroup 관계를 사용한다.
- **SPEC-AI-012** (선행, 필수): 급등 징후 탐지 — `surge_candidate` signal_type 및 `surge_metadata.surge_basis`/`surge_probability_score` 패턴 reference.
- **SPEC-AI-013** (선행, 필수): 급등예측 모의투자 포트폴리오 — `get_today_signals`(signal_type 필터, 당일 시그널 인식), `execute_buy_orders`(open position 조회, surge_probability_score 정렬), `surge_execute_buys` 30분 주기 잡 및 `is_buy_eligible_hours`/`is_market_hours`/`BUY_CUTOFF` 시간 가드를 제공.
- **SPEC-AI-014** (선행): 가격 변동 조회 — `_fetch_price_change_sync` 동기 시세 어댑터 및 `_price_change_provider` 테스트 주입 reference.

---

## Verification Checklist

- [ ] 모든 EARS 요구사항이 검증 가능한 인수 기준을 가진다(AC-001 ~ AC-010)
- [ ] 신규 DB 마이그레이션 없음 확인(스키마 무변경)
- [ ] 기존 `signal_type='surge_candidate'` 의미 무변경(`get_today_signals` 필터 자동 통과)
- [ ] `surge_metadata` JSON에 `group_cascade_intraday` surge_basis 키 추가만(기존 키 변경 없음)
- [ ] SPEC-AI-027 배치 cascade 및 기존 6개 탐지기 회귀 없음(독립 함수 + 독립 잡)
- [ ] 시간 가드: `is_buy_eligible_hours()`(09:00~11:00) 밖 / `is_market_hours()` False 시 no-op
- [ ] anchor 보유 포지션 가드(이미 진입한 그룹 스킵)
- [ ] 당일 임의 signal_type 보유 계열사 스킵(중복 발행 방지)
- [ ] anchor cooldown(기본 30분) 재발행 제한
- [ ] ThemeGroup당 일일 cascade 상한(기본 2건) 제한
- [ ] confidence 공식 검증 가능([0,1] 클램프, change_rate 비례)
- [ ] `created_at`이 현재 KST → `get_today_signals` 당일 즉시 인식
- [ ] 종목코드/그룹 하드코딩 부재 확인(ThemeGroup/StockThemeGroup 관계만 사용)
- [ ] 스케줄러 잡 4개(09:30/10:00/10:30/11:00) 등록, `max_instances=1`/`coalesce=True`/`replace_existing=True`/`timezone="Asia/Seoul"`
- [ ] 잡/그룹/계열사 단위 예외 격리(상위 스케줄러로 예외 전파 금지)
- [ ] in-memory DB + 시세/시각 주입 기반 격리 테스트로 외부 의존성 차단
- [ ] target coverage 85%+ 명시, 신규 함수 90%+
- [ ] @MX 태그 계획 포함(ANCHOR / NOTE / SPEC, 시세 조회 빈도에 따라 WARN 권고)
