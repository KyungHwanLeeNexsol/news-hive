---
id: SPEC-AI-036
version: 0.1.0
status: draft
created: 2026-06-04
updated: 2026-06-04
author: MoAI
priority: High
issue_number: null
title: fund_signals composite_score 활성화 및 confidence 캘리브레이션
---

# SPEC-AI-036: fund_signals composite_score 활성화 및 confidence 캘리브레이션

## HISTORY

- 2026-06-04 (v0.1.0): 초안 작성. 라이브 DB 분석(2026-06-04)에서 발견된 3대 신호
  품질 문제(composite_score 미적용, confidence 예측력 0, 신호 과다·저품질)를
  근거로 작성. surge_detector.py 코드 검증을 통해 근본 원인 확정. research.md 참조.

---

## 1. Environment (배경)

NewsHive의 급등 매매 시스템은 `surge_detector.py`가 매일 다수의
`signal_type="surge_candidate"` 신호를 생성한다. 2026-06-04 라이브 DB 분석에서
다음 3가지 신호 품질 결함이 확인되었다.

- **결함 1 — composite_score 항상 NULL**: 검증된 428개 행 중 composite_score가
  채워진 행은 0개. 다중 팩터 점수 컬럼이 존재하나 surge 경로에서 한 번도 할당되지
  않는다. (research.md: surge_detector.py의 모든 surge_candidate 생성 지점이
  confidence/surge_metadata만 설정)
- **결함 2 — confidence 예측력 사실상 0**: confidence와 return_pct의 상관계수
  0.0001. 오늘 22개 신호 모두 confidence 0.238~0.280 구간에 밀집. 30일 surge_candidate
  의 69%가 0.25~0.30 구간. 모델이 모든 종목에 거의 동일한 confidence를 부여하여
  랭킹 신호로 무용지물.
- **결함 3 — 신호 과다·저품질**: 30일간 1,165개 surge_candidate (일평균 33개),
  5월 적중률 9%. confidence >= 0.40 신호만 의미 있는 성과(적중률 25%, 평균
  수익률 6.39%)를 보이나 30일간 12개(일평균 0.4개)뿐.

근거 코드 위치 (research.md 상세):
- `backend/app/services/surge_detector.py` — surge_candidate 신호 생성 (composite_score 미할당)
- `backend/app/services/fund_manager.py` — 4개 선행 탐지기 + LLM 신호 경로 (composite_score는 LLM 경로만 할당)
- `backend/app/models/fund_signal.py` — composite_score / factor_scores / confidence 컬럼 정의
- `backend/app/services/signal_verifier.py` — `verify_signals`, 기존 Bayesian `calibrate_confidence`
- `backend/app/services/factor_scoring.py` — `compute_composite_score` (0~100 스케일), `build_factor_scores_json`
- `backend/app/routers/fund_manager.py` — `/api/fund` 라우터

## 2. Assumptions (가정)

- A1. surge_candidate 신호의 팩터 점수(theme_cluster_score, combo_score,
  pattern_score, immediate_disclosure_score, legacy_score)는 신호 생성 시점에
  `SurgeCandidate` 객체와 `surge_metadata`에 이미 존재한다. (research.md 확인)
- A2. `verify_signals`가 5거래일 후 `is_correct`, `return_pct`, `alpha_pct`를
  기록하므로, (confidence, is_correct) 학습쌍을 충분히 확보할 수 있다.
- A3. 백엔드에 numpy / scikit-learn 의존성이 없다. 따라서 isotonic 캘리브레이터는
  순수 Python PAV(Pool Adjacent Violators) 알고리즘으로 구현하거나, 신규 의존성
  추가가 명시적으로 승인되어야 한다. (research.md: pyproject.toml 확인)
- A4. SPEC-AI-029의 적응형 임계값(`surge_threshold_service`, `SurgeThresholdHistory`,
  `combo_zero_theme_floor`)이 운영 중이며, 본 SPEC은 그 위에 floor를 더한다.
- A5. composite_score 컬럼은 LLM 경로에서 0~100 스케일로 기록되어 왔다. surge 경로는
  0.0~1.0 스케일로 기록한다(확률 해석 일관성). 두 스케일 혼재는 신호 품질
  엔드포인트가 `signal_type`별로 분리 보고하여 관리한다. (REQ-036-001, REQ-036-007)

## 3. Requirements (EARS)

### REQ-036-001: surge composite_score / factor_scores 계산 활성화

- **WHEN** `surge_detector`가 `signal_type="surge_candidate"` 신호를 생성하면,
  **THE 시스템 SHALL** 해당 신호의 `composite_score`(0.0~1.0)와 `factor_scores`
  (JSON)를 함께 채운다.
- **THE `composite_score` SHALL** 개별 surge 팩터 점수(theme_cluster_score,
  combo_score, pattern_score, immediate_disclosure_score, legacy_score)의 가중
  결합으로 산출되며, 기존 `compute_ensemble_score`의 정규화 결과를 1차 소스로
  재사용한다.
- **THE `factor_scores` JSON SHALL** 위 개별 팩터 기여도를 키-값으로 포함한다.
- **THE `composite_score` SHALL** 0.0~1.0 범위로 클램핑된다.
- **THE 시스템 SHALL** 모든 surge_candidate 생성 지점(theme/combo/pattern/
  disclosure/cascade/carry 등)에서 동일하게 이 할당을 수행한다.
- **WHERE** 기존 surge_metadata에 surge_probability_score가 이미 있는 경우,
  **THE 시스템 SHALL** composite_score와 surge_probability_score가 동일 소스에서
  파생되어 모순되지 않도록 한다.

### REQ-036-002: confidence 캘리브레이션 (Isotonic Regression)

- **THE 시스템 SHALL** 과거 검증된 (raw_confidence, is_correct) 쌍에 대해
  단조 증가 isotonic 캘리브레이터를 학습한다.
- **WHEN** surge_candidate 신호의 raw confidence가 산출되면, **THE 시스템 SHALL**
  DB에 저장하기 전 캘리브레이터를 적용하여 보정된 confidence를 저장한다.
- **THE 보정된 confidence SHALL** 실제 적중 확률과 단조적으로 일치한다(보정값이
  높을수록 실제 적중률이 같거나 더 높다).
- **WHILE** 학습 표본이 최소 임계치(`min_calibration_samples`, 기본 50) 미만이면,
  **THE 시스템 SHALL** 캘리브레이션을 건너뛰고 raw confidence를 그대로 사용한다.
- **THE 시스템 SHALL** 최근 90일 검증 신호로 주 1회 캘리브레이터를 재학습한다.
- **THE 캘리브레이터 SHALL** 영속화되고(pickle 파일 또는 DB 테이블) 애플리케이션
  시작 시 로드된다.
- **IF** 캘리브레이터 로드 또는 적용이 실패하면, **THEN THE 시스템 SHALL** raw
  confidence로 폴백하고 신호 생성을 중단하지 않는다.
- **THE 시스템 SHALL** isotonic 캘리브레이션을 surge_candidate 경로에만 적용하고,
  LLM 경로의 기존 Bayesian `calibrate_confidence`는 변경하지 않는다.

### REQ-036-003: surge_candidate 최소 품질 floor 상향

- **WHEN** surge_candidate 신호가 생성될 때, **THE 시스템 SHALL** 보정된
  confidence가 `min_calibrated_confidence`(기본 0.35) 이상이거나 composite_score가
  `min_composite_score`(기본 0.60) 이상인 신호만 통과시킨다.
- **IF** 신호가 두 기준을 모두 충족하지 못하면, **THEN THE 시스템 SHALL** 해당
  surge_candidate 신호를 생성하지 않는다(또는 비활성 상태로 기록).
- **THE 품질 floor SHALL** SPEC-AI-029의 적응형 임계값과 함께 적용되며, 둘 중 더
  엄격한 기준이 적용된다(floor는 적응형 임계값을 대체하지 않는다).
- **THE floor 임계값 SHALL** YAML 설정에서 조정 가능하다.

### REQ-036-004: 신호 품질 메트릭 API

- **WHEN** `GET /api/fund/signal-quality` 가 호출되면, **THE 시스템 SHALL**
  다음을 반환한다: confidence 분포(버킷별 카운트), composite_score 채움 비율,
  캘리브레이션 메트릭(Brier score, ECE).
- **THE 응답 SHALL** `signal_type`별로 composite_score 스케일을 구분하여 보고한다
  (surge=0~1, llm=0~100).
- **WHERE** 검증 표본이 부족하면, **THE 시스템 SHALL** 해당 메트릭을 null 또는
  "insufficient_data" 상태로 반환한다(에러 없이).

### REQ-036-005: forward-only 적용 (백필 금지)

- **THE 시스템 SHALL** composite_score가 없는 기존 신호를 소급 백필하지 않는다.
- **WHEN** 신규 신호가 생성되는 시점부터만, **THE 시스템 SHALL** composite_score와
  factor_scores를 채운다.
- **THE 마이그레이션 SHALL** 스키마 변경 없이 동작한다(컬럼이 이미 존재).

### REQ-036-006: 캘리브레이션 학습 데이터 품질 가드

- **THE 시스템 SHALL** 캘리브레이터 학습 시 `is_correct`가 NULL이 아닌(검증 완료된)
  신호만 사용한다.
- **WHILE** 학습 데이터의 양성 비율(is_correct=True 비율)이 0% 또는 100%이면,
  **THE 시스템 SHALL** 캘리브레이션을 건너뛰고 raw confidence를 사용한다(분리 불가).
- **THE 시스템 SHALL** 학습에 사용한 표본 수와 학습 시각을 캘리브레이터 메타데이터에
  기록한다.

### REQ-036-007: composite_score 스케일 일관성

- **THE surge 경로 composite_score SHALL** 항상 0.0~1.0 범위로 기록된다.
- **THE 시스템 SHALL** surge 경로와 LLM 경로의 composite_score를 동일 컬럼에
  서로 다른 스케일로 기록하되, 두 경로를 혼합 집계하지 않는다.
- **IF** 향후 두 스케일 통합이 필요하면, **THEN** 별도 SPEC에서 다룬다(본 SPEC
  범위 외).

### REQ-036-008: 회귀 안전성 (Unwanted Behavior)

- **THE 시스템 SHALL** composite_score/캘리브레이션 도입으로 인해 기존 신호 생성
  파이프라인이 중단되지 않도록 모든 신규 로직을 예외 격리한다(try/except).
- **THE 시스템 SHALL** SPEC-AI-029(적응형 임계값) 및 SPEC-AI-030(combo chase
  guard)의 동작을 변경하지 않는다.
- **THE 시스템 SHALL** LLM 경로(`generate_signal`)의 composite_score/factor_scores/
  confidence 산출 로직을 변경하지 않는다.

## 4. Specifications (측정 기준)

- composite_score 채움 비율: 신규 surge_candidate 신호의 100%가 composite_score를
  가진다(검증 윈도우 내).
- 캘리브레이션 효과: 90일 검증 신호 기준, 보정된 confidence의 Brier score가
  raw confidence 대비 개선되거나 동일하다(악화 금지).
- 단조성: 보정된 confidence 버킷의 적중률이 단조 비감소(상위 버킷 적중률 >= 하위 버킷).
- 신호 수 감소: 품질 floor 적용 후 일평균 surge_candidate 수가 5~10개 범위로
  수렴(기존 33개 대비 감소).
- 예측력 회복: 보정된 confidence와 return_pct의 절대 상관계수가 0.0001(현재)보다
  유의미하게 증가.

## 5. Exclusions (What NOT to Build)

- **백필 금지**: 기존 신호의 composite_score 소급 계산은 하지 않는다(REQ-036-005).
- **LLM 경로 미변경**: `generate_signal()`의 Bayesian calibrate_confidence, 0~100
  스케일 composite_score, build_factor_scores_json 로직은 그대로 둔다(REQ-036-008).
- **SPEC-AI-029 적응형 임계값 재구현 금지**: 본 SPEC은 floor만 추가하며 적응형
  로직 자체는 수정하지 않는다.
- **SPEC-AI-030 combo chase guard 재구현 금지**.
- **신규 탐지기 추가 금지**: 기존 4개 surge 탐지기 + 파생 탐지기를 그대로 사용한다.
- **스케일 통합 금지**: surge(0~1)와 LLM(0~100) composite_score 스케일 통합은
  별도 SPEC(REQ-036-007).
- **intraday 가격/거래량 데이터 사용 금지**: 본 SPEC은 이미 계산된 탐지기 점수만
  사용하며, open_price나 분봉 데이터를 새로 가져오지 않는다.
- **scikit-learn 무조건 도입 금지**: 의존성 추가는 PAV 순수 구현이 부적합할 때만
  명시적 승인 하에 고려한다(A3).
- **프론트엔드 UI 변경 없음**: signal-quality는 모니터링용 백엔드 엔드포인트로만 제공.

## 6. Dependencies

- **SPEC-AI-029** (완료): 적응형 임계값. REQ-036-003의 floor는 이 위에 적층.
- **SPEC-AI-030** (완료/draft): combo chase guard. 충돌 없음.
- **SPEC-AI-012/018** (완료): surge 탐지기 + 앙상블 스코어. composite_score 입력 소스.
- 외부: 없음(신규 외부 서비스 의존 없음). 가능 시 PAV 순수 Python 구현.

## 7. Traceability

| REQ | 검증 (acceptance.md) | 주요 변경 파일 |
|-----|---------------------|----------------|
| REQ-036-001 | AC-1, AC-2 | surge_detector.py, factor_scoring.py |
| REQ-036-002 | AC-3, AC-4, AC-5 | (신규) surge_calibrator.py, signal_verifier.py |
| REQ-036-003 | AC-6, AC-7 | surge_detector.py, surge_settings/yaml |
| REQ-036-004 | AC-8, AC-9 | routers/fund_manager.py, signal_verifier.py |
| REQ-036-005 | AC-10 | surge_detector.py |
| REQ-036-006 | AC-11 | (신규) surge_calibrator.py |
| REQ-036-007 | AC-2, AC-9 | factor_scoring.py |
| REQ-036-008 | AC-12 | 전체 (예외 격리) |
