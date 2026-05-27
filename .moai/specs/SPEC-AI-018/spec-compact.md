# SPEC-AI-018 Compact: 시장 레짐 분류 시스템 강화

> Requirements + Acceptance Criteria only. Full context: `spec.md`.

---

## REQ-018-001: 섹터 폭(breadth) 지표 추가

- WHERE `_fetch_kospi_indicators(db)`가 지표를 계산할 때, the system SHALL `positive_sector_ratio`(`avg_return_5d > 0` 섹터 수 / 전체 섹터 수)를 추가 계산하여 `(kospi_5d_return, kospi_20d_ma_position, positive_sector_ratio)` 3-튜플을 반환한다.
- WHERE `classify_market_regime()`가 분류할 때, the system SHALL `positive_sector_ratio` 인자를 수용하며 기존 `vol_level` 선택 인자 호환을 유지한다.
- WHEN BULL 조건 검사 시, the system SHALL 기존 조건에 더해 `positive_sector_ratio >= 0.6`을 요구한다.
- IF `positive_sector_ratio <= 0.3`이면, then the system SHALL BEAR 조건에 OR로 추가하여 BEAR로 분류한다.
- WHEN 반환 시, the system SHALL `tuple[MarketRegimeEnum, float]` 시그니처를 변경하지 않는다.
- `[MODIFY]` `backend/app/services/market_regime_service.py`

**AC:**
- AC-018-001-1: 10개 섹터 중 7개 상승 → `positive_sector_ratio == 0.7` 포함 3-튜플 반환.
- AC-018-001-2: 기존 BULL 충족이나 `ratio=0.4` → SIDEWAYS로 분류.
- AC-018-001-3: 기존 BEAR 미충족이나 `ratio=0.2` → BEAR로 분류.
- AC-018-001-4: 반환은 항상 2-요소 튜플 (시그니처 불변).

---

## REQ-018-002: 레짐 히스테리시스

- WHEN `get_or_create_today_regime()`가 레짐 확정 전, the system SHALL 직전 2개 `MarketRegime` 레코드를 검사한다.
- IF 새 레짐이 2일+ 연속 동일 분류이거나 `confidence >= 0.75`이면, then the system SHALL 저장 레짐을 교체한다.
- IF 교체 조건 미충족 시, then the system SHALL `regime`을 직전 안정값으로 유지하고 신규 분류값을 `raw_regime`에 기록한다.
- WHEN BEAR 전환인 경우, the system SHALL 히스테리시스 무관 즉시 적용한다 (비대칭).
- WHERE 직전 레코드 부재(첫 분류) 시, the system SHALL `raw_regime == regime`으로 설정한다.
- `[MODIFY]` `market_regime_service.py`, `[MODIFY]` `models/market_regime.py`, `[NEW]` `alembic/versions/054_spec_ai_018_raw_regime.py` (down_revision=053)

**AC:**
- AC-018-002-1: 직전 SIDEWAYS, 신규 BULL conf=0.65, 2일 SIDEWAYS → `regime`=SIDEWAYS, `raw_regime`=BULL.
- AC-018-002-2: 2일 연속 BULL raw → `regime`=BULL 교체.
- AC-018-002-3: 신규 BULL conf=0.80 → 즉시 교체.
- AC-018-002-4: 신규 BEAR conf=0.55, 연속성 미충족 → BEAR 즉시 적용.
- AC-018-002-5: 직전 레코드 없음 → `raw_regime == regime`.

---

## REQ-018-003: SIDEWAYS 신뢰도 동적 계산

- WHERE SIDEWAYS 분류 시, the system SHALL `confidence = 0.6` 하드코딩을 거리 기반 공식으로 대체한다.
- WHEN 계산 시, the system SHALL `d_bull = max(0, 1.5 - r5)/1.5*0.5 + max(0, -ma)/2.0*0.5` 및 `d_bear = max(0, r5-(-1.5))/1.5*0.5 + max(0, ma-(-2.0))/2.0*0.5`를 산출한다.
- WHEN 두 거리 산출 후, the system SHALL `confidence = 0.5 + min(d_bull, d_bear) * 0.4`를 적용하며 최대 0.9로 캡한다.
- WHERE 모든 계산은, the system SHALL `classify_market_regime()` 내부에서 수행한다.
- `[MODIFY]` `backend/app/services/market_regime_service.py`

**AC:**
- AC-018-003-1: 중간 영역(`r5=0.0, ma=-1.0`) → 신뢰도 > 0.6 (공식 기반).
- AC-018-003-2: 최대 거리 → 신뢰도 0.9로 캡.
- AC-018-003-3: 임계 경계 근처(`r5=1.4, ma=0.1`) → 신뢰도 ≈ 0.5.

---

## REQ-018-004: 레짐별 탐지기 파라미터

- WHERE `surge_detection.yaml` 로드 시, the system SHALL `regime_detector_params`(BULL/BEAR별 `volume_zscore_threshold`/`news_window_hours`/`min_news_sentiment`)를 인식한다.
- WHEN `SurgeDetectionConfig` 파싱 시, the system SHALL `regime_detector_params`를 타입 지정 Pydantic 구조로 파싱하며 섹션 부재 시 빈 기본값으로 처리한다.
- WHEN `detect_volume_surge_news_combo()` 호출 시, the system SHALL `market_regime: str` 인자를 수용하고 해당 레짐 파라미터가 있으면 사용한다.
- IF 레짐이 SIDEWAYS이거나 미지 값이면, then the system SHALL `volume_news_combo` 기본값으로 폴백한다.
- WHEN `gather_surge_candidates()`가 호출 시, the system SHALL `market_regime` 문자열을 `detect_volume_surge_news_combo()`에 전달한다.
- WHERE 앙상블 `regime_thresholds`(SPEC-AI-017)는, the system SHALL 변경하지 않는다.
- `[MODIFY]` `surge_detection.yaml`, `[MODIFY]` `surge_settings.py`, `[MODIFY]` `surge_detector.py`

**AC:**
- AC-018-004-1: `market_regime="BULL"` → z-score 임계 2.0 사용 (기본 2.5 아님).
- AC-018-004-2: `market_regime="SIDEWAYS"` (항목 없음) → 기본값 폴백.
- AC-018-004-3: `market_regime="NEUTRAL"` (미지) → 예외 없이 기본값 폴백.
- AC-018-004-4: `regime_detector_params` 섹션 부재 → 오류 없이 로드, 빈 dict.
- AC-018-004-5: `gather_surge_candidates(..., market_regime="BEAR")` → BEAR 파라미터 전달.
- AC-018-004-6: SPEC-AI-017 `regime_thresholds` 미변경 유지.
