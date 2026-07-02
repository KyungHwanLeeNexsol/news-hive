---
id: SPEC-AI-024
version: 0.2.0
status: implemented
created: 2026-05-29
updated: 2026-07-02
author: MoAI
priority: High
issue_number: 0
title: 임원 자사주 직접 매수 공시 강화 탐지 (Insider Direct Purchase Disclosure Enhancement)
---

# SPEC-AI-024: 임원 자사주 직접 매수 공시 강화 탐지

## HISTORY

- 2026-05-29 (v0.1.0): 초안 작성. 기존 `detect_immediate_disclosure_signal()`이 처리하는 일반 DART 공시(회사 단위 자기주식 취득/소각/계약/합병)와는 별개로, **임원 개인이 자사주를 매수**한 보고서를 별도 신호로 분리 가중치화. backend-only SPEC. `_run_coverage_expansion()`의 4번째 try/except 블록으로 추가하며 SPEC-AI-023과 동일한 격리·신호 패턴을 따른다.
- 2026-07-02 (v0.2.0, DDD 버그픽스): `detect_insider_purchase_signals()` 구현이 본 SPEC 요구사항과 불일치하던 6건 수정 — (1) `surge_metadata`/`FundSignal.disclosure_id` 추적성 필드 미설정 수정, (2) `reasoning` 접두사 `"[SPEC-AI-024 임원자사주매수]"` 추가, (3) 음성 키워드에 `"매각"`,`"감소"` 추가, (4) `report_type`/`report_name`의 ㆍ(U+318D)·중간점(·) 표기 변형(c-2) 매칭 로직 신설, (5) 양성 매칭을 `ilike("%임원%취득%")` 순서 고정 조건에서 "임원" AND ("취득" OR "매수") 순서 무관 조건으로 정정, (6) 종목당 1건 dedup 기준을 `Disclosure.created_at.desc()` 정렬 기반 "가장 최근 공시" 우선으로 정정. 함수명(`detect_insider_purchase_signals`, 복수형)은 호출부 breaking change 방지를 위해 변경하지 않음(spec.md 표기 오차로 간주). status: planned → implemented.

---

## Overview

기존 `detect_immediate_disclosure_signal()`(`backend/app/services/surge_detector.py` line 788)은 회사 차원의 DART 공시(자기주식 소각/취득결정, 단일판매 공급계약, 합병 결정)를 `_IMMEDIATE_EVENT_PATTERNS` 키워드 매칭으로 처리한다. 그러나 **임원(또는 주요주주)이 개인 자금으로 자사주를 매수한 공시**는 별개의 보고서(`"임원ㆍ주요주주특정증권등소유상황보고서"`)로 제출되며 회사 단위 공시와 의미가 다르다.

임원의 자사주 매수는 다음 이유로 별개의 강한 매수 신호로 평가받는다:

1. **정보 비대칭**: 임원은 회사 내부 정보에 가장 가까운 사람이며, 개인 자금을 투입한다는 사실은 향후 실적/이벤트에 대한 강한 확신을 시사한다.
2. **인센티브 정합**: 자사주 매수는 회사의 자기주식 취득(회사 자금 → 주주환원)과 달리 임원 개인의 손실 위험을 동반하므로 신호의 진실성이 더 강하다.
3. **역사적 적중률**: 임원 매수 공시 발생 종목의 익일 surge 적중률은 약 45% (Background에 명시) — 단독 신호 강도가 충분하다.

본 SPEC은 위 신호를 독립 탐지기 `detect_insider_purchase_signal()`로 분리 구현하여, `_run_coverage_expansion()`의 4번째 try/except 블록에서 격리 실행한다. `signal_type='surge_candidate'`로 발행하여 `surge_trading_service.get_today_signals` 필터를 자동 통과하며, 익일 매수 큐(`paper_executed=True`)에 진입한다.

### Problem Background

| 케이스 | 기존 처리 | 본 SPEC 처리 |
|--------|-----------|--------------|
| 회사가 자기주식 매수 결정 공시 | `detect_immediate_disclosure_signal` → `immediate_disclosure_score=0.70` (앙상블 가중치에 기여) | (변경 없음) |
| 회사가 자기주식 소각 결정 공시 | `detect_immediate_disclosure_signal` → `immediate_disclosure_score=0.90` | (변경 없음) |
| **임원이 개인 자사주 매수 공시** | **현재 어떤 탐지기도 발동 안 함** (해당 보고서명에 `_IMMEDIATE_EVENT_PATTERNS` 키워드 미포함) | **본 SPEC: `surge_candidate` 시그널 `confidence=0.45` 발행** |

### Root Cause

`_IMMEDIATE_EVENT_PATTERNS`는 회사 단위 결정 공시 키워드(`"자기주식소각", "자기주식취득결정", "단일판매ㆍ공급계약체결", "흡수합병결정"` 등)만 등록되어 있다. **임원 보고서**의 표준명("임원ㆍ주요주주특정증권등소유상황보고서")은 등록되어 있지 않으며, 등록한다고 해도 동일 보고서가 매수/매도/장외처분 등 모든 거래를 포괄하므로 단순 명칭 매칭으로는 매수 신호 분리가 불가능하다. 매수만 정확히 분리하려면 보고서명 + 거래유형 키워드("취득"/"매수")의 조합 매칭이 필요하다.

### 설계 원칙

- **가법적 확장 (Additive)**: 기존 `detect_immediate_disclosure_signal()`과 `_IMMEDIATE_EVENT_PATTERNS` 리스트를 변경하지 않는다. 본 SPEC은 별도 함수와 별도 키워드 리스트로 동작한다.
- **SPEC-AI-023과 동일 시그니처/패턴**: 신호 생성 방식, Pydantic Config, `_run_coverage_expansion` 통합 위치, 중복 방지 로직 모두 SPEC-AI-023(`detect_near_limit_up_carries`)을 직접 모델로 한다.
- **try/except 격리**: 본 단계 실패가 surge_candidate / theme_propagation / volume_anomaly / near_limit_up_carry 시그널을 손상시키지 않는다.
- **DB 스키마 무변경**: 신규 컬럼/마이그레이션 없음. 기존 `FundSignal`, `Disclosure` 필드만 사용.
- **WHAT/WHY only**: 키워드 매칭 조건과 confidence 산출, 중복 방지 정책만 정의. 내부 쿼리 최적화/캐시 전략은 RUN 단계에서 결정.

### 전제 조건 (Assumptions)

- `disclosures` 테이블은 `id`, `stock_id`, `report_name`, `report_type`, `rcept_dt`(YYYYMMDD 문자열), `created_at` 컬럼을 보유한다 (research.md §1 검증 완료).
- `report_type`은 nullable이며 일부 레코드에서 NULL일 수 있다. 따라서 매칭은 `report_name` 우선 + `report_type` 보조 OR 패턴을 사용한다.
- `fund_signals` 테이블은 `signal_type`, `confidence`, `surge_metadata`(Text JSON), `paper_executed`, `disclosure_id` 컬럼을 보유한다 (SPEC-AI-004, SPEC-AI-012, SPEC-AI-013).
- `app.services.fund_manager._run_coverage_expansion(db, surge_results)`은 surge_candidate persist 직후 호출되며 현재 3개의 try/except 블록을 보유한다 (research.md §3 검증 완료).
- DART 임원 자사주 매수의 표준 보고서명은 `"임원ㆍ주요주주특정증권등소유상황보고서"`(ㆍ = U+318D)이며 변형 `"임원·주요주주특정증권등소유상황보고서"`(중간점 ·)가 존재할 수 있다.
- 본 SPEC은 새 DB 컬럼/마이그레이션을 추가하지 않는다.
- 본 탐지기는 외부 API(naver_finance 등) 호출이 없으며 DB 쿼리만 수행한다.

---

## EARS Requirements

### REQ-AI024-001: 임원 자사주 매수 공시 패턴 탐지 및 시그널 생성

**WHERE** 시스템이 `run_surge_signal_generation()` 내 surge_candidate persist 및 `_run_coverage_expansion()`의 기존 3개 try/except 블록 실행 직후, the system SHALL `detect_insider_purchase_signal(db, config) -> list[FundSignal]` 신규 탐지기를 호출하여 임원 자사주 직접 매수에 대한 surge_candidate 시그널을 생성한다.

**WHEN** 본 탐지기가 실행될 때, the system SHALL 다음 조건으로 후보 공시를 조회한다:
- (a) `Disclosure.stock_id IS NOT NULL` (종목 연결 완료)
- (b) `Disclosure.rcept_dt >= cutoff_dt_str` — `cutoff_dt_str`는 현재 KST 시각 기준 `InsiderPurchaseConfig.lookback_days` 일수만큼 거슬러 올라간 날짜의 `YYYYMMDD` 문자열 (기본 1일 → 어제와 오늘)
- (c) 다음 두 조건 중 하나라도 충족 (OR):
    - **(c-1)** `Disclosure.report_name`에 `"임원"` 부분문자열이 포함되고 **동시에** (`"취득"` 또는 `"매수"`) 중 하나가 포함됨
    - **(c-2)** (`Disclosure.report_type` 또는 `Disclosure.report_name`)에 `"임원ㆍ주요주주특정증권등소유상황보고서"`(ㆍ U+318D) 또는 `"임원·주요주주특정증권등소유상황보고서"`(중간점 ·) 부분문자열이 포함되고 **동시에** `Disclosure.report_name`에 (`"취득"` 또는 `"매수"`) 중 하나 포함됨

**WHERE** 매칭된 후보 공시 중, the system SHALL 다음 키워드 중 하나라도 `report_name`에 포함되면 해당 공시를 제외한다 (음성 신호 차단):
- `"처분"`, `"매도"`, `"매각"`, `"양도"` (매도성 거래 보고서)
- `"감소"` (지분 감소 보고)

**WHERE** 같은 `stock_id`에 매칭되는 공시가 lookback 범위 내에 여러 건 존재할 경우, the system SHALL 종목당 1건의 시그널만 생성한다 (가장 최근 공시를 대표로 사용).

**IF** 매칭된 종목의 `stock_id`에 오늘 (KST 00:00:00 이후) 이미 `signal_type='surge_candidate'` 시그널이 존재하면, **then** the system SHALL 해당 종목을 스킵하고 다음 종목 처리를 계속한다 (중복 방지 — SPEC-AI-023 동일 정책).

**IF** 위 모든 조건 (REQ-AI024-001 a/b/c 충족 + 음성 키워드 부재 + 오늘 surge_candidate 중복 부재)을 만족하면, **then** the system SHALL 다음 값으로 신규 `FundSignal` 레코드를 생성한다:
- `stock_id` = 매칭된 종목 ID
- `signal_type` = `"surge_candidate"`
- `signal` = `"buy"`
- `confidence` = `config.base_confidence` (기본 `0.45`)
- `reasoning` = `f"[SPEC-AI-024 임원자사주매수] {report_name}"` (예: `"[SPEC-AI-024 임원자사주매수] 임원ㆍ주요주주특정증권등소유상황보고서(보통주식 5,000주 취득)"`)
- `paper_executed` = `True`
- `disclosure_id` = 매칭된 공시의 `Disclosure.id`
- `surge_metadata`(JSON 문자열): `{"surge_basis": ["insider_purchase"], "report_name": <report_name>, "rcept_no": <rcept_no>}`
- 기타 필드 (`target_price`, `stop_loss`, `price_at_signal`, `news_summary`, `financial_summary`, `market_summary`, `factor_scores`, `composite_score`, `ai_model`, `tp_sl_method`, `prompt_version`, `trend_alignment`, `volatility_level`): NULL 또는 기본값

**WHEN** 모든 후보 처리가 완료되면, the system SHALL `db.commit()`을 한 번 호출하고 생성된 `FundSignal` 객체 리스트를 반환한다.

**WHEN** 탐지기 실행이 완료될 때, the system SHALL 평가 공시 수, 매칭 종목 수, 중복으로 스킵된 종목 수, 생성된 시그널 수를 로깅한다 (`logger.info("[임원매수] 공시=%d 매칭=%d 중복스킵=%d 생성=%d", ...)`).

**WHEN** 함수 내부에서 예외가 발생할 때, the system SHALL `logger.error("[임원매수] 예외 발생: %s", e, exc_info=True)` 로깅 후 빈 리스트를 반환한다 (예외 전파 금지).

`[NEW]` `backend/app/services/surge_detector.py` — `detect_insider_purchase_signal(db, config) -> list[FundSignal]` 신규 함수
`[NEW]` `backend/app/services/surge_detector.py` — `_INSIDER_PURCHASE_REPORT_TITLES`, `_INSIDER_PURCHASE_ACTION_KEYWORDS`, `_INSIDER_PURCHASE_NEGATIVE_KEYWORDS` 모듈 상수
`[MODIFY]` `backend/app/services/fund_manager.py` — `_run_coverage_expansion()` 내 `detect_near_limit_up_carries` 호출 이후 본 탐지기 호출 추가

---

### REQ-AI024-002: InsiderPurchaseConfig 설정 클래스

**WHERE** 본 SPEC의 파라미터를 런타임에 조정할 수 있도록, the system SHALL `app.surge_config.surge_settings`에 다음 Pydantic 모델을 추가한다:

```python
class InsiderPurchaseConfig(BaseModel):
    """SPEC-AI-024: 임원 자사주 직접 매수 공시 신호 설정."""
    enabled: bool = True
    base_confidence: float = 0.45
    lookback_days: int = 1
```

**WHERE** `InsiderPurchaseConfig` 인스턴스는, the system SHALL `_run_coverage_expansion()` 내부에서 직접 instantiate하여 `detect_insider_purchase_signal(db, InsiderPurchaseConfig())` 형태로 호출한다 (SPEC-AI-023 `NearLimitUpConfig`과 동일 패턴).

**WHERE** `SurgeDetectionConfig` 본체에는, the system SHALL `InsiderPurchaseConfig` 필드를 추가하지 않는다 — 본 SPEC의 config는 독립적으로 instantiate된다.

**IF** `InsiderPurchaseConfig.enabled == False`이면, **then** the system SHALL 탐지기를 호출 즉시 빈 리스트를 반환하며 DB 쿼리를 수행하지 않는다.

`[MODIFY]` `backend/app/surge_config/surge_settings.py` — `InsiderPurchaseConfig` 클래스 정의

---

### REQ-AI024-003: 통합 지점 격리

**WHERE** `fund_manager._run_coverage_expansion()` 헬퍼는, the system SHALL 본 SPEC의 탐지기 호출을 다음 위치에 추가한다 (4번째 try/except 블록):

```
_run_coverage_expansion(db, surge_results)
├── try: propagate_theme_group_signals (SPEC-AI-022)
├── try: detect_volume_anomaly_dormant_stocks (SPEC-AI-022)
├── try: detect_near_limit_up_carries (SPEC-AI-023)
└── try: detect_insider_purchase_signal (SPEC-AI-024) ← 신규
```

**WHEN** 신규 try/except 블록이 실행될 때, the system SHALL:
- 성공 시 `logger.info("[커버리지확장] 임원자사주매수 시그널 %d개 생성", len(signals))` 로깅
- 실패 시 `logger.warning("[커버리지확장] 임원자사주매수 실패 (다른 시그널 결과 보존됨): %s", e)` 로깅
- 본 try 블록이 실패해도 이미 commit된 surge_candidate / theme_propagation / volume_anomaly / near_limit_up_carry 시그널은 보존된다

**WHERE** `detect_insider_purchase_signal()` 내부에서 단일 종목 처리가 실패하면, the system SHALL 해당 종목만 스킵하고 다음 종목 처리를 계속한다.

`[MODIFY]` `backend/app/services/fund_manager.py` — `_run_coverage_expansion()` 내 신규 try/except 블록 (REQ-AI024-001과 동일 파일 변경)

---

## Acceptance Criteria

각 요구사항별 검증 가능한 인수 기준. 외부 의존성(DB)은 in-memory SQLite 또는 fixture로 격리.

### AC-001: 임원 자사주 취득 공시 매칭 시 surge_candidate 시그널 생성 (REQ-AI024-001)

**Given**:
- 종목 X가 `stocks` 테이블에 존재 (`stock_id=100`, `stock_code="005930"`)
- 공시 D1: `stock_id=100`, `report_name="임원ㆍ주요주주특정증권등소유상황보고서(보통주식 5,000주 취득)"`, `rcept_dt=오늘 YYYYMMDD`
- 종목 X에 오늘 (KST 00:00 이후) `signal_type='surge_candidate'` 시그널 부재

**When**: `detect_insider_purchase_signal(db, InsiderPurchaseConfig())` 호출

**Then**:
- 종목 X에 대해 `signal_type="surge_candidate"`, `signal="buy"`, `confidence=0.45` 시그널 1건 생성
- `paper_executed == True`
- `disclosure_id == D1.id`
- `reasoning`에 `"[SPEC-AI-024 임원자사주매수]"` 및 `report_name` 포함
- `surge_metadata` JSON 파싱 시 `surge_basis == ["insider_purchase"]`, `report_name` 키 포함
- 함수 반환 리스트 길이 `>= 1`

### AC-002: 동일 종목에 오늘 surge_candidate 시그널 있으면 중복 생성 안 함 (REQ-AI024-001)

**Given**:
- 종목 Y(`stock_id=200`)에 AC-001과 동일한 임원 매수 공시 D2 존재
- 종목 Y에 오늘 (KST 00:00 이후) `signal_type='surge_candidate'`, `confidence=0.60` 시그널이 이미 존재 (일반 surge_candidate 또는 다른 coverage_expansion 탐지기 결과)

**When**: `detect_insider_purchase_signal(db, InsiderPurchaseConfig())` 호출

**Then**:
- 종목 Y에 대해 신규 시그널 생성 안 함
- 기존 시그널의 `confidence/signal_type/metadata` 변경 없음
- 종목 Y에 대한 처리는 `중복스킵=1` 카운트로 로깅

### AC-003: 함수 내부 예외 시 빈 리스트 반환 + 파이프라인 미영향 (REQ-AI024-001, REQ-AI024-003)

**Given**:
- `_run_coverage_expansion()` 진입 시 surge_candidate 시그널이 이미 DB에 commit됨
- `detect_insider_purchase_signal()` 내부에서 예외 발생 (예: DB 쿼리 mock이 raise)

**When**: `_run_coverage_expansion(db, surge_results)` 호출

**Then**:
- `_run_coverage_expansion`이 예외를 raise하지 않고 정상 반환
- 기존 surge_candidate, theme_propagation, volume_anomaly, near_limit_up_carry 시그널 row가 DB에 그대로 보존됨
- `logger.warning` 호출 발생 (메시지에 `"임원자사주매수 실패"` 포함)
- `detect_insider_purchase_signal()` 자체는 빈 리스트 반환 (예외 전파 금지)

### AC-004: enabled=False 시 빈 리스트 즉시 반환, DB 쿼리 없음 (REQ-AI024-002)

**Given**: `InsiderPurchaseConfig(enabled=False)` 인스턴스

**When**: `detect_insider_purchase_signal(db, config)` 호출

**Then**:
- 즉시 빈 리스트 반환
- `db.query()` 호출 0회 (mock spy 검증)
- DB add 호출 0회

### AC-005: 음성 키워드("처분", "매도") 포함 공시는 매칭 제외 (REQ-AI024-001)

**Given**:
- 종목 Z(`stock_id=300`)에 공시 D3: `report_name="임원ㆍ주요주주특정증권등소유상황보고서(보통주식 5,000주 처분)"`, `rcept_dt=오늘`

**When**: `detect_insider_purchase_signal(db, InsiderPurchaseConfig())` 호출

**Then**:
- 종목 Z에 대해 시그널 생성 안 함 (`"처분"` 키워드로 매도성 거래 차단)
- 함수 반환 리스트가 종목 Z를 포함하지 않음

### AC-006: report_type 매칭 변형(중간점 ·) 처리 (REQ-AI024-001 c-2)

**Given**:
- 종목 W(`stock_id=400`)에 공시 D4: `report_name="보통주식 1,000주 취득"`, `report_type="임원·주요주주특정증권등소유상황보고서"` (중간점 · 사용), `rcept_dt=오늘`

**When**: `detect_insider_purchase_signal(db, InsiderPurchaseConfig())` 호출

**Then**:
- 종목 W에 대해 시그널 1건 생성 (`report_type` 매칭 + `report_name`에 "취득" 포함)

### AC-007: lookback_days=1 — 어제+오늘 공시만 매칭 (REQ-AI024-001 b)

**Given**:
- 종목 V(`stock_id=500`)에 공시 D5: AC-001과 동일 패턴, `rcept_dt=오늘`
- 종목 U(`stock_id=501`)에 공시 D6: AC-001과 동일 패턴, `rcept_dt=어제`
- 종목 T(`stock_id=502`)에 공시 D7: AC-001과 동일 패턴, `rcept_dt=2일 전`

**When**: `detect_insider_purchase_signal(db, InsiderPurchaseConfig(lookback_days=1))` 호출

**Then**:
- 종목 V, U에 대해 각 1건 시그널 생성 (`rcept_dt >= 어제`)
- 종목 T는 시그널 생성 안 함 (lookback 범위 초과)

### AC-008: 종목당 1 시그널만 생성 (REQ-AI024-001 dedup)

**Given**:
- 종목 S(`stock_id=600`)에 같은 보고서 패턴의 공시 2건 (D8, D9, 둘 다 오늘 접수, 서로 다른 임원의 매수 보고)

**When**: `detect_insider_purchase_signal(db, InsiderPurchaseConfig())` 호출

**Then**:
- 종목 S에 대해 시그널 1건만 생성 (가장 최근 공시 기준)
- `disclosure_id`는 두 공시 중 1개 (`created_at` 또는 `id` 최댓값)

### AC-009: 매칭되지 않는 공시는 무시 (REQ-AI024-001 a/b/c)

**Given**:
- 공시 D10: `report_name="단일판매ㆍ공급계약체결"` (회사 단위 공시, "임원" 미포함, "취득"/"매수" 미포함)
- 공시 D11: `report_name="자기주식취득결정"` (회사 단위 자사주 취득, "임원" 키워드 미포함)
- 공시 D12: `report_name="임원ㆍ주요주주특정증권등소유상황보고서(보통주식 5,000주 양도)"` ("양도" 키워드로 음성 분기)

**When**: `detect_insider_purchase_signal(db, InsiderPurchaseConfig())` 호출

**Then**:
- D10, D11, D12 모두 매칭 제외
- 함수 반환 리스트에 해당 종목 시그널 부재

### AC-010: 통합 — `_run_coverage_expansion`이 4개 try 블록 모두 실행 (REQ-AI024-003)

**Given**:
- `_run_coverage_expansion(db, surge_results)` 호출
- 4개 탐지기 모두 정상 동작

**When**: 함수 실행

**Then**:
- 4개 `logger.info` 메시지 발생: `"[커버리지확장] 테마 전파 ..."`, `"[커버리지확장] 거래량 이상 ..."`, `"[near_limit_up] 완료 ..."`, `"[커버리지확장] 임원자사주매수 ..."`
- 4개 탐지기 모두 호출됨 (각 mock spy 1회 이상)
- 본 SPEC의 신규 try 블록은 기존 3개 블록 이후에 실행됨

---

## Implementation Notes

### 신규 함수 시그니처

```python
# backend/app/services/surge_detector.py
def detect_insider_purchase_signal(
    db: Session,
    config: "InsiderPurchaseConfig",  # noqa: F821 (지연 임포트)
) -> list[FundSignal]:
    """SPEC-AI-024 REQ-001: 임원 자사주 직접 매수 공시 기반 surge_candidate 시그널 생성.

    Returns: 생성된 FundSignal 목록 (commit 완료)
    """
```

### 신규 모듈 상수 (surge_detector.py)

```python
# 임원 보고서 표준명 — DART는 ㆍ(U+318D) 사용, 중간점 · 변형도 등록
_INSIDER_PURCHASE_REPORT_TITLES: list[str] = [
    "임원ㆍ주요주주특정증권등소유상황보고서",  # 정식 (ㆍ U+318D)
    "임원·주요주주특정증권등소유상황보고서",   # 중간점 변형
]

# 매수 거래 키워드 (report_name에 함께 포함되어야 함)
_INSIDER_PURCHASE_ACTION_KEYWORDS: list[str] = ["취득", "매수"]

# 음성 키워드 — 매도/처분성 거래는 제외
_INSIDER_PURCHASE_NEGATIVE_KEYWORDS: list[str] = [
    "처분", "매도", "매각", "양도", "감소",
]
```

### Pydantic 설정 클래스 (surge_settings.py)

```python
class InsiderPurchaseConfig(BaseModel):
    """SPEC-AI-024: 임원 자사주 직접 매수 공시 신호 설정."""
    enabled: bool = True
    base_confidence: float = 0.45
    lookback_days: int = 1
```

### fund_manager._run_coverage_expansion 통합 지점

```python
def _run_coverage_expansion(db: Session, surge_results: list[dict]) -> None:
    # ... 기존 try: propagate_theme_group_signals (SPEC-AI-022)
    # ... 기존 try: detect_volume_anomaly_dormant_stocks (SPEC-AI-022)
    # ... 기존 try: detect_near_limit_up_carries (SPEC-AI-023)

    # SPEC-AI-024: 임원 자사주 직접 매수
    try:
        from app.surge_config.surge_settings import InsiderPurchaseConfig
        from app.services.surge_detector import detect_insider_purchase_signal

        insider_config = InsiderPurchaseConfig()
        insider_signals = detect_insider_purchase_signal(db, insider_config)
        logger.info(
            "[커버리지확장] 임원자사주매수 시그널 %d개 생성",
            len(insider_signals),
        )
    except Exception as e:
        logger.warning(
            "[커버리지확장] 임원자사주매수 실패 (다른 시그널 결과 보존됨): %s", e
        )
```

### 쿼리 패턴 (참고용)

```python
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import or_

KST = ZoneInfo("Asia/Seoul")
now_kst = datetime.now(KST)
cutoff_dt_str = (now_kst - timedelta(days=config.lookback_days)).strftime("%Y%m%d")
today_utc_start = now_kst.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)

# 1. 후보 공시 조회 (lookback 범위 + stock_id 연결 + 키워드 OR)
title_filter = or_(*[Disclosure.report_name.contains(t) for t in _INSIDER_PURCHASE_REPORT_TITLES])
type_filter = or_(*[Disclosure.report_type.contains(t) for t in _INSIDER_PURCHASE_REPORT_TITLES])
title_or_type = or_(title_filter, type_filter, Disclosure.report_name.contains("임원"))

candidates = (
    db.query(Disclosure)
    .filter(
        Disclosure.rcept_dt >= cutoff_dt_str,
        Disclosure.stock_id.isnot(None),
        title_or_type,
    )
    .order_by(Disclosure.created_at.desc())
    .all()
)

# 2. Python 단에서 정밀 매칭 (취득/매수 키워드 + 음성 키워드 차단)
# 3. 종목당 1건 dedup
# 4. 오늘 surge_candidate 중복 체크 후 add
```

### @MX Tag 계획

- `detect_insider_purchase_signal()`: `@MX:NOTE` + `@MX:SPEC: SPEC-AI-024 REQ-001`. fan_in 예상 1 (`_run_coverage_expansion`에서만 호출).
- `_INSIDER_PURCHASE_REPORT_TITLES`: `@MX:NOTE` + `@MX:REASON: DART 표기 변형 ㆍ(U+318D) vs ·(중간점) 양쪽 등록`
- `_INSIDER_PURCHASE_NEGATIVE_KEYWORDS`: `@MX:NOTE` + `@MX:REASON: 임원 보고서가 매수/매도/장외처분을 모두 포괄하므로 매도성 키워드 차단 필요`
- `InsiderPurchaseConfig`: `@MX:NOTE` + `@MX:SPEC: SPEC-AI-024 REQ-002`.

### 테스트 전략

- `backend/tests/test_insider_purchase_signal.py` (신규) — AC-001 ~ AC-009
- `backend/tests/test_coverage_expansion_integration.py` (확장 또는 신규) — AC-003, AC-010
- DB는 in-memory SQLite 또는 기존 fixture 활용. naver_finance mock은 불필요 (본 탐지기는 외부 API 호출 없음).
- 목표 coverage: 신규 함수 90%+, 수정 파일 85%+

### 운영 고려사항

- **호출 시점**: `_run_coverage_expansion()`은 `run_surge_signal_generation()` 내부에서 호출되며, scheduler 기준 평일 15:20 KST. 본 SPEC의 탐지기는 DART 크롤러가 당일 임원 보고서를 수집한 이후 실행되어야 의미가 있다 (현재 dart_crawler 호출 시점 확인은 별도 운영 점검 사항).
- **DB 부담**: 일 평균 임원 매수 보고서 수는 KOSPI/KOSDAQ 합산 약 10-30건 수준 (역사 평균). 본 탐지기는 그 중 매수 거래만 분리하므로 5-15건/일 시그널 예상. surge_candidate 일평균(약 60-80건) 대비 작음.
- **API 호출 없음**: 본 탐지기는 외부 API 호출이 없다 (DB 쿼리만). naver_finance / DART API 부하 0.
- **paper_executed=True 정책**: SPEC-AI-023과 동일하게 익일 매수 큐에 자동 진입. 백테스트로 적중률 검증 후 정책 조정은 별도 SPEC.
- **DART 크롤러 의존성**: 본 SPEC의 효과는 `dart_crawler`가 `"임원ㆍ주요주주특정증권등소유상황보고서"`를 정상 수집하는지에 직접적으로 의존한다. 신규 보고서 형식이 누락된 경우 본 탐지기는 침묵한다 (오작동 아님). 운영 모니터링은 `[임원매수] 공시=0` 로그 빈도로 감지 가능.

---

## Exclusions (What NOT to Build)

- **기존 `detect_immediate_disclosure_signal()` 변경**: 회사 단위 공시 탐지기는 그대로 유지. 본 SPEC은 별도 함수로 동작.
- **`_IMMEDIATE_EVENT_PATTERNS` 확장**: 임원 보고서를 위 리스트에 추가하지 않는다 (보고서가 매수/매도 모두 포괄하여 단순 키워드 매칭 부적합).
- **신규 `signal_type='insider_purchase'` 도입**: `signal_type='surge_candidate'`를 그대로 사용. 식별은 `surge_metadata.surge_basis == ["insider_purchase"]`로 처리. 새 enum 값 도입 금지.
- **신규 DB 컬럼 추가**: `Disclosure.is_insider_purchase` 같은 boolean 컬럼 신설 금지. 키워드 매칭으로 충분.
- **신규 마이그레이션**: 본 SPEC은 DB 스키마 변경 없음.
- **임원 매수 금액/주식 수 파싱**: `report_name` 부제목 내 "5,000주" 같은 정량 정보를 추출하여 confidence를 동적 조정하지 않는다. base_confidence=0.45 고정.
- **임원 매수 후 적중률 학습**: 본 SPEC은 고정 confidence. 동적 학습은 후속 SPEC.
- **임원 등급/직급별 가중치**: CEO 매수 > 사외이사 매수 등 차등 가중치는 본 SPEC 범위 외. 모든 임원 매수를 동일 confidence로 처리.
- **target_price/stop_loss 자동 산정**: NULL로 발행. TP/SL은 매수 단계의 `surge_trading_service`에서 별도 산정.
- **`SurgeDetectionConfig`에 `insider_purchase` 필드 추가**: `InsiderPurchaseConfig`은 독립 instantiate. SurgeDetectionConfig 본체 변경 금지.
- **scheduler.py 호출 시간 변경**: 본 SPEC은 함수 시그니처와 로직만 정의. 호출 시점 조정은 별도 작업.
- **프론트엔드 변경**: backend-only SPEC. 새 시그널의 UI 표시는 surge_basis 필드를 기존 UI가 처리.
- **외부 알림 (이메일/슬랙) 발송**: 본 SPEC은 시그널 생성만. 알림은 기존 briefing 시스템에 위임.
- **DART API 직접 호출**: 본 SPEC은 기존 `dart_crawler`가 수집한 `disclosures` 테이블만 조회. DART API 직접 호출 금지.
- **임원 매수 외 주요주주(지분 5% 이상) 매수 별도 처리**: 동일 보고서 양식을 사용하므로 본 SPEC의 매칭 조건에 포함되며 별도 분기 불요.

---

## Delta Markers Summary

| Marker | File | Requirements |
|--------|------|--------------|
| `[NEW]` | `backend/app/services/surge_detector.py` (`detect_insider_purchase_signal` 함수 + 3개 모듈 상수) | REQ-AI024-001 |
| `[MODIFY]` | `backend/app/services/fund_manager.py` (`_run_coverage_expansion` 내 4번째 try 블록 추가) | REQ-AI024-001, REQ-AI024-003 |
| `[MODIFY]` | `backend/app/surge_config/surge_settings.py` (`InsiderPurchaseConfig` 클래스 추가) | REQ-AI024-002 |
| `[NEW]` | `backend/tests/test_insider_purchase_signal.py` | AC-001 ~ AC-002, AC-004 ~ AC-009 |
| `[NEW or MODIFY]` | `backend/tests/test_coverage_expansion_integration.py` | AC-003, AC-010 |

---

## Related SPECs

- **SPEC-AI-004** (선행, 필수): 공시 충격 스코어링 — `Disclosure.impact_score`, `FundSignal.disclosure_id` 필드. 본 SPEC은 `disclosure_id`를 활용.
- **SPEC-AI-012** (선행, 필수): 급등 징후 탐지 — `surge_candidate` signal_type, `surge_metadata.surge_basis` 패턴 reference.
- **SPEC-AI-013** (선행): 급등예측 모의투자 — `surge_trading_service.get_today_signals`의 `signal_type='surge_candidate'` 필터 (본 SPEC 신규 시그널 자동 통과).
- **SPEC-AI-018** (관련, 비중복): 즉각 공시 이벤트 — `_IMMEDIATE_EVENT_PATTERNS`에 회사 단위 자사주 취득결정(score 0.70) 등록. **본 SPEC의 "임원 개인 매수"와 다른 보고서**이므로 직교(orthogonal)한다.
- **SPEC-AI-022** (선행, 필수): 시그널 커버리지 확장 — `_run_coverage_expansion()` 통합 패턴과 try/except 격리. 본 SPEC은 4번째 탐지기로 추가.
- **SPEC-AI-023** (선행, 필수): 상한가 근접 carry-forward — 본 SPEC의 직접 모델 (시그니처/Config/통합 위치 동일 패턴).

---

## Verification Checklist

- [ ] 모든 EARS 요구사항이 검증 가능한 인수 기준을 가진다 (AC-001 ~ AC-010)
- [ ] 신규 DB 마이그레이션 없음 확인 (스키마 무변경)
- [ ] 기존 `signal_type='surge_candidate'` 컬럼 의미 무변경 (필터 자동 통과)
- [ ] `surge_metadata` JSON 스키마에 `surge_basis=["insider_purchase"]`, `report_name`, `rcept_no` 키 추가만 (기존 키 변경 없음)
- [ ] `_run_coverage_expansion()` 내 4번째 try/except 격리로 다른 시그널 회귀 방지
- [ ] target coverage 85%+ 명시, 신규 함수 90%+
- [ ] @MX 태그 계획 포함 (NOTE / SPEC / REASON)
- [ ] `paper_executed=True` 기본값 (익일 매수 큐 진입 허용)
- [ ] confidence 고정값 0.45 (config로 조정 가능)
- [ ] 음성 키워드 차단 보장 (`"처분"`, `"매도"`, `"매각"`, `"양도"`, `"감소"`)
- [ ] DART 표기 변형(ㆍ U+318D vs · 중간점) 양쪽 등록
- [ ] 중복 방지: 동일 종목에 당일 surge_candidate 존재 시 스킵
- [ ] 종목당 1 시그널 dedup (lookback 내 다중 공시 매칭 시)
- [ ] 외부 API 호출 0건 (DB 쿼리만)
- [ ] 기존 `detect_immediate_disclosure_signal` 및 `_IMMEDIATE_EVENT_PATTERNS` 무변경
