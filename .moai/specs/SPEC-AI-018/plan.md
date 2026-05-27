# SPEC-AI-018 구현 계획 (Implementation Plan)

## 기술적 접근 (Technical Approach)

본 SPEC은 brownfield delta 작업으로, 기존 SPEC-AI-015 레짐 분류기와 SPEC-AI-012/017 급등 탐지기를 수정한다. 신규 모듈 생성은 alembic 마이그레이션과 테스트 파일에 한정한다.

핵심 설계 원칙:
- **하위 호환성**: `classify_market_regime()`의 반환 시그니처 `tuple[MarketRegimeEnum, float]`은 불변. 신규 인자(`positive_sector_ratio`)는 기존 `vol_level` 선택 인자와 함께 수용.
- **비대칭 보호**: BEAR 전환은 히스테리시스를 우회(즉시 적용)하여 하락장 자본 보호를 우선.
- **안전한 폴백**: `regime_detector_params` 섹션 부재 / SIDEWAYS / 미지 레짐은 기존 기본값으로 폴백.
- **외부 계약 보존**: SPEC-AI-017 `regime_thresholds`는 손대지 않음.

---

## 작업 분해 (Task Breakdown)

### Milestone 1 (Priority High): 섹터 폭 지표 — REQ-018-001

1. `_fetch_kospi_indicators(db)`에 `positive_sector_ratio` 계산 추가
   - 해당 날짜 `SectorMomentum` 레코드 전체 수 및 `avg_return_5d > 0` 레코드 수 카운트
   - 분모 0 방어 (섹터 0개 시 0.5 중립값 반환)
   - 폴백 날짜 사용 시(기존 로직) 동일 날짜 기준으로 폭 계산
   - 반환 타입을 `tuple[float, float]` → `tuple[float, float, float]`로 확장
2. `classify_market_regime()`에 `positive_sector_ratio` 인자 추가
   - 시그니처: `(kospi_5d_return, kospi_20d_ma_position, positive_sector_ratio=..., vol_level=None)` 형태로 기존 선택 인자 호환 유지
   - BULL 조건에 `positive_sector_ratio >= 0.6` AND 추가
   - BEAR 조건에 `positive_sector_ratio <= 0.3` OR 추가
3. `get_or_create_today_regime()`의 `_fetch_kospi_indicators()` 호출부 및 `classify_market_regime()` 호출부를 3-튜플 언패킹으로 수정

### Milestone 2 (Priority High): 레짐 히스테리시스 — REQ-018-002

1. `MarketRegime` 모델에 `raw_regime` 컬럼 추가
   - `Mapped[MarketRegimeEnum]`, nullable=False (기존 enum 타입 `market_regime_type` 재사용)
   - 신규 레코드는 기본적으로 `regime`과 동일 값
2. alembic 마이그레이션 `054_spec_ai_018_raw_regime.py` 작성
   - `down_revision = "053"` (053_spec_ai_015_market_regime)
   - `upgrade()`: `raw_regime` 컬럼 추가 + 기존 행 백필(`raw_regime = regime`)
   - `downgrade()`: 컬럼 제거
3. `get_or_create_today_regime()`에 히스테리시스 로직 삽입
   - `get_recent_regimes(db, days=...)` 또는 직전 2개 레코드 조회
   - 교체 조건: 동일 레짐 2일 연속 OR `confidence >= 0.75`
   - BEAR 전환 즉시 적용(우회)
   - 억제 시: `regime` = 직전 안정값, `raw_regime` = 신규 분류값
   - 첫 분류(직전 레코드 없음): `regime` = `raw_regime` = 분류값

### Milestone 3 (Priority Medium): SIDEWAYS 동적 신뢰도 — REQ-018-003

1. `classify_market_regime()` SIDEWAYS 분기의 `confidence = 0.6` 제거
2. `d_bull`, `d_bear` 거리 계산 추가
3. `confidence = min(0.9, 0.5 + min(d_bull, d_bear) * 0.4)` 적용
   - SPEC 공식에서 캡 0.9는 `min(0.9, ...)`로 구현 (`min(d_bull, d_bear)`가 1.0일 때 0.9에 도달)

### Milestone 4 (Priority Medium): 레짐별 탐지기 파라미터 — REQ-018-004

1. `surge_detection.yaml`에 `regime_detector_params` 섹션 추가 (BULL/BEAR)
2. `surge_settings.py`에 Pydantic 모델 추가
   - `RegimeDetectorParamItem(BaseModel)`: `volume_zscore_threshold`, `news_window_hours`, `min_news_sentiment`
   - `SurgeDetectionConfig`에 `regime_detector_params: dict[str, RegimeDetectorParamItem] = {}` 필드 추가 (기본값 빈 dict로 부재 시 안전)
3. `detect_volume_surge_news_combo(db, config, market_regime="NEUTRAL")` 인자 추가
   - 레짐별 파라미터 조회: `config.regime_detector_params.get(market_regime)`
   - 존재 시 해당 임계값 사용, 부재/SIDEWAYS/NEUTRAL/unknown 시 `config.volume_news_combo` 기본값 폴백
4. `gather_surge_candidates()`의 `detect_volume_surge_news_combo(db, config)` 호출부에 `market_regime` 전달

### Milestone 5 (Priority Medium): 테스트 — 전 요구사항 검증

1. `backend/tests/test_market_regime.py` 신규 작성 (현재 미존재)
   - REQ-018-001/002/003 단위 테스트 (acceptance.md 시나리오 기반)
2. `backend/tests/test_surge_detector.py` 보강
   - REQ-018-004 레짐별 파라미터 선택/폴백 검증

---

## 기술적 제약 (Technical Constraints)

- **Python 3.12+**, FastAPI, SQLAlchemy 2.0 (`Mapped`/`mapped_column` 스타일 유지).
- **타입 힌트 필수**: 모든 신규/수정 함수 시그니처에 타입 힌트 (mypy 통과).
- **코드 주석은 한국어** (`code_comments: ko`).
- **반환 시그니처 불변**: `classify_market_regime()`은 `tuple[MarketRegimeEnum, float]` 유지.
- **함수명 정확성**: 실제 함수는 `detect_volume_surge_news_combo` (요청서 표기 `detect_volume_news_combo`와 동일 대상).
- **설정은 Pydantic BaseModel**: `SurgeDetectionConfig`는 dataclass 아님 — 신규 필드는 Pydantic 필드로 추가하고 기본값을 부여해 기존 YAML과 호환.
- **앙상블 가중치 검증 보존**: `validate_ensemble_weights` model_validator는 변경 금지.
- **마이그레이션 체인**: `down_revision = "053"`, 백필 포함하여 기존 행의 `raw_regime` NOT NULL 제약 충족.
- **검증 명령**: `cd backend && uv run pytest tests/test_market_regime.py tests/test_surge_detector.py --tb=short -q` 및 `uv run ruff check . && uv run mypy app/`.

---

## 위험 요소 (Risks)

| 위험 | 영향 | 완화 |
|------|------|------|
| `_fetch_kospi_indicators` 반환 타입 변경이 다른 호출처 깨뜨림 | 중 | 호출처를 grep으로 전수 확인 후 3-튜플 언패킹 일괄 수정 |
| `raw_regime` NOT NULL 백필 누락 시 마이그레이션 실패 | 중 | `upgrade()`에서 컬럼 추가 직후 `raw_regime = regime` UPDATE 수행 |
| BULL 조건에 `positive_sector_ratio >= 0.6` 추가로 BULL 빈도 급감 | 중 | acceptance.md에 경계값 시나리오 포함, 백테스트로 영향 모니터링 |
| 히스테리시스가 정당한 빠른 전환까지 억제 | 중 | `confidence >= 0.75` 즉시 적용 + BEAR 비대칭 우회로 보완 |
| `regime_detector_params` 추가가 기존 YAML 로드 깨뜨림 | 저 | Pydantic 필드 기본값 `{}` 부여로 섹션 부재 시 안전 |

---

## 검증 체크리스트 (Verification Checklist)

- [ ] `classify_market_regime()` 반환 타입 불변 확인
- [ ] `_fetch_kospi_indicators()` 모든 호출처 3-튜플 언패킹 반영
- [ ] `raw_regime` 마이그레이션 upgrade/downgrade 양방향 동작
- [ ] BEAR 전환 즉시 적용(히스테리시스 우회) 확인
- [ ] SIDEWAYS 신뢰도 0.5~0.9 범위 보장
- [ ] `regime_detector_params` 부재 시 기본값 폴백 동작
- [ ] SPEC-AI-017 `regime_thresholds` 미변경 확인
- [ ] `pytest -m "not slow"` 통과 + `ruff`/`mypy` 클린
