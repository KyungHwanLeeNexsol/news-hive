# Acceptance Criteria: SPEC-AI-036

EARS-aligned, Given-When-Then scenarios. Every criterion is observable
(DB state, API response, test output, metric threshold).

## REQ-036-001 / 007 — composite_score / factor_scores 활성화

### AC-1: 신규 surge_candidate는 composite_score를 가진다
- **GIVEN** surge 탐지기가 실행되고 후보가 자격을 통과했을 때
- **WHEN** `signal_type="surge_candidate"` 신호가 생성되어 DB에 커밋되면
- **THEN** 해당 행의 `composite_score IS NOT NULL` 이고 `factor_scores IS NOT NULL`
- **AND** 신규 생성 신호 100%가 composite_score를 가진다(검증 윈도우 집계).

### AC-2: composite_score는 0.0~1.0 범위이며 ensemble과 일관
- **GIVEN** 생성된 surge_candidate 신호
- **WHEN** composite_score를 읽으면
- **THEN** `0.0 <= composite_score <= 1.0`
- **AND** `factor_scores` JSON은 theme_cluster/combo/pattern/immediate_disclosure/
  legacy 점수 키를 포함
- **AND** composite_score는 `surge_metadata.surge_probability_score`와 동일 소스에서
  파생되어 모순되지 않는다(차이 < 1e-6 또는 동일 산식).

## REQ-036-002 / 006 — isotonic 캘리브레이션

### AC-3: 캘리브레이터는 단조 증가 함수를 학습한다
- **GIVEN** (raw_confidence, is_correct) 학습쌍 N >= 50개
- **WHEN** `train_isotonic(pairs)`를 실행하면
- **THEN** 반환된 모델의 predict는 단조 비감소: `raw_a <= raw_b ⇒ predict(raw_a) <= predict(raw_b)`
- **AND** 출력은 [0.0, 1.0] 범위.

### AC-4: 표본 부족 시 raw confidence 폴백
- **GIVEN** 검증 신호가 `min_calibration_samples`(50) 미만
- **WHEN** 신호의 confidence를 보정하려 하면
- **THEN** raw confidence가 변경 없이 사용된다
- **AND** 신호 생성은 정상 진행된다(에러/중단 없음).

### AC-5: 캘리브레이터 영속화 및 시작 시 로드
- **GIVEN** 캘리브레이터가 학습·저장된 상태
- **WHEN** 애플리케이션이 재시작되면
- **THEN** 저장된 캘리브레이터가 로드되어 적용된다
- **AND** 로드 실패 시 identity(raw) 폴백으로 신호 생성이 계속된다.

## REQ-036-003 — 품질 floor 게이트

### AC-6: floor 미달 신호는 생성되지 않는다
- **GIVEN** floor 설정 `min_calibrated_confidence=0.35`, `min_composite_score=0.60`
- **WHEN** 후보의 보정 confidence가 0.30이고 composite_score가 0.50이면
- **THEN** 해당 surge_candidate 신호는 생성되지 않는다(또는 비활성 기록).

### AC-7: floor와 SPEC-AI-029 적응형 임계값 중 더 엄격한 기준 적용
- **GIVEN** SPEC-AI-029 적응형 임계값이 0.40, 본 floor가 0.35일 때
- **WHEN** 보정 confidence 0.37 후보를 평가하면
- **THEN** 적응형 임계값(0.40)이 더 엄격하므로 신호가 생성되지 않는다
- **AND** `surge_threshold_service`의 로직은 수정되지 않는다(호출만).

## REQ-036-004 / 007 — signal-quality API

### AC-8: 엔드포인트가 품질 메트릭을 반환한다
- **GIVEN** 검증된 신호가 충분히 존재할 때
- **WHEN** `GET /api/fund/signal-quality` 를 호출하면
- **THEN** 응답은 confidence 분포, composite_score 채움 비율, Brier score, ECE를 포함
- **AND** HTTP 200.

### AC-9: composite_score 스케일은 signal_type별로 분리 보고
- **GIVEN** surge(0~1)와 LLM(0~100) 신호가 공존
- **WHEN** signal-quality 응답을 읽으면
- **THEN** composite_score 메트릭이 `signal_type`별로 스케일을 구분해 보고된다
- **AND** 두 스케일이 한 메트릭으로 혼합 집계되지 않는다.

## REQ-036-005 — forward-only

### AC-10: 기존 NULL 신호는 백필되지 않는다
- **GIVEN** composite_score가 NULL인 과거 신호들
- **WHEN** 본 기능이 배포되어 신규 신호가 생성된 뒤
- **THEN** 과거 신호의 composite_score는 여전히 NULL이다(소급 변경 없음)
- **AND** 스키마 마이그레이션이 수행되지 않는다(컬럼 기존재).

## REQ-036-006 — 학습 데이터 품질 가드

### AC-11: 분리 불가 데이터에서 캘리브레이션 건너뜀
- **GIVEN** 학습 데이터의 is_correct가 전부 True(양성 비율 100%)
- **WHEN** 캘리브레이터를 학습하려 하면
- **THEN** 캘리브레이션을 건너뛰고 raw confidence를 사용한다
- **AND** 캘리브레이터 메타데이터에 sample_count와 trained_at(또는 skip 사유)이 기록된다.

## REQ-036-008 — 회귀 안전성

### AC-12: 신규 로직 실패가 신호 파이프라인을 중단시키지 않는다
- **GIVEN** composite_score 산출 또는 캘리브레이션 적용 중 예외가 발생
- **WHEN** surge 탐지기가 신호를 생성하면
- **THEN** 예외는 격리되고(try/except) 나머지 신호 생성은 계속된다
- **AND** SPEC-AI-029/030 및 LLM 경로(`generate_signal`)의 동작은 변경되지 않는다
  (해당 경로의 기존 테스트가 모두 통과).

## Edge Cases

- 동일 종목에 복수 탐지기가 동시 후보를 올리는 경우 → composite_score는 최고
  소스 기준으로 일관되게 채워진다(중복 행 모순 없음).
- 검증된 신호가 정확히 50개(경계값) → 캘리브레이션이 활성화된다(>= 비교).
- composite_score 입력이 모두 0 → composite_score=0.0, floor에서 탈락(정상).
- 캘리브레이터 pkl 파일 손상 → identity 폴백, 로그 경고, 신호 생성 지속.
- signal-quality 호출 시 검증 신호 0건 → `insufficient_data` 상태 반환, HTTP 200.

## Quality Gate / Definition of Done

- [ ] AC-1~AC-12 전부 통과 (pytest 출력으로 증빙)
- [ ] `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"` 통과
- [ ] `cd backend && uv run ruff check .` 무경고
- [ ] `cd backend && uv run mypy app/` 통과
- [ ] 신규 surge_candidate composite_score 채움 비율 100% (검증 윈도우)
- [ ] 보정 confidence Brier score가 raw 대비 악화되지 않음
- [ ] 보정 confidence 버킷 적중률 단조 비감소
- [ ] 품질 floor 적용 후 일평균 surge_candidate 수가 5~10 범위로 수렴(샘플 검증)
- [ ] SPEC-AI-029/030 및 LLM 경로 기존 테스트 회귀 없음
- [ ] 스키마 마이그레이션 미수행(컬럼 기존재) 확인
- [ ] `GET /api/fund/signal-quality` 응답 스키마 검증

## Test Strategy

- **단위 테스트** (`test_surge_calibrator.py`, 신규): PAV 단조성, [0,1] 클램핑,
  표본 부족 폴백, 분리 불가(0%/100%) 스킵, pickle 저장/로드/손상 폴백.
- **단위 테스트** (`test_surge_detector.py`, 확장): surge_candidate 생성 시
  composite_score/factor_scores 채움, floor 게이트 통과/탈락, 예외 격리.
- **통합 테스트**: floor + SPEC-AI-029 적응형 임계값 동시 적용 시 더 엄격한 기준 적용.
- **API 테스트**: `/api/fund/signal-quality` 200 응답, signal_type별 스케일 분리,
  insufficient_data 경계.
- **회귀 테스트**: LLM 경로(`generate_signal`)와 SPEC-AI-029/030 기존 테스트 무변경 통과.
