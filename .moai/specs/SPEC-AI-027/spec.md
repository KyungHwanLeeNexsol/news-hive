---
id: SPEC-AI-027
version: 1.0.0
status: implemented
created: 2026-06-01
updated: 2026-06-01
author: MoAI
priority: High
issue_number: 0
title: 대기업 그룹 계열사 테마캐리 탐지기 (Corporate Group Cascade Detector)
---

# SPEC-AI-027: 대기업 그룹 계열사 테마캐리 탐지기

## HISTORY

- 2026-06-01 (v0.1.0): 초안 작성. 2026-06-01 급등 포트폴리오 분석 결과 LG그룹 계열사 다수(LG +24.03%, LG전자 +22.59%, LG이노텍 +18.73%, LG화학 +7.62% 등)가 동반 급등했으나, 현행 파이프라인이 이들을 개별 저확률(prob 0.25 ~ 0.41) theme_cluster 후보로만 식별하여 매수 큐 진입에 실패한 사각지대를 해소한다. "대장주(flagship)"가 급등하면 동일 기업집단 계열사가 동반 상승하는 패턴을 group_cascade 탐지기로 포착하여 surge_candidate 시그널로 발행한다. backend-only SPEC. 신규 마이그레이션 없음.

---

## Overview

surge_candidate 탐지 파이프라인은 **개별 종목 단위**로 후보를 평가한다. 그러나 한국 시장에서는 동일 기업집단(계열사 그룹)의 대장주가 급등하면 같은 그룹의 다른 계열사가 **시차를 두고 동반 상승**하는 패턴이 반복 관찰된다. 현행 시스템은 이 그룹 단위 연쇄(cascade) 신호를 포착하지 못한다.

본 SPEC은 `_run_coverage_expansion()`에 **신규 try/except 블록 1개**(7번째 탐지기)를 추가한다. 한 종목이 대장주 조건(surge_probability >= 0.70 **또는** intraday 등락률 >= 12% AND market_cap >= 5조원)을 만족하면, 종목명 접두사(prefix) 매칭으로 동일 그룹 계열사를 찾아 `signal_type="surge_candidate"`, `surge_basis=["group_cascade"]` 시그널을 confidence decay(대장주 confidence x 0.7)와 함께 발행한다.

### Problem Background

| 시나리오 | 기존 파이프라인 처리 | 본 SPEC 처리 |
|---|---|---|
| LG(003550) +24.03% surge_prob 높음, LG전자/LG이노텍은 prob 0.25 ~ 0.40 theme_cluster only | 계열사는 저확률 후보로만 식별 → 매수 큐 미진입 | 대장주 LG 탐지 → "LG" 접두사 계열사를 group_cascade 시그널로 boost 발행 |
| 삼성전기(009150) +23.73% 단독 급등, 삼성전자/삼성SDS는 신호 부재 | 대장주가 surge_prob >= 0.70 미달 시 그룹 전파 없음 | intraday 등락률 >= 12% AND 시총 >= 5조 → flagship 인정, "삼성" 계열사 cascade |
| 두산(000150) +15.80% volume_news_combo, 두산 계열사 다수 존재 | 두산 단독 후보, 계열사 미탐지 | "두산" 접두사 계열사 최대 3개를 cascade 후보로 발행 |

### Root Cause

- 기존 탐지기(theme_cluster, theme_propagation 등)는 **개별 종목 점수** 또는 **사전 정의된 theme_groups 테이블**에 의존
- theme_propagation(SPEC-AI-022)은 `theme_groups` 시드(LG/삼성/현대차/SK 4개 그룹)에 등록된 종목만 전파하며, 시드에 없는 계열사(예: 두산, 한화, DB)는 대상에서 제외됨
- 대장주가 surge_candidate 자격을 충족하더라도, **계열사 단위 confidence boost** 로직이 없어 저확률 계열사가 매수 컷오프(min 0.30)를 통과하지 못함
- 종목명 접두사("LG", "삼성", "현대", "SK", "두산", "한화")라는 강력한 그룹 식별 신호가 활용되지 않음

### 설계 원칙 (Design Principles)

- **가법적 확장 (Additive)**: 기존 surge_candidate / theme_propagation / volume_anomaly / near_limit_up_carry / insider_purchase / executive_disclosure / forum_mention_surge 생성 로직 변경 절대 금지. 본 SPEC은 7번째 탐지기를 추가만 한다.
- **try/except 격리**: `_run_coverage_expansion()` 내 신규 try 블록(7번째)으로 추가. 본 단계 실패가 상위 파이프라인 및 기존 6개 탐지기 결과에 영향 없음.
- **신규 마이그레이션 없음**: `stocks` 테이블의 기존 `name`, `stock_code`, `market_cap` 컬럼만 사용. theme_groups 테이블 의존 없음(접두사 매칭이 1차 식별 수단). DB 스키마 무변경.
- **신규 signal_type 도입 금지**: `signal_type="surge_candidate"`를 그대로 사용. 식별은 `surge_metadata.surge_basis=["group_cascade"]`로 수행. 따라서 `surge_trading_service.get_today_signals`의 `signal_type='surge_candidate'` 필터를 자동 통과한다.
- **paper_executed=True**: 사용자 요구사항. 본 SPEC 시그널은 익일 매수 큐에 자동 진입(SPEC-AI-022 theme_propagation / SPEC-AI-023 near_limit_up_carry와 동일 정책).
- **하드코딩 금지**: 종목코드를 하드코딩하지 않는다. 그룹 식별은 종목명 접두사(prefix, 길이 >= 2자) 매칭 또는 기존 theme_groups 테이블을 사용한다.
- **WHAT/WHY only**: 시그널 생성 조건과 confidence 공식만 정의. 쿼리 최적화, 인덱스 활용, prefix 매칭 알고리즘 세부는 RUN 단계에서 결정.

### 전제 조건 (Assumptions)

- `stocks` 테이블은 `id`, `name`, `stock_code`, `market_cap`(억원 단위, nullable) 컬럼을 보유한다.
- `market_cap`은 **억원** 단위이다. 따라서 5조원 = 50000(억원), 1,000억원 = 1000.
- `fund_signals` 테이블은 `signal_type`, `signal`, `confidence`, `reasoning`, `surge_metadata`, `paper_executed`, `stock_id`, `created_at` 컬럼을 보유한다(SPEC-AI-004, SPEC-AI-012, SPEC-AI-023).
- 대장주의 "surge_probability"는 당일 생성된 `surge_results`(=`_gather_surge_candidates` 반환값)의 `surge_score` 또는 동일 종목의 당일 surge_candidate `confidence`로부터 도출 가능하다.
- intraday 등락률은 기존 시세 조회 함수(`_fetch_price_change_sync` 또는 `naver_finance.fetch_current_price_with_change`)로 조회 가능하다.
- `_run_coverage_expansion`은 `run_surge_signal_generation` 내 surge_candidate persist 직후 호출되며, 인자로 `surge_results: list[dict]`(대장주 후보 식별 입력)를 받는다(SPEC-AI-022 ~ SPEC-AI-026).
- `surge_trading_service.get_today_signals`는 `signal_type='surge_candidate'`만 필터링하므로, 본 SPEC 신규 시그널도 동일 signal_type으로 발행되어 자동으로 익일 매수 큐에 포함된다.
- 본 SPEC은 새 DB 컬럼/마이그레이션을 추가하지 않는다.

---

## EARS Requirements

### REQ-AI027-001: 그룹 cascade 조건 탐지 (대장주 식별)

**WHERE** 시스템이 `_run_coverage_expansion()` 내 surge_candidate / theme_propagation / volume_anomaly / near_limit_up_carry / insider_purchase / executive_disclosure / forum_mention_surge 처리 완료 후, the system SHALL `detect_group_cascade_signals(db, surge_results, config) -> list[FundSignal]` 신규 탐지기를 호출하여 대장주 동반 상승 후보를 발행한다.

**WHEN** 본 탐지기가 실행될 때, the system SHALL 다음 두 조건 중 **하나 이상**을 만족하는 종목을 대장주(flagship) 후보로 식별한다:
- (a) 대장주 surge_probability(`surge_results`의 해당 종목 `surge_score`, 또는 당일 surge_candidate confidence) `>= GroupCascadeConfig.flagship_prob_threshold`(기본 0.70)
- (b) 대장주 당일 intraday 등락률 `>= GroupCascadeConfig.flagship_change_pct`(기본 12.0%) **AND** 해당 종목 `market_cap >= GroupCascadeConfig.flagship_min_market_cap`(기본 50000, 즉 5조원)

**IF** 후보 종목의 `market_cap`이 NULL 이거나 조건 (a)·(b)를 모두 미달하면, **then** the system SHALL 해당 종목을 대장주에서 제외한다.

**WHERE** 동일 종목이 surge_results와 당일 surge_candidate 양쪽에서 식별되면, the system SHALL 더 높은 확률값을 대장주 confidence로 채택한다.

`[NEW]` `backend/app/services/surge_detector.py` — `detect_group_cascade_signals(db, surge_results, config) -> list[FundSignal]` 신규 함수
`[MODIFY]` `backend/app/services/fund_manager.py` — `_run_coverage_expansion()` 내 forum_mention_surge 호출 이후 호출 추가(별도 try/except 블록)

---

### REQ-AI027-002: cascade 계열사 후보 식별

**WHEN** 대장주가 식별될 때, the system SHALL 대장주 종목명에서 그룹 식별용 **접두사(prefix)**를 추출한다(길이 >= `GroupCascadeConfig.min_prefix_len`, 기본 2자). 추출 규칙은 대장주 종목명의 선행 토큰(예: "LG" -> "LG", "삼성전기" -> "삼성", "두산" -> "두산")으로 한다.

**WHEN** 접두사가 추출될 때, the system SHALL `stocks` 테이블에서 동일 접두사로 시작하는 계열사 후보를 조회하되, 다음 필터를 적용한다:
- `name LIKE '{prefix}%'` (대장주 자신은 제외)
- `market_cap >= GroupCascadeConfig.cascade_min_market_cap`(기본 1000, 즉 1,000억원)
- 당일(KST 00:00 이후) `surge_candidate` / `theme_propagation` / `volume_anomaly` 시그널이 **부재**한 종목(REQ-AI027-004 dedup 가드)

**WHEN** 동일 접두사 계열사가 다수일 때, the system SHALL `market_cap` 내림차순으로 정렬하여 상위 `GroupCascadeConfig.max_cascade_per_flagship`(기본 3)개로 제한한다.

**IF** 추출된 접두사 길이가 `min_prefix_len` 미만이거나 매칭되는 계열사가 0개이면, **then** the system SHALL 해당 대장주에 대한 cascade 발행을 스킵한다.

**WHERE** 기존 `theme_groups` 테이블에 대장주가 앵커/멤버로 등록되어 있으면, the system MAY 접두사 매칭 대신(또는 보완하여) 동일 그룹 멤버를 cascade 후보로 사용할 수 있다(RUN 단계 결정 사항. 단, 신규 종목코드 하드코딩은 금지).

`[NO NEW FILE]` REQ-AI027-001 함수 내부에 포함

---

### REQ-AI027-003: 시그널 생성

**WHEN** cascade 계열사 후보가 확정되고 dedup 가드(REQ-AI027-004)를 통과할 때, the system SHALL 각 후보에 대해 다음 값으로 신규 `FundSignal` 레코드를 생성한다:
- `signal_type = "surge_candidate"`
- `signal = "buy"`
- `confidence = round(flagship_confidence * GroupCascadeConfig.decay_factor, 4)`, 여기서 `decay_factor` 기본값 0.7
- `reasoning = f"[SPEC-AI-027 그룹캐스케이드] 대장주 {flagship_name}({flagship_code}) {flagship_prob:.2f} 급등 → 계열사 동반 상승 기대"`
- `paper_executed = True` (익일 매수 큐 자동 포함)
- `surge_metadata`(JSON 문자열): `{"surge_basis": ["group_cascade"], "flagship_stock_code": flagship_code, "flagship_prob": round(flagship_prob, 4), "group_prefix": prefix, "surge_probability_score": confidence}`
- 기타 필드(`target_price`, `stop_loss`, `price_at_signal`, `news_summary`, `financial_summary`, `market_summary`, `disclosure_id`, `factor_scores`, `composite_score`, `ai_model`, `tp_sl_method`, `prompt_version`, `trend_alignment`, `volatility_level`): NULL 또는 기본값

**WHEN** 탐지기 실행이 완료될 때, the system SHALL 식별된 대장주 수, 평가된 계열사 후보 수, 생성된 시그널 수를 로깅한다(`logger.info("[group_cascade] flagship=%d cascade_eval=%d 생성=%d", ...)`).

`[NO NEW FILE]` REQ-AI027-001 함수 내부에 포함

---

### REQ-AI027-004: 중복 방지 가드 (Dedup Guard)

**IF** cascade 계열사 후보가 당일(KST 00:00 이후) 이미 다음 중 하나의 시그널을 보유하면, **then** the system SHALL 해당 후보에 대한 group_cascade 시그널 생성을 스킵한다:
- (a) 동일 종목에 당일 `signal_type='surge_candidate'` 시그널 존재
- (b) 동일 종목에 당일 `signal_type='theme_propagation'` 시그널 존재
- (c) 동일 종목에 당일 `signal_type='volume_anomaly'` 시그널 존재

**WHEN** 복수 대장주가 동일 계열사를 cascade 후보로 지목할 때, the system SHALL 가장 높은 `flagship_confidence`를 산출하는 대장주 기준으로 단 1건만 생성한다(중복 발행 금지).

**WHERE** 단일 계열사 후보 처리 중 예외가 발생하면, the system SHALL 해당 후보만 `db.rollback()` 후 스킵하고 다음 후보 처리를 계속한다(예외 전파 금지).

`[NO NEW FILE]` REQ-AI027-001 함수 내부에 포함

---

### REQ-AI027-005: 통합 지점 격리 (Additive Integration)

**WHERE** `fund_manager._run_coverage_expansion()` 헬퍼는, the system SHALL 본 SPEC의 탐지기 호출을 다음 위치(7번째 try 블록)에 추가한다:

```
_run_coverage_expansion(db, surge_results)
├── try 1: propagate_theme_group_signals        (기존, SPEC-AI-022)
├── try 2: detect_volume_anomaly_dormant_stocks  (기존, SPEC-AI-022)
├── try 3: detect_near_limit_up_carries           (기존, SPEC-AI-023)
├── try 4: detect_insider_purchase_signals        (기존, SPEC-AI-024)
├── try 5: detect_theme_group_carry_forward       (기존, SPEC-AI-025)
├── try 6: detect_forum_mention_surge             (기존, SPEC-AI-026)
└── try 7: detect_group_cascade_signals           (신규, SPEC-AI-027)
```

**WHEN** 신규 try/except 블록이 실행될 때, the system SHALL:
- 실패 시 `logger.error("[group_cascade] 예외 발생: %s", e, exc_info=True)` 로깅
- DB 세션 무결성을 위해 필요 시 `db.rollback()` 후에도 후속 코드(이 함수 종료) 진행
- 본 try 블록이 실패해도 이미 commit된 6개 탐지기 시그널은 보존된다

**WHERE** `GroupCascadeConfig.enabled == False`이면, the system SHALL 탐지기를 호출하지 않거나 즉시 빈 리스트를 반환한다.

`[MODIFY]` `backend/app/surge_config/surge_settings.py` — `GroupCascadeConfig(BaseModel)` 신규 Pydantic 클래스 추가
`[MODIFY]` `backend/app/services/fund_manager.py` — 7번째 try/except 블록 추가

---

## Implementation Scope

| Marker | File | Requirements |
|--------|------|--------------|
| `[NEW]` | `backend/app/services/surge_detector.py` (`detect_group_cascade_signals` 함수 추가) | REQ-AI027-001, 002, 003, 004 |
| `[MODIFY]` | `backend/app/surge_config/surge_settings.py` (`GroupCascadeConfig` 클래스 추가) | REQ-AI027-005 |
| `[MODIFY]` | `backend/app/services/fund_manager.py` (`_run_coverage_expansion`에 7번째 try 블록 추가) | REQ-AI027-001, REQ-AI027-005 |
| `[NEW]` | `backend/tests/test_group_cascade.py` | AC-001 ~ AC-009 |
| `[MODIFY]` | `backend/tests/test_coverage_expansion_integration.py` | AC-010 |

### 신규 함수 시그니처 (참고)

```python
# backend/app/services/surge_detector.py
def detect_group_cascade_signals(
    db: Session,
    surge_results: list[dict],
    config: "GroupCascadeConfig",  # noqa: F821 (지연 임포트)
) -> list[FundSignal]:
    """SPEC-AI-027: 대장주 급등 시 동일 기업집단 계열사를 group_cascade 시그널로 발행.

    대장주 식별(surge_prob >= 0.70 OR intraday >= 12% AND 시총 >= 5조) →
    종목명 접두사(prefix) 매칭으로 계열사 조회 → confidence decay(x0.7) 적용하여
    surge_candidate 발행. paper_executed=True.

    Returns: 생성된 FundSignal 목록
    """
```

### 신규 Pydantic 설정 클래스 (참고)

```python
class GroupCascadeConfig(BaseModel):
    """SPEC-AI-027: 대기업 그룹 계열사 테마캐리 탐지기 설정."""
    enabled: bool = True
    flagship_prob_threshold: float = 0.70      # 대장주 확률 임계값
    flagship_change_pct: float = 12.0          # 대장주 intraday 등락률 임계값 (%)
    flagship_min_market_cap: int = 50000       # 대장주 최소 시총 (억원, 5조원)
    cascade_min_market_cap: int = 1000         # 계열사 최소 시총 (억원, 1,000억원)
    min_prefix_len: int = 2                    # 그룹 식별 접두사 최소 길이 (자)
    max_cascade_per_flagship: int = 3          # 대장주당 최대 계열사 수
    decay_factor: float = 0.7                  # confidence decay 계수
```

### 통합 지점 (참고)

```python
def _run_coverage_expansion(db: Session, surge_results: list[dict]) -> None:
    # ... try 1 ~ 6 기존 탐지기 (변경 금지)

    # 7. 대기업 그룹 계열사 테마캐리 (SPEC-AI-027)
    try:
        from app.services.surge_detector import detect_group_cascade_signals
        from app.surge_config.surge_settings import GroupCascadeConfig
        cascade_cfg = GroupCascadeConfig()
        cascade_signals = detect_group_cascade_signals(db, surge_results, cascade_cfg)
        logger.info("[group_cascade] 완료 — %d건", len(cascade_signals))
    except Exception as e:
        logger.error("[group_cascade] 예외 발생: %s", e, exc_info=True)
```

### @MX Tag 계획

- `detect_group_cascade_signals()`: `@MX:ANCHOR` + `@MX:REASON: fund_manager._run_coverage_expansion()에서 호출(fan_in 파이프라인), 전체 stocks LIKE 스캔 + 시세 조회 포함` + `@MX:SPEC: SPEC-AI-027 REQ-001`.
- `GroupCascadeConfig`: `@MX:NOTE` + `@MX:SPEC: SPEC-AI-027 REQ-005`.
- prefix LIKE 쿼리가 stocks 풀스캔에 가까우면 `@MX:WARN` + `@MX:REASON: name LIKE 접두사 매칭 인덱스 미활용 시 풀스캔 위험` 권고(RUN 단계 쿼리 플랜 확인).

---

## Acceptance Criteria

각 요구사항별 검증 가능한 인수 기준. 외부 의존성(DB, 시세 조회)은 in-memory SQLite 또는 mock으로 격리.

| AC | 시나리오 | 기대 결과 | REQ |
|----|----------|-----------|-----|
| AC-001 | 대장주 "LG"(003550) surge_prob=0.80(>=0.70), 시총 충분, 계열사 "LG전자"·"LG화학"·"LG이노텍" 당일 신호 부재, 시총 >= 1000 | LG전자/LG화학/LG이노텍 각각 1건 group_cascade 시그널 생성. confidence = round(0.80*0.7, 4) = 0.56. surge_basis=["group_cascade"], flagship_stock_code="003550", paper_executed=True | REQ-001, 002, 003 |
| AC-002 | 대장주 "삼성전기"(009150) surge_prob=0.40(<0.70) 이나 intraday 등락률=23.73%(>=12.0) AND 시총 >= 50000 | flagship 인정. "삼성" 접두사 계열사 cascade 발행 | REQ-001 |
| AC-003 | 후보 종목 intraday=23% 이나 market_cap=NULL | flagship에서 제외(시그널 0건), 예외 없음 | REQ-001 |
| AC-004 | 대장주 "두산"(000150) flagship, 계열사 5개 매칭(시총 내림차순) | 상위 3개만 cascade 시그널 생성(max_cascade_per_flagship=3) | REQ-002 |
| AC-005 | 대장주 접두사 추출 결과 1자(min_prefix_len=2 미만) 또는 매칭 계열사 0개 | 해당 대장주 cascade 스킵, 시그널 0건 | REQ-002 |
| AC-006 | cascade 후보 "LG전자"에 당일 surge_candidate 시그널 이미 존재 | 해당 후보 스킵(중복 미생성), 기존 시그널 변경 없음 | REQ-004 |
| AC-007 | cascade 후보 "LG화학"에 당일 theme_propagation 시그널 존재 | 해당 후보 스킵 | REQ-004 |
| AC-008 | 동일 계열사를 대장주 A(prob 0.75)·B(prob 0.90)가 모두 지목 | confidence = round(0.90*0.7, 4)=0.63 단 1건만 생성(최고 flagship 기준) | REQ-004 |
| AC-009 | `GroupCascadeConfig(enabled=False)` | 즉시 빈 리스트 반환, DB add 0회 | REQ-005 |
| AC-010 | `_run_coverage_expansion()` 내 detect_group_cascade_signals 예외 발생 | 함수가 raise하지 않고 정상 반환, 기존 6개 탐지기 시그널 DB 보존, `logger.error` 호출(메시지에 "group_cascade" 포함) | REQ-005 |

### AC 상세 — AC-001 (대표 케이스)

**Given**:
- `stocks`: LG(003550, market_cap=50000), LG전자(066570, market_cap=30000), LG화학(051910, market_cap=40000), LG이노텍(011070, market_cap=20000)
- `surge_results`에 LG(003550) `surge_score=0.80` 포함
- LG전자/LG화학/LG이노텍에 당일 surge_candidate/theme_propagation/volume_anomaly 시그널 부재
- `GroupCascadeConfig()` 기본값

**When**: `detect_group_cascade_signals(db, surge_results, GroupCascadeConfig())` 호출

**Then**:
- LG전자/LG화학/LG이노텍 각각 surge_candidate 시그널 1건(총 3건) 생성
- 각 `confidence == 0.56`(= round(0.80 * 0.7, 4))
- 각 `surge_metadata` 파싱 시 `surge_basis == ["group_cascade"]`, `flagship_stock_code == "003550"`, `flagship_prob == 0.8`, `group_prefix == "LG"`
- 각 `paper_executed == True`, `signal == "buy"`, `signal_type == "surge_candidate"`
- 함수 반환 리스트 길이 == 3

---

## Non-Goals (Exclusions — What NOT to Build)

- **신규 마이그레이션 / DB 스키마 변경**: `stocks`, `fund_signals` 테이블 컬럼 추가 금지. `surge_metadata` JSON 표기로 충분. theme_groups 테이블 시드 변경 금지.
- **신규 signal_type 도입**: `signal_type='surge_candidate'`를 그대로 사용. 새 enum 값(`group_cascade` 등) 도입 금지(식별은 surge_basis로).
- **종목코드 하드코딩**: LG/삼성/현대 등 그룹의 종목코드를 코드에 직접 박지 않는다. 접두사 매칭 또는 기존 theme_groups 테이블만 사용.
- **그룹 마스터 테이블 신규 구축**: 계열사 관계 전용 테이블/모델 신규 생성 금지(접두사 매칭으로 1차 해결). 정교한 계열사 매핑은 후속 SPEC.
- **접두사 오탐 정교화(예: "삼성전기" vs "삼성카드" 동일 그룹 여부, "한국..." 비계열 종목)**: 단순 prefix LIKE 매칭만 수행. 시멘틱/사업자등록번호 기반 계열 판정은 본 SPEC 범위 외.
- **대장주 intraday 등락률 실시간 스트리밍**: 기존 시세 조회 함수의 동기 호출만 사용. 실시간 틱 데이터 연동은 별도 SPEC.
- **confidence 동적 학습**: 고정 decay_factor(0.7) 공식. 적중률 기반 동적 조정은 후속 SPEC.
- **cascade 발행 종목의 target_price/stop_loss 자동 산정**: NULL로 발행. TP/SL은 매수 단계 `surge_trading_service`에서 별도 산정.
- **`SurgeDetectionConfig` 본체 변경**: `GroupCascadeConfig`은 독립 instantiate. SurgeDetectionConfig에 필드 추가 금지.
- **기존 6개 탐지기 로직 변경**: surge_candidate / theme_propagation / volume_anomaly / near_limit_up_carry / insider_purchase / executive_disclosure / forum_mention_surge 어느 것도 수정하지 않는다.
- **scheduler.py 호출 시간 변경**: 본 SPEC은 함수 시그니처와 로직만 정의.
- **프론트엔드 변경**: backend-only SPEC. 신규 시그널의 UI 표시는 기존 `surge_basis` 처리 로직에 위임.
- **외부 알림(이메일/슬랙) 발송**: 시그널 생성만. 알림은 기존 briefing 시스템에 위임.

---

## Related SPECs

- **SPEC-AI-022** (선행, 필수): 시그널 커버리지 확장 — `_run_coverage_expansion()` 통합 지점, try/except 격리 패턴, theme_groups 인프라(`theme_groups`, `stock_theme_groups`)를 제공. 본 SPEC은 동일 패턴으로 7번째 탐지기를 추가하며, theme_propagation과 보완 관계(접두사 매칭으로 시드 미등록 그룹까지 커버).
- **SPEC-AI-023** (선행): 상한가 근접 carry-forward — `paper_executed=True` + `surge_candidate` 발행 패턴 및 `list[FundSignal]` 반환 시그니처의 reference.
- **SPEC-AI-024 / 025 / 026** (선행): 각각 5/6번째 try 블록. 본 SPEC의 7번째 블록은 동일 격리 패턴 적용.
- **SPEC-AI-012** (선행): 급등 징후 탐지 — `surge_candidate` signal_type과 `surge_metadata.surge_basis` 패턴 reference.
- **SPEC-AI-013** (선행): 급등예측 모의투자 포트폴리오 — `surge_trading_service.get_today_signals`의 signal_type 필터(본 SPEC 신규 시그널 자동 통과) 및 `execute_buy_orders()`의 surge_probability_score 정렬.

---

## Verification Checklist

- [ ] 모든 EARS 요구사항이 검증 가능한 인수 기준을 가진다(AC-001 ~ AC-010)
- [ ] 신규 DB 마이그레이션 없음 확인(스키마 무변경)
- [ ] 기존 `signal_type='surge_candidate'` 의미 무변경(필터 자동 통과)
- [ ] `surge_metadata` JSON에 `group_cascade` surge_basis 키 추가만(기존 키 변경 없음)
- [ ] `_run_coverage_expansion()` 7번째 try/except 격리로 기존 6개 탐지기 회귀 방지
- [ ] 종목코드 하드코딩 부재 확인(접두사 매칭 또는 theme_groups만 사용)
- [ ] market_cap 단위 일관성(억원: 5조=50000, 1000억=1000) 검증
- [ ] confidence 공식 검증 가능(`round(flagship_confidence * decay_factor, 4)`, decay 기본 0.7)
- [ ] 중복 방지: 당일 surge_candidate / theme_propagation / volume_anomaly 존재 시 스킵
- [ ] 복수 대장주 동일 계열사 지목 시 최고 flagship 기준 단 1건 생성
- [ ] max_cascade_per_flagship(기본 3) 제한 검증
- [ ] `paper_executed=True` 기본값(익일 매수 큐 진입)
- [ ] in-memory DB 또는 mock 기반 격리 테스트로 외부 의존성 차단
- [ ] target coverage 85%+ 명시, 신규 함수 90%+
- [ ] @MX 태그 계획 포함(ANCHOR / NOTE / SPEC, LIKE 쿼리 인덱스 의존도에 따라 WARN 권고)
