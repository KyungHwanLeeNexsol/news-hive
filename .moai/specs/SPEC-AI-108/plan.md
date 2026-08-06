# SPEC-AI-108 Plan

## A. 구현 전략

Tier M, cycle_type: ddd(ANALYZE-PRESERVE-IMPROVE — `.moai/config/sections/quality.yaml`
`constitution.development_mode: ddd`). 범위는 spec.md §Goals 1-4에 근거한 순수 읽기
진단(신규 사후 재구성 함수 + 신규 정밀도 집계 함수 + 기존 평가 잡에 격리된 로그
블록 추가)에 한정하며, SPEC-AI-100/101 소유의 판정·영속화 로직, `enabled`/
`shadow_mode_enabled` 실제 값, 앙상블/게이팅/매매 실행 경로는 건드리지 않는다.

핵심 판단(결정 가역성이 높은 순 — 되돌리기 어려운 결정을 먼저 확정):

1. **사후 재구성 함수의 알고리즘 동등성 보장**(spec.md §Decisions D1/D2) —
   가장 되돌리기 어려운 결정이다. 이 함수가 라이브 `compute_horizon_signature()`와
   다른 결과를 낸다면, 이후 축적되는 모든 관측 로그가 처음부터 다시 쌓여야
   한다(로그는 append-only이므로 소급 재계산 불가, 백필 금지 관례상 재작성도
   지양). `surge_basis` 문자열-앙상블 키 정규화 매핑(과거 Open Question 1 —
   `disclosure_pattern`/`immediate_disclosure` 및 `legacy`/`legacy_detectors`
   2건)은 plan-phase에서 코드 대조로 이미 확정했다(spec.md §Context [E-6]) —
   TASK-001은 이 확정 매핑을 그대로 구현에 반영한다.
2. **신규 함수의 데이터 소스 결정**(§Decisions D3 — 재조회 vs 반환값 확장) —
   `_persist_signal_forward_outcomes()` 시그니처를 건드리지 않기로 이미 확정했으나,
   재조회 쿼리의 정확한 필터(trading_date + fund_signal_id IN (...))는 중간
   가역성 — 배포 후 바꾸려면 로그 필드 의미가 달라질 수 있다. TASK-002에서 확정한다.
3. **로그 통합 지점과 필드 스키마**(spec.md REQ-AI108-006) — SPEC-AI-101의 기존
   신호가 기준 EOD 로그 인근에 위치시키는 것은 이미 결정됨(D3). 정확한 로그
   메시지 포맷만 남은 결정.
4. **fail-open 격리 방식**(spec.md REQ-AI108-007) — 기존 잡의 다른 격리 블록과
   동일한 `try/except` 패턴을 재사용하므로 사실상 기계적 결정.
5. **테스트 파일 구성** — 가장 가역성이 높다(테스트 추가/조정은 언제든 반복 가능).

### A.1 PRESERVE 목록(수정 금지)

| 대상 | 사유 |
|------|------|
| `compute_horizon_signature()`(`surge_detector.py`) | REQ-AI108-001 — 사후 재구성은 별개의 신규 함수이며 이 함수 본체는 무수정 |
| `select_effective_threshold()`, `run_horizon_shadow_comparison()`(`surge_detector.py`) | SPEC-AI-100 소유 — 판정 로직 무변경 |
| `check_horizon_transition_readiness()`(`surge_horizon_readiness_service.py`) | SPEC-AI-101 소유 — 본 SPEC은 호출하지도, 수정하지도 않는다(SPEC-AI-106 소관) |
| `_persist_signal_forward_outcomes()`(`surge_evaluation_service.py`) | REQ-AI108-003 — 시그니처/반환값 무변경, 신규 함수가 독립적으로 재조회(§Decisions D3) |
| `evaluate_high_based_outcomes()` | SPEC-AI-093 소유 — 무참조·무수정 |
| `ensemble.horizon_aware_thresholds.enabled`(`false`)/`.shadow_mode_enabled`(`true`) | REQ-AI108-005 — 배포 후에도 값 불변 |
| `ensemble.horizon_aware_thresholds.thresholds`/`horizon_labels` 블록 수치 | 읽기 전용 소비만, 값 자체는 SPEC-AI-100/106 소관 |
| `evaluate_surge_predictions()`의 predicted_set/actual_set/legacy_recall/scannable_recall/high_based_* 산출 로직 | REQ-AI108-001~007 구현은 이 함수 내부에 격리 블록만 추가 — 기존 산출 로직 무변경 |
| `SurgeSignalForwardOutcome`/`SurgeActualOutcome`/`SurgeHorizonShadowObservation` 모델 스키마 | 신규 컬럼/테이블 추가 금지(REQ-AI108-005) |

## B. 작업 분해

### TASK-001: 확정된 `surge_basis` 정규화 매핑 적용 + 사후 재구성 함수 구현

- 대상(확정된 정규화 매핑 — 코드 대조 완료, plan-phase에서 이 세션에 확정됨,
  과거 spec.md Open Question 1): 신호 생성 경로 확인 결과(`surge_detector.py`) —
  `disclosure_pattern` 경로(:1620)는 `active_detectors=["disclosure_pattern"]`을,
  `immediate_disclosure` 경로(:1827)는 `active_detectors=["immediate_disclosure"]`를,
  레거시 탐지기 병합 경로(:2729-2730)는 `active_detectors.append("legacy")`를
  기록한다 — 반면 `compute_horizon_signature()`의 앙상블 키는
  `disclosure_pattern`(:1945, `max(pattern_score, immediate_disclosure_score)`)
  1개와 `legacy_detectors`(:1950, `candidate.legacy_score`) 1개다. **확정된
  정규화 매핑**: `{"immediate_disclosure": "disclosure_pattern", "legacy":
  "legacy_detectors"}`. 나머지 5개 앙상블 키(`theme_cluster`/
  `volume_news_combo`/`news_delayed`/`volume_breakout`/`momentum_continuation`)는
  `surge_basis` 문자열과 1:1 동일하므로 정규화 불필요(surge_detector.py:762,
  963,1309,2235,2589-2590,2600-2601 등에서 확인) — spec.md §Context [E-6]에
  근거를 기록했다.
- 대상(구현): `backend/app/services/surge_evaluation_service.py`에 신규 사설
  함수 `_reconstruct_horizon_signature_from_basis(surge_basis: list[str] | None,
  horizon_labels: dict[str, str]) -> str`를 추가한다. 로직:
  1. `surge_basis`가 `None`이거나 빈 리스트면 `"multi_day_dominant"` 반환
     (`compute_horizon_signature()`의 "발화한 탐지기 없음" 분기와 동등).
  2. 위 확정 매핑으로 `surge_basis`의 각 문자열을 정규화한다(매핑에 없는
     문자열은 원문자열 그대로 유지) — 그 뒤 앙상블 7개 키(`theme_cluster`/
     `volume_news_combo`/`disclosure_pattern`/`legacy_detectors`/`news_delayed`/
     `volume_breakout`/`momentum_continuation`) 집합과의 교집합만 남긴다.
  3. 교집합이 비면 `"multi_day_dominant"`, 남은 키들의 `horizon_labels` 값
     집합이 1개면 `"{label}_dominant"`, 2개 이상이면 `"mixed"`를 반환.
- 순수 함수(DB 접근 없음) — 단위 테스트로 6개 분기(빈 입력/단일 라벨/다중
  라벨/미지 키 무시/`surge_basis=["immediate_disclosure"]` 정규화 동등성/
  `surge_basis=["legacy"]` 정규화 동등성)를 개별 검증한다 — 마지막 2개는
  위 확정 매핑이 실제로 적용되는지 확인하는 회귀 방지 테스트이며, AC-108-002/
  AC-108-003의 동등성 검증 케이스에 나란히 추가한다.
- 추적 REQ/AC: REQ-AI108-001, REQ-AI108-002 / AC-108-001, AC-108-002, AC-108-003

### TASK-002: 지평 시그니처별 정밀도 집계 함수 구현

- 대상: `surge_evaluation_service.py`에 신규 함수
  `_analyze_precision_by_horizon_signature(db: Session, trading_date: date,
  signal_rows: list, horizon_labels: dict[str, str]) -> dict[str, dict]`를
  추가한다.
- 구현:
  1. `signal_rows`(2단계에서 이미 조회됨, `fund_signal_id`/`surge_metadata`
     보유)에서 각 신호의 `surge_basis`를 파싱하고 TASK-001 함수로 지평
     시그니처를 재구성한다.
  2. `trading_date` + `signal_rows`의 `fund_signal_id` 집합으로
     `SurgeSignalForwardOutcome`을 조회해 `forward_max_return_pct`를
     `fund_signal_id`별로 매핑한다(REQ-AI108-003 — `_persist_signal_forward_outcomes()`
     시그니처 무변경, 독립 재조회).
  3. 4개 버킷 각각에 대해 `{signal_count, forward_positive_count,
     precision}`을 계산한다 — `forward_max_return_pct`가 `None`인 신호는
     `signal_count`에는 포함하되 `forward_positive_count` 판정에서는
     False로 취급(양성 아님, 미달성과 동일 취급 — SPEC-AI-101의 기존
     `forward_actual_codes` 판정 로직과 동일 기준).
  4. `signal_count == 0`인 버킷은 `precision=None`(REQ-AI108-004).
- 반환 구조 예시(dict): `{"same_day_dominant": {"signal_count": 3,
  "forward_positive_count": 1, "precision": 0.333}, "next_day_dominant": {...},
  "multi_day_dominant": {...}, "mixed": {...}}`.
- 추적 REQ/AC: REQ-AI108-003, REQ-AI108-004 / AC-108-004, AC-108-005, AC-108-006

### TASK-003: `evaluate_surge_predictions()`에 격리된 로그 블록 배선

- 대상: `evaluate_surge_predictions()`(`surge_evaluation_service.py`) —
  REQ-AI101-001의 `_persist_signal_forward_outcomes()` 호출 직후, 핵심 평가
  결과(`SurgePredictionEvaluation`) `db.commit()` 이전 또는 이후 어느 쪽이든
  가능하나(본 진단은 순수 읽기이므로 커밋 순서에 안전 영향 없음), 기존
  `high_based_*`/`Scannable Recall` 격리 블록과 일관된 위치(핵심 결과 계산
  이후, 부가 진단 블록들과 인접)에 배치한다 — 정확한 라인은 Run 단계에서
  최신 파일 상태로 재확인한다.
- 구현: 기존 격리 블록(`try/except` + 경고 로그, SPEC-AI-086/095/106과 동일
  패턴)으로 TASK-002 함수를 호출하고, 반환된 4버킷 dict를 구조화 INFO 로그
  1줄로 기록한다.
  ```
  try:
      horizon_labels = config.ensemble.horizon_aware_thresholds.horizon_labels
      horizon_precision = _analyze_precision_by_horizon_signature(
          db, trading_date, signal_rows, horizon_labels
      )
      logger.info(
          "[지평시그니처정밀도] %s",
          {k: v for k, v in horizon_precision.items()},
      )
  except Exception as _hpe:
      logger.warning("[지평시그니처정밀도] 진단 실패 (무시): %s", _hpe)
  ```
- 이 블록은 REQ-AI108-007에 따라 핵심 평가 결과 계산/커밋 및 REQ-AI101-001/002의
  upsert에 어떤 영향도 주지 않아야 한다.
- 추적 REQ/AC: REQ-AI108-006, REQ-AI108-007 / AC-108-007, AC-108-008

### TASK-004: characterization 테스트 + 회귀 검증

- 신규: `test_spec_ai_108.py` —
  - TASK-001 순수 함수 4개 분기 단위 테스트.
  - TASK-002 집계 함수: 고정 fixture(4개 버킷에 각각 다른 `forward_max_return_pct`
    분포)로 정밀도 값 검증 + `signal_count=0` 버킷의 `precision=None` 검증.
  - TASK-003 배선: 정상 호출 시 로그 필드 확인, 예외 주입 시 핵심 평가 결과
    커밋 보존 확인(`SurgePredictionEvaluation` 행 정상 생성).
- 회귀: `uv run pytest tests/test_spec_ai_100.py tests/test_spec_ai_101.py
  tests/test_spec_ai_095.py tests/test_surge_evaluation_service.py -q` 전체
  통과 확인 — SPEC-AI-100/101/095 판정 로직 및 기존 `evaluate_surge_predictions()`
  핵심 산출 로직에 diff 0.
- 추적 REQ/AC: REQ-AI108-002, REQ-AI108-005 / AC-108-009, AC-108-010

## C. 증거 활용 절차 (REQ-AI108-008 산출물)

본 절차는 이 진단이 축적한 관측 데이터를 향후 두 결정에 활용하는 방법을
문서화한다. 본 SPEC은 이 절차를 문서화만 하며 실행하지 않는다(§Non-Goals).

1. **최소 관측 기간 확인**: 배포 이후 journalctl에서
   `[지평시그니처정밀도]` 태그로 로그를 검색해(예: `journalctl -u newshive |
   grep '지평시그니처정밀도'`) 각 버킷의 누적 `signal_count`를 확인한다.
   일 예측 건수가 3~9건 수준(project-surge-spec-status 메모리)이므로, 4개
   버킷으로 분산되면 개별 버킷이 통계적으로 의미 있는 표본(예: 각 버킷
   `signal_count >= 20`)에 도달하기까지 여러 주 관측이 필요할 수 있다 —
   정확한 최소 표본 기준은 spec.md Open Question 3이 미해결로 남긴다.
2. **SPEC-AI-100 Open Question 2(지평별 임계값 수치) 판단 시 참고 방법**:
   버킷 간 `precision` 격차가 유의하게 관측되면(예: `same_day_dominant`
   정밀도가 `multi_day_dominant` 대비 뚜렷이 다름), 이는 두 지평이 실제로
   다른 신뢰도 프로파일을 가진다는 증거이며 `thresholds` 블록의 placeholder
   값을 지평별로 분화할 근거가 된다. 격차가 관측되지 않으면(모든 버킷의
   정밀도가 통계적 노이즈 범위 내에서 유사), 이는 SPEC-AI-100 D1이 채택한
   "지평 태깅형 단일 파이프라인"으로 충분하며 임계값 분화 자체가 불필요할
   수 있다는 증거다 — 두 결론 모두 유효한 결과이며, 이 SPEC은 어느 쪽도
   전제하지 않는다.
3. **SPEC-AI-100 §Decisions D1("완전 분리 기각") 재검토 시 참고 방법**: 만약
   버킷 간 정밀도 격차가 극단적으로 크고 지속적으로 관측되며, 동시에 위 2항의
   임계값 분화만으로는 그 격차를 좁힐 수 없다는 것이 (임계값 분화를 실제로
   시도한 이후) 별도로 확인되면, 그때 비로소 D1의 "완전 분리 기각" 결정을
   재검토할 근거가 성립한다. 이 SPEC의 관측 데이터 단독으로는 재검토 근거가
   되지 않는다 — 임계값 분화 시도 자체가 먼저 있어야 한다(순서: 본 SPEC의
   측정 → Open Question 2 임계값 튜닝 시도 → 그래도 부족하면 D1 재검토).
4. **본 SPEC이 내리지 않는 결정**: 위 2항/3항 모두 사람이 검토해 내리는
   판단이며, 이 진단의 로그 출력이 임계값이나 아키텍처를 자동으로 바꾸는
   일은 없다(REQ-AI108-005).

## D. 위험

| 위험 | 완화 |
|------|------|
| `surge_basis` 문자열-앙상블 키 정규화 매핑(`disclosure_pattern`/`immediate_disclosure` 및 `legacy`/`legacy_detectors` 2건)을 TASK-001 구현에서 누락하면 재구성된 지평 시그니처가 조용히 부정확할 위험 | plan-phase에서 신호 생성 경로 코드를 직접 대조해 두 매핑 모두 확정(spec.md §Context [E-6]), TASK-001 구현에 명시적으로 반영, 단위 테스트로 `surge_basis=["immediate_disclosure"]`/`surge_basis=["legacy"]` 정규화 동등성을 AC-108-002/003 케이스에 나란히 개별 검증 |
| 일 예측 건수가 적어(3~9건) 4버킷 분산 시 조기 관측 기간 동안 대부분 버킷이 `signal_count` 낮음/0에 머물 위험 | REQ-AI108-004 None 가드로 안전 처리, §C 1항에 "통계적으로 의미 있는 표본까지는 여러 주 소요될 수 있다"를 명시 |
| 신규 재조회 쿼리(`SurgeSignalForwardOutcome`)가 예측 건수 대비 과도한 부하를 유발할 위험 | 예측 건수가 일 3~9건 수준이라 쿼리 결과 행 수가 사실상 무시 가능(≤10행) — 별도 배치/캐싱 불필요 |
| 이 진단 배선이 REQ-AI101-001/002의 신호가 기준 EOD 최대수익률 upsert 로직과 충돌할 위험 | 이 진단은 순수 읽기(신규 쓰기 없음)이며 `_persist_signal_forward_outcomes()` 완료 이후에만 실행되도록 배선(TASK-003), 예외 격리로 REQ-AI108-007 보장 |
| SPEC-AI-106(같은 잡에 다른 진단 블록 추가)과 동시에 개발될 경우 코드 병합 충돌 가능성 | 두 SPEC은 서로 다른 데이터를 다루는 독립 블록이며 어느 순서로 배포되어도 충돌하지 않음(spec.md §Decisions D3) — 병합 시 두 블록을 나란히 추가하는 것으로 충분, 상호 의존 없음 |
