---
id: SPEC-AI-050
version: 0.1.0
status: draft
created: 2026-06-17
updated: 2026-06-17
---

# SPEC-AI-050 인수 기준 (Acceptance Criteria)

각 시나리오는 Given-When-Then 형식이며, 단위 테스트로 검증 가능하도록
구체적 입력값·기대 출력을 명시한다. 모든 테스트는
`backend/tests/` 하위 `test_spec_ai_050_*.py` 로 작성한다.

---

## REQ-1: 요일 기반 동적 news_window_hours

### AC-1.1 (월요일 윈도우 확장 — 정상 케이스)
- **Given** 설정 레짐 news_window_hours = 12, 실행 시각이 2026-06-15(월) 10:00 KST
- **When** `_resolve_dynamic_news_window(base_hours=12, run_dt=2026-06-15T10:00 KST)` 호출
- **Then** 반환값 = `min(72, 12*4)` = 48
- **And** "동적 윈도우 확장 적용: 12h → 48h" 로그가 기록된다

### AC-1.2 (일반 거래일 — 확장 없음)
- **Given** 설정 레짐 news_window_hours = 24, 실행 시각이 2026-06-17(수) 10:00 KST
  (직전 거래일 = 화요일, 역일 차 1)
- **When** `_resolve_dynamic_news_window(base_hours=24, run_dt=...)` 호출
- **Then** 반환값 = 24 (확장 없음)
- **And** 확장 로그가 기록되지 않는다

### AC-1.3 (연휴 직후 — 직전 거래일 2역일 이상)
- **Given** 직전 거래일이 실행일 기준 3 역일 이전(예: 임시공휴일 포함 연휴 직후),
  설정 news_window_hours = 12
- **When** `_resolve_dynamic_news_window` 호출
- **Then** 반환값 = 48 (`min(72, 12*4)`)

### AC-1.4 (탐지기 주입 통합)
- **Given** market_regime="BEAR", 실행일 월요일, 6/13(금) 22:00 KST 에 긍정 뉴스
  종목 A 존재 (전통 12h 윈도우 밖, 48h 윈도우 안)
- **When** `detect_volume_surge_news_combo(db, config, "BEAR")` 실행
- **Then** 종목 A 의 금요일 뉴스가 news_cutoff 안에 포함되어 positive_news_stocks
  에 A 가 들어간다 (전통 12h 였다면 누락)

---

## REQ-2: BEAR 레짐 news_window_hours 완화

### AC-2.1 (YAML 값 검증)
- **Given** 변경된 surge_detection.yaml
- **When** `get_surge_config().regime_detector_params["BEAR"].news_window_hours` 조회
- **Then** 값 = 24 (이전 12 아님)

### AC-2.2 (24 미만 클램프)
- **Given** BEAR.news_window_hours 를 18 로 설정 시도 (운영자 또는 자가개선)
- **When** 설정 적용 검증 로직 실행
- **Then** 값이 24 로 클램프된다
- **And** "BEAR news_window_hours 24 미만 시도 → 24 클램프" 경고 로그 기록

---

## REQ-3: 자가개선 루프 레짐 윈도우 확장

### AC-3.1 (recall=0 3일 지속 → 윈도우 +12h)
- **Given** 최근 5일 SurgePredictionEvaluation 의 recall 이 [0,0,0,x,x] 이고
  직전 3일 detector contribution 합 = 0, 활성 레짐 BEAR.news_window_hours = 24
- **When** `analyze_and_improve(db, trading_date)` 실행
- **Then** `regime_detector_params.BEAR.news_window_hours` 가 36 으로 패치된다
- **And** SurgeAutoImprovementLog 에 parameter_path=
  "regime_detector_params.BEAR.news_window_hours", old=24, new=36 기록
- **And** `reload_surge_config()` 가 호출되어 캐시가 무효화된다

### AC-3.2 (윈도우 상한 48h)
- **Given** BEAR.news_window_hours = 48, recall=0 3일 지속
- **When** `analyze_and_improve` 실행
- **Then** news_window_hours 가 변경되지 않는다 (48 유지)
- **And** "윈도우 상한 48h 도달" 로그 기록
- **And** 윈도우 관련 SurgeAutoImprovementLog 가 생성되지 않는다

### AC-3.3 (recall 회복 시 윈도우 미조정)
- **Given** 롤링 5일 recall 평균 > 0 (예: 0.3)
- **When** `analyze_and_improve` 실행
- **Then** news_window_hours 는 변경되지 않는다 (기존 min_score 조정 로직만 동작)

### AC-3.4 (R12 롤백 호환)
- **Given** AC-3.1 로 윈도우가 +12h 조정된 다음날, prev_recall < rolling_avg*0.80
- **When** `analyze_and_improve` 실행
- **Then** 윈도우 조정 로그가 R12 롤백 대상에 포함되어 old_value 로 복원된다

---

## REQ-4: group_cascade 정밀도 가드

### AC-4.1 (저확률 단독 cascade 차단)
- **Given** flagship_prob=0.50, decay_factor=0.7 → 유효 신뢰도 0.35 (< 0.4),
  cascade 종목 X 에 당일 group_cascade 외 시그널 없음
  (`existing_today[X.stock_id]` = {"group_cascade"} 또는 비어있음)
- **When** `detect_group_cascade_signals(db, surge_results, config)` 실행
  (require_companion_detector=True)
- **Then** 종목 X 에 대한 cascade surge_candidate 신호가 생성되지 않는다
- **And** "companion 가드 차단: 1건" 로그 기록

### AC-4.2 (저확률이나 동반 탐지기 존재 → 허용)
- **Given** 유효 신뢰도 0.35 (< 0.4), 종목 X 에 당일 theme_cluster 시그널 존재
  (`existing_today[X.stock_id]` 에 "surge_candidate" 등 group_cascade 외 type)
- **When** `detect_group_cascade_signals` 실행
- **Then** 종목 X 에 cascade 신호가 생성된다 (동반 탐지기 보강으로 통과)

### AC-4.3 (고확률 단독 cascade → 허용)
- **Given** flagship_prob=0.70, decay_factor=0.7 → 유효 신뢰도 0.49 (>= 0.4),
  동반 탐지기 없음
- **When** `detect_group_cascade_signals` 실행
- **Then** 종목 X 에 cascade 신호가 생성된다 (기존 동작 유지)

### AC-4.4 (가드 비활성 시 레거시 동작)
- **Given** require_companion_detector=False
- **When** `detect_group_cascade_signals` 실행
- **Then** 유효 신뢰도와 무관하게 SPEC-AI-027 기존 동작대로 신호가 생성된다

---

## REQ-5: weekend_gap_up 신규 탐지기

### AC-5.1 (이력+테마 매칭 종목 탐지)
- **Given** 실행일 월요일, 종목 Y 가 최근 10거래일 내 surge_actual_outcome 에서
  was_surge=True, Y 의 섹터가 최근 뉴스 활성 테마와 매칭
- **When** `detect_weekend_gap_up_signals(db)` 실행
- **Then** 종목 Y 에 signal_type="surge_candidate",
  surge_metadata.surge_basis 에 "weekend_gap_up" 포함된 신호가 생성된다

### AC-5.2 (이력 없음 → 미탐지)
- **Given** 종목 Z 가 최근 10거래일 내 was_surge=True 기록 없음
- **When** `detect_weekend_gap_up_signals` 실행
- **Then** 종목 Z 에 weekend_gap_up 신호가 생성되지 않는다

### AC-5.3 (테마 불일치 → 미탐지)
- **Given** 종목 W 가 was_surge=True 이나 섹터가 활성 테마와 불일치
- **When** `detect_weekend_gap_up_signals` 실행
- **Then** 종목 W 에 신호가 생성되지 않는다

### AC-5.4 (요일 가드 — 일반 거래일 비활성)
- **Given** 실행일이 수요일(직전 거래일 1역일 전), 조건 만족 종목 Y 존재
- **When** weekend_gap_up 활성화 판정
- **Then** 탐지기가 비활성화되어 신호를 생성하지 않는다 (REQ-1 동일 가드)

### AC-5.5 (앙상블 가중치 합산 무결성)
- **Given** weekend_gap_up 가중치 신설, legacy_detectors 재배분
- **When** `validate_ensemble_weights(config.ensemble.weights)` 실행
- **Then** 모든 가중치 합 == 1.0 (±0.001) 통과
- **And** EnsembleWeightsConfig 가 weekend_gap_up 필드를 포함한다

---

## 엣지 케이스 (Edge Cases)

- **EC-1**: 실행 시각이 토요일/일요일 (스케줄 오작동) → 동적 윈도우는 적용되나
  거래 미발생. 신호 생성만 되고 매수 미실행. 오류 없이 처리.
- **EC-2**: surge_actual_outcome 가 비어있음(신규 배포 직후) → weekend_gap_up
  는 빈 목록 반환, 예외 없음.
- **EC-3**: 자가개선이 윈도우와 min_score 를 같은 날 동시 조정 → 두 dot-path
  패치가 독립적으로 적용되고 reload 1회 호출.
- **EC-4**: companion 가드와 max_cascade_per_flagship 동시 적용 → 가드 통과
  종목만 max 카운트에 반영.
- **EC-5**: 배포 직후 YAML 리셋으로 윈도우가 커밋값(24)으로 복원 → 다음
  recall=0 3일 후 자가개선이 재조정. 회귀 아님(설계대로).

---

## 품질 게이트 (Quality Gates)

- [ ] `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"` 통과
- [ ] `cd backend && uv run ruff check .` 통과
- [ ] `cd backend && uv run python -c "from app.main import app; print('OK')"` 통과
- [ ] `validate_ensemble_weights` 합산 1.0 검증
- [ ] 신규 코드 테스트 커버리지 85%+ (REQ-1~5 각 핵심 함수)
- [ ] @MX 태그: 신규 YAML 자동패치/가드 함수에 @MX:WARN + @MX:REASON

## Definition of Done

- [ ] REQ-1~5 의 모든 AC 시나리오가 통과하는 테스트 존재
- [ ] surge_detection.yaml 변경분이 합산 1.0 / int 포맷 유지로 적용됨
- [ ] 배포 시 YAML 리셋 위험이 plan.md 에 기록되고 운영자에게 고지됨
- [ ] group_cascade companion 가드로 2026-06-15 유형 단독 cascade 차단 재현
- [ ] 월요일 시나리오에서 6/16 미포착 47종목 유형(이력+테마)이 weekend_gap_up
      또는 확장 윈도우로 최소 1종목 이상 포착됨을 통합 테스트로 입증
