---
id: SPEC-AI-018
version: 0.1.0
status: draft
created: 2026-05-27
updated: 2026-05-27
author: MoAI
priority: High
issue_number: 0
title: 시장 레짐 분류 시스템 강화 (Market Regime Detection Hardening)
---

# SPEC-AI-018: 시장 레짐 분류 시스템 강화

## HISTORY

- 2026-05-27 (v0.1.0): 초안 작성. SPEC-AI-015 레짐 분류기의 4대 약점(지표 단일성, 히스테리시스 부재, SIDEWAYS 하드코딩 신뢰도, 정적 탐지기 파라미터) 보완. brownfield delta SPEC.

---

## Overview

SPEC-AI-015에서 구축한 기본 시장 레짐 분류기(`market_regime_service.py`)는 KOSPI 5일 수익률과 20일 이동평균 위치 2개 지표만으로 BULL/BEAR/SIDEWAYS를 분류한다. P4 분석 결과 4가지 약점이 식별되었다.

1. **지표 단일성**: 5일 수익률만으로는 단 하루 변동으로 BULL↔SIDEWAYS가 뒤집힐 수 있다. 시장 폭(breadth) 신호가 없다.
2. **히스테리시스 부재**: 하루짜리 레짐 전환이 트레이딩 파라미터에 휩쏘(whipsaw)를 유발한다.
3. **SIDEWAYS 신뢰도 하드코딩(0.6)**: "명확히 상승/하락이 아닌" 경우에 대한 실제 불확실성 측정이 없다.
4. **레짐별 탐지기 파라미터 부재**: `volume_zscore_threshold`(2.5), `news_window_hours`(24)가 시장 국면과 무관하게 정적이다.

본 SPEC은 위 4가지 약점을 보완하는 4개의 집중 요구사항을 정의한다. SPEC-AI-017이 정의한 앙상블 `regime_thresholds`는 변경하지 않는다.

### 전제 조건 (Assumptions)

- `SectorMomentum` 테이블은 날짜별로 다수 섹터의 `avg_return_5d`를 보유한다 (섹터 폭 계산 가능).
- `MarketRegime` 테이블은 날짜별 1개 레코드를 보유하며(`date` UNIQUE), `get_recent_regimes()`로 직전 레코드 조회가 가능하다.
- 현재 `classify_market_regime()`는 `(kospi_5d_return, kospi_20d_ma_position, vol_level=None)` 3개 인자를 받으며(`vol_level`은 미사용), `tuple[MarketRegimeEnum, float]`을 반환한다.
- 현재 거래량/뉴스 콤보 탐지 함수의 실제 이름은 `detect_volume_surge_news_combo(db, config)`이다 (요청서의 `detect_volume_news_combo`는 동일 함수를 지칭).
- 설정 파싱은 Pydantic `BaseModel`(`SurgeDetectionConfig`)로 수행된다 (dataclass 아님).

---

## EARS Requirements

### REQ-018-001: 섹터 폭(breadth) 지표 추가

**WHERE** `_fetch_kospi_indicators(db)`가 KOSPI 지표를 계산할 때, the system SHALL `positive_sector_ratio`(해당 날짜 `SectorMomentum` 레코드 중 `avg_return_5d > 0`인 섹터 수 / 전체 섹터 수)를 추가로 계산하여 반환한다.

**WHEN** `_fetch_kospi_indicators(db)`가 호출되면, the system SHALL `(kospi_5d_return, kospi_20d_ma_position, positive_sector_ratio)` 3-튜플을 반환한다 (기존 2-튜플에서 확장).

**WHERE** `classify_market_regime()`가 레짐을 분류할 때, the system SHALL `positive_sector_ratio` 인자를 추가로 수용한다. 기존 `vol_level` 선택 인자와의 호환성을 유지한다.

**WHEN** BULL 분류 조건을 검사할 때, the system SHALL 기존 조건(`kospi_5d_return >= 1.5 AND kospi_20d_ma_position > 0.0`)에 더해 `positive_sector_ratio >= 0.6`(과반 섹터 상승)을 추가로 요구한다.

**IF** `positive_sector_ratio <= 0.3`(70% 이상 섹터 하락)이면, **then** the system SHALL 기존 BEAR 조건에 OR 조건으로 추가하여 BEAR로 분류한다.

**WHERE** BULL 및 BEAR 조건이 모두 충족되지 않을 때, the system SHALL SIDEWAYS로 분류한다 (기본값).

**WHEN** `classify_market_regime()`가 반환할 때, the system SHALL 반환 시그니처 `tuple[MarketRegimeEnum, float]`을 변경 없이 유지한다.

`[MODIFY]` `backend/app/services/market_regime_service.py`

---

### REQ-018-002: 레짐 히스테리시스 (Regime Hysteresis)

**WHEN** `get_or_create_today_regime()`가 새 레짐을 확정하기 전, the system SHALL DB의 직전 2개 `MarketRegime` 레코드를 조회하여 검사한다.

**IF** 새로 분류된 레짐이 직전 2일 이상 연속으로 동일하게 분류되었거나 신뢰도 점수 `confidence >= 0.75`인 경우, **then** the system SHALL 저장된 레짐을 새 레짐으로 교체한다.

**IF** 새로 분류된 레짐이 위 교체 조건을 충족하지 못하면, **then** the system SHALL 직전의 안정(stable) 레짐 값을 `regime` 필드에 유지하고, 새로 분류된 "raw" 레짐을 `MarketRegime.raw_regime` 필드에 기록한다.

**WHEN** 새로 분류된 레짐이 BEAR로의 전환인 경우, the system SHALL 히스테리시스 규칙과 무관하게 즉시 BEAR를 적용한다 (비대칭 규칙 — 자본 보호 우선).

**WHERE** 직전 레코드가 존재하지 않거나(첫 분류) `raw_regime`이 명확한 안정값과 동일할 때, the system SHALL `raw_regime`을 최종 `regime`과 동일하게 설정한다.

`[MODIFY]` `backend/app/services/market_regime_service.py`
`[MODIFY]` `backend/app/models/market_regime.py` (raw_regime 컬럼 추가)
`[NEW]` `backend/alembic/versions/054_spec_ai_018_raw_regime.py` (down_revision=053)

---

### REQ-018-003: SIDEWAYS 신뢰도 동적 계산

**WHERE** `classify_market_regime()`가 SIDEWAYS로 분류할 때, the system SHALL 하드코딩된 `confidence = 0.6`을 거리 기반 동적 공식으로 대체한다.

**WHEN** SIDEWAYS 신뢰도를 계산할 때, the system SHALL "BULL 임계까지의 거리"를 다음과 같이 계산한다: `d_bull = max(0, 1.5 - kospi_5d_return) / 1.5 * 0.5 + max(0, -kospi_20d_ma_position) / 2.0 * 0.5`.

**WHEN** SIDEWAYS 신뢰도를 계산할 때, the system SHALL "BEAR 임계까지의 거리"를 다음과 같이 계산한다: `d_bear = max(0, kospi_5d_return - (-1.5)) / 1.5 * 0.5 + max(0, kospi_20d_ma_position - (-2.0)) / 2.0 * 0.5`.

**WHEN** 두 거리가 계산되면, the system SHALL SIDEWAYS 신뢰도를 `0.5 + min(d_bull, d_bear) * 0.4`로 산출하며 최대 0.9로 캡(cap)한다 (중간 영역에 깊을수록 높은 신뢰도).

**WHERE** 위 모든 계산은, the system SHALL `classify_market_regime()` 함수 내부에서 수행한다.

`[MODIFY]` `backend/app/services/market_regime_service.py`

---

### REQ-018-004: 레짐별 탐지기 파라미터 (Regime-aware Detector Parameters)

**WHERE** `surge_detection.yaml`이 로드될 때, the system SHALL `regime_detector_params` 섹션(BULL/BEAR별 `volume_zscore_threshold`, `news_window_hours`, `min_news_sentiment`)을 인식한다.

**WHEN** `SurgeDetectionConfig`가 설정을 파싱할 때, the system SHALL `regime_detector_params`를 타입이 지정된 구조(Pydantic 모델)로 파싱하며, 섹션 부재 시 빈 기본값으로 안전하게 처리한다.

**WHEN** `detect_volume_surge_news_combo()`가 호출될 때, the system SHALL `market_regime: str` 인자를 수용하고, 해당 레짐에 대한 파라미터가 존재하면 레짐별 임계값을 사용한다.

**IF** 시장 레짐이 SIDEWAYS이거나 `regime_detector_params`에 없는 미지(unknown) 값이면, **then** the system SHALL `volume_news_combo` 섹션의 기본값으로 폴백한다.

**WHEN** `gather_surge_candidates()`가 `detect_volume_surge_news_combo()`를 호출할 때, the system SHALL `market_regime` 문자열을 전달한다.

**WHERE** 앙상블 `regime_thresholds`(SPEC-AI-017)는, the system SHALL 변경하지 않는다.

`[MODIFY]` `backend/app/surge_config/surge_detection.yaml`
`[MODIFY]` `backend/app/surge_config/surge_settings.py`
`[MODIFY]` `backend/app/services/surge_detector.py`

---

## Exclusions (What NOT to Build)

- **KOSPI 60일 수익률 지표**: `benchmark` 함수가 충분한 데이터를 반환하지 못할 수 있어 제외.
- **머신러닝 기반 레짐 분류기**: 본 SPEC 범위 외.
- **장중(intraday) 레짐 감지**: 현 시스템은 장 마감(end-of-day) 기준이며 유지.
- **VIX 또는 옵션 기반 신호**: 데이터 소스 없음.
- **앙상블 `regime_thresholds` 변경**: SPEC-AI-017이 이미 정의(BULL 0.38 / SIDEWAYS 0.50 / BEAR 0.52). 변경 금지.
- **레짐 표시용 프론트엔드/API 변경**: 기존 `/fund/market-regime` 엔드포인트로 충분.
- **`REGIME_PARAMS_MAP` 투자 파라미터 변경**: SPEC-AI-015 Table 1 하드코딩 값은 본 SPEC 범위 외.

---

## Delta Markers Summary

| Marker | File | Requirements |
|--------|------|--------------|
| `[MODIFY]` | `backend/app/services/market_regime_service.py` | REQ-018-001, 002, 003 |
| `[MODIFY]` | `backend/app/models/market_regime.py` | REQ-018-002 |
| `[NEW]` | `backend/alembic/versions/054_spec_ai_018_raw_regime.py` | REQ-018-002 |
| `[MODIFY]` | `backend/app/surge_config/surge_detection.yaml` | REQ-018-004 |
| `[MODIFY]` | `backend/app/surge_config/surge_settings.py` | REQ-018-004 |
| `[MODIFY]` | `backend/app/services/surge_detector.py` | REQ-018-004 |
| `[NEW]` | `backend/tests/test_market_regime.py` | REQ-018-001, 002, 003 검증 |

---

## Related SPECs

- **SPEC-AI-015** (선행): 기본 레짐 분류기 — 본 SPEC이 강화하는 대상.
- **SPEC-AI-017** (병렬): 앙상블 임계값 — `regime_thresholds`는 본 SPEC이 변경하지 않는 외부 의존 계약.
