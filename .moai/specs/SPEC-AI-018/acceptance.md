# SPEC-AI-018 인수 기준 (Acceptance Criteria)

Given-When-Then 형식. 각 요구사항당 최소 2개 시나리오.

---

## REQ-018-001: 섹터 폭(breadth) 지표

### AC-018-001-1: 폭 지표가 추가 반환된다
- **Given** 특정 날짜에 `SectorMomentum` 레코드 10개가 있고 그중 7개의 `avg_return_5d > 0`
- **When** `_fetch_kospi_indicators(db)`를 호출하면
- **Then** 반환은 3-튜플 `(kospi_5d_return, kospi_20d_ma_position, positive_sector_ratio)`이며 `positive_sector_ratio == 0.7`이다

### AC-018-001-2: BULL은 과반 섹터 상승을 요구한다
- **Given** `kospi_5d_return = 2.0`, `kospi_20d_ma_position = 1.0` (기존 BULL 조건 충족)이지만 `positive_sector_ratio = 0.4` (과반 미달)
- **When** `classify_market_regime(2.0, 1.0, positive_sector_ratio=0.4)`를 호출하면
- **Then** 레짐은 BULL이 아닌 SIDEWAYS로 분류된다

### AC-018-001-3: 폭이 낮으면 BEAR로 분류된다
- **Given** `kospi_5d_return = -0.5`, `kospi_20d_ma_position = -0.5` (기존 BEAR 조건 미충족)이지만 `positive_sector_ratio = 0.2` (80% 섹터 하락)
- **When** `classify_market_regime(-0.5, -0.5, positive_sector_ratio=0.2)`를 호출하면
- **Then** 레짐은 BEAR로 분류된다 (`positive_sector_ratio <= 0.3` OR 조건 발동)

### AC-018-001-4: 반환 시그니처는 불변이다
- **Given** 어떤 입력이든
- **When** `classify_market_regime(...)`를 호출하면
- **Then** 반환은 항상 `tuple[MarketRegimeEnum, float]` 2-요소 튜플이다 (요소 수 변경 없음)

---

## REQ-018-002: 레짐 히스테리시스

### AC-018-002-1: 하루짜리 전환은 억제되고 raw_regime에 기록된다
- **Given** DB의 직전 안정 레짐이 SIDEWAYS이고, 오늘 새로 분류된 레짐이 BULL이며 `confidence = 0.65` (< 0.75), 직전 2일 모두 SIDEWAYS
- **When** `get_or_create_today_regime(db)`를 호출하면
- **Then** 저장된 `regime`은 SIDEWAYS(직전 안정값)로 유지되고, `raw_regime`은 BULL로 기록된다

### AC-018-002-2: 2일 연속 동일 분류 시 전환이 적용된다
- **Given** 직전 안정 레짐이 SIDEWAYS이고, 어제와 오늘 raw 분류가 모두 BULL (2일 연속), `confidence = 0.65`
- **When** `get_or_create_today_regime(db)`를 호출하면
- **Then** 저장된 `regime`은 BULL로 교체되고 `raw_regime`도 BULL이다

### AC-018-002-3: 고신뢰도 전환은 즉시 적용된다
- **Given** 직전 안정 레짐이 SIDEWAYS, 오늘 새 분류가 BULL이며 `confidence = 0.80` (>= 0.75), 직전 1일만 BULL raw
- **When** `get_or_create_today_regime(db)`를 호출하면
- **Then** 저장된 `regime`은 BULL로 즉시 교체된다 (신뢰도 우회)

### AC-018-002-4: BEAR 전환은 비대칭으로 즉시 적용된다
- **Given** 직전 안정 레짐이 BULL, 오늘 새 분류가 BEAR이며 `confidence = 0.55` (< 0.75), 직전 BEAR raw 없음 (연속성 미충족)
- **When** `get_or_create_today_regime(db)`를 호출하면
- **Then** 저장된 `regime`은 BEAR로 즉시 적용된다 (자본 보호 우선 비대칭 규칙)

### AC-018-002-5: 첫 분류 시 raw_regime은 regime과 동일하다
- **Given** DB에 직전 `MarketRegime` 레코드가 전혀 없음
- **When** `get_or_create_today_regime(db)`를 호출하면
- **Then** `raw_regime == regime`으로 설정된다

---

## REQ-018-003: SIDEWAYS 동적 신뢰도

### AC-018-003-1: 중간 영역 깊은 곳은 높은 신뢰도를 갖는다
- **Given** `kospi_5d_return = 0.0`, `kospi_20d_ma_position = -1.0` (BULL/BEAR 임계로부터 멀리 떨어진 중간 영역)
- **When** `classify_market_regime(0.0, -1.0, positive_sector_ratio=0.5)`로 SIDEWAYS가 분류되면
- **Then** 신뢰도는 하드코딩 0.6이 아닌, `0.5 + min(d_bull, d_bear) * 0.4` 공식으로 계산된 값이며 0.6보다 크다

### AC-018-003-2: 신뢰도는 0.9를 초과하지 않는다
- **Given** 양쪽 임계로부터 최대로 떨어진 SIDEWAYS 입력 (`min(d_bull, d_bear)`가 1.0에 근접)
- **When** SIDEWAYS 신뢰도가 계산되면
- **Then** 신뢰도는 0.9로 캡되어 0.9를 초과하지 않는다

### AC-018-003-3: 임계 경계 근처는 낮은 신뢰도를 갖는다
- **Given** `kospi_5d_return = 1.4`, `kospi_20d_ma_position = 0.1` (BULL 임계 바로 아래)
- **When** SIDEWAYS가 분류되면
- **Then** 신뢰도는 0.5에 가까운 낮은 값이다 (`d_bull`이 작아 `min(d_bull, d_bear)`이 작음)

---

## REQ-018-004: 레짐별 탐지기 파라미터

### AC-018-004-1: BULL 레짐은 더 민감한 임계값을 사용한다
- **Given** `regime_detector_params.BULL.volume_zscore_threshold = 2.0`이 YAML에 정의됨
- **When** `detect_volume_surge_news_combo(db, config, market_regime="BULL")`를 호출하면
- **Then** 사용되는 거래량 z-score 임계값은 기본값 2.5가 아닌 BULL 전용 2.0이다

### AC-018-004-2: SIDEWAYS는 기본값으로 폴백한다
- **Given** `regime_detector_params`에 SIDEWAYS 항목이 없음 (BULL/BEAR만 정의)
- **When** `detect_volume_surge_news_combo(db, config, market_regime="SIDEWAYS")`를 호출하면
- **Then** `volume_news_combo` 기본값(`volume_zscore_threshold=2.5`, `news_window_hours=24`, `min_news_sentiment=0.3`)이 사용된다

### AC-018-004-3: 미지(unknown) 레짐도 기본값으로 폴백한다
- **Given** `market_regime="NEUTRAL"` (regime_detector_params에 없는 값)
- **When** `detect_volume_surge_news_combo(db, config, market_regime="NEUTRAL")`를 호출하면
- **Then** 예외 없이 `volume_news_combo` 기본값으로 폴백한다

### AC-018-004-4: 설정 섹션 부재 시 안전하게 로드된다
- **Given** `surge_detection.yaml`에 `regime_detector_params` 섹션이 완전히 없는 경우
- **When** `get_surge_config()`로 설정을 로드하면
- **Then** `SurgeDetectionConfig`가 검증 오류 없이 로드되고 `regime_detector_params`는 빈 dict이다

### AC-018-004-5: gather_surge_candidates가 레짐을 전달한다
- **Given** `gather_surge_candidates(db, [], config, [], market_regime="BEAR")` 호출
- **When** 내부에서 `detect_volume_surge_news_combo`가 실행되면
- **Then** `market_regime="BEAR"`가 해당 탐지기에 전달되어 BEAR 전용 파라미터가 적용된다

### AC-018-004-6: 앙상블 임계값은 변경되지 않는다
- **Given** SPEC-AI-017의 `regime_thresholds = {BULL: 0.38, SIDEWAYS: 0.50, BEAR: 0.52}`
- **When** 본 SPEC 구현 후 설정을 로드하면
- **Then** `regime_thresholds` 값은 변경 없이 그대로 유지된다

---

## Definition of Done

- [ ] REQ-018-001~004 모든 AC 시나리오가 테스트로 검증되고 통과한다
- [ ] `classify_market_regime()` 반환 시그니처 `tuple[MarketRegimeEnum, float]` 불변
- [ ] `_fetch_kospi_indicators()` 모든 호출처가 3-튜플로 갱신됨
- [ ] alembic `054` 마이그레이션 upgrade/downgrade 양방향 동작 + 기존 행 백필
- [ ] BEAR 비대칭 즉시 전환 동작 확인
- [ ] SIDEWAYS 신뢰도가 0.5~0.9 범위 내
- [ ] `regime_detector_params` 부재/SIDEWAYS/unknown 폴백 동작
- [ ] SPEC-AI-017 `regime_thresholds` 미변경 확인
- [ ] `cd backend && uv run pytest tests/ -m "not slow" --tb=short -q` 통과
- [ ] `uv run ruff check .` 및 `uv run mypy app/` 클린

## Quality Gate (TRUST 5)

- **Tested**: REQ별 최소 2개 AC, 신규 `test_market_regime.py` + `test_surge_detector.py` 보강, 커버리지 85%+
- **Readable**: 한국어 주석, 명확한 함수/변수명
- **Unified**: ruff/black 포맷 준수, 기존 SQLAlchemy 2.0 스타일 일관
- **Secured**: 외부 입력(섹터 데이터) 분모 0 방어, NOT NULL 제약 백필
- **Trackable**: 커밋 메시지에 SPEC-AI-018 참조, @MX 태그 갱신
