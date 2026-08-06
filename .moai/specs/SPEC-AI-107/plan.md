# SPEC-AI-107 Plan

## A. 구현 전략

Tier M, cycle_type: ddd(ANALYZE-PRESERVE-IMPROVE — `.moai/config/sections/quality.yaml`
`constitution.development_mode: ddd`). 범위는 spec.md §Goals 1-6에 근거한 섀도우
학습 파이프라인 신설(walk-forward 분할 + Brier 게이트 + 파일 기반 실행 로그) +
`train_isotonic()`의 하위 호환 확장 + 스케줄러 배선 + 프로모션/롤백 절차 문서화에
한정하며, `fund_manager.py`의 품질 floor 게이트 로직, `signal_verifier.py`의
Bayesian 캘리브레이션, active `data/surge_calibrator.pkl`의 실제 교체는 건드리지
않는다.

핵심 판단(결정 가역성이 높은 순 — 되돌리기 어려운 결정을 먼저 확정):

1. **영속화 스킴(candidate 디렉토리 구조 + 실행 로그 스키마)** — 가장 되돌리기
   어려운 결정이다. 첫 실행 이후 파일 경로나 로그 필드 스키마를 바꾸면 이미 쌓인
   관측 이력과의 호환성이 깨진다. active 경로(`data/surge_calibrator.pkl`)는
   무변경 유지하고, candidate는 `data/surge_calibrator/candidate_{YYYYMMDD}.pkl`,
   실행 로그는 `data/surge_calibrator/runs.jsonl`(append-only)로 확정한다 —
   TASK-002에서 구현.
2. **`train_isotonic()` 시그니처 확장 방식**(spec.md REQ-AI107-007) — 배포 후
   바꾸면 기존 6개 AC 테스트(`test_surge_calibrator.py`)의 회귀 위험이 생기므로
   중간 가역성. 신규 선택적 인자 `min_positive_samples: int | None = None`(기본값
   생략 시 기존 동작과 완전 동일)으로 확정 — §Decisions D4.
3. **최소 positive 표본 floor의 잠정값** — 관측 데이터를 본 뒤 조정 가능하므로
   가역성이 높다. 잠정값 `15`로 시작한다(근거: PAV가 신뢰할 만한 단조 곡선을
   형성하려면 최소 여러 개의 서로 다른 breakpoint가 필요하며, `_run_pav`의 병합
   로직 특성상 positive 5개 미만에서는 사실상 단일 블록으로 붕괴할 가능성이 높다
   — 15는 보수적 시작값이며 후속 세션에서 실제 분포를 보고 조정 가능, spec.md
   Open Question 2).
4. **walk-forward holdout 비율** — `holdout_fraction=0.3`(최근 30%를 검증 구간으로
   사용)으로 시작한다. 표본이 매우 적을 때(예: 50개 근처) holdout이 15개로
   지나치게 작아지는 문제가 있으나, 이는 애초에 REQ-AI107-004의 "데이터 부족" 경로가
   흡수한다 — 최소 표본 floor(50)를 통과한 표본이라면 holdout 15개는 Brier 점수
   비교의 최소 신뢰도를 제공한다고 판단한다(§Open Questions 3, 조정 가능).
5. **스케줄러 배선 시점(cron 스케줄)** — 가장 가역성이 높다(cron 시각은 배포 후
   설정 변경만으로 조정 가능). 매주 일요일 03:00 KST — 기존 `relation_inference`
   잡(일요일 04:00 KST)과 겹치지 않는 저부하 시간대.
6. **테스트 파일 구성** — 가장 가역성이 높다(반복 조정 가능).

### A.1 PRESERVE 목록(수정 금지)

| 대상 | 사유 |
|------|------|
| `_run_pav()`, `IsotonicModel.predict()`(`surge_calibrator.py`) | SPEC-AI-036 소유 — PAV 알고리즘 자체는 재구현하지 않는다(REQ-AI107 범위는 학습 데이터 준비·게이팅·영속화이지 알고리즘 변경이 아님) |
| `data/surge_calibrator.pkl`(active 경로)의 실제 파일 내용 | REQ-AI107-002 — 섀도우 학습 실행이 이 파일을 절대 덮어쓰지 않는다 |
| `fund_manager.py:1439-1481`의 품질 floor 게이트 로직/임계값(`min_calibrated_confidence`, `min_composite_score`) | §Non-Goals — SPEC-AI-036 소유, 무수정 |
| `signal_verifier.py:487-535`의 Bayesian `calibrate_confidence(raw_confidence, accuracy_stats)` | §Non-Goals — 별개 시스템, 무수정 |
| `signal_verifier.py:538-568`의 기존 `get_surge_calibration_pairs()` 시그니처/반환 형태 | TASK-001은 이 함수를 대체하지 않고 시간 정보를 포함한 신규 함수를 추가만 한다 — 기존 호출부(`retrain_calibrator()`)는 무수정 |
| `train_isotonic()`을 `min_positive_samples` 인자 없이 호출하는 기존 코드/테스트 경로 | REQ-AI107-007 — 바이트 단위 동일 동작 유지 |

## B. 작업 분해

### TASK-001: 시간 인지형 캘리브레이션 페어 조회 함수 추가

- 대상: `backend/app/services/signal_verifier.py`.
- 구현: 기존 `get_surge_calibration_pairs(db, lookback_days=90)` 옆에 신규
  `get_surge_calibration_pairs_with_time(db, lookback_days=90) ->
  list[tuple[float, int, datetime]]`를 추가한다. 쿼리는 기존 함수와 동일한 필터
  (`signal_type=="surge_candidate"`, `is_correct is not None`,
  `verified_at is not None`, `created_at >= cutoff`)를 사용하되
  `FundSignal.confidence, FundSignal.is_correct, FundSignal.created_at` 3개
  컬럼을 select한다. 기존 함수는 무수정 — walk-forward 분할에 필요한 시간
  정보만 추가로 노출하는 sibling 함수다.
- 추적 REQ/AC: REQ-AI107-001 / AC-107-001

### TASK-002: walk-forward 분할 + Brier 게이트 + candidate 영속화 + 실행 로그

- 대상: `backend/app/services/surge_calibrator.py`.
- 구현 항목:
  1. `_CANDIDATE_DIR = Path(__file__).parent.parent.parent / "data" / "surge_calibrator"`,
     `_RUN_LOG_PATH = _CANDIDATE_DIR / "runs.jsonl"` 경로 상수 추가.
  2. `split_walk_forward(triples, holdout_fraction=0.3) ->
     tuple[list[tuple[float,int]], list[tuple[float,int]]]` — `created_at`
     기준 오름차순 정렬 후 마지막 `holdout_fraction` 비율을 holdout으로 분리,
     나머지를 학습 세트로 반환(둘 다 `(raw, is_correct)` 형태로 축약).
  3. `compute_brier_score(pairs: list[tuple[float,int]]) -> float` — 순수
     Python `sum((p - a) ** 2 for p, a in pairs) / len(pairs)`.
  4. `train_isotonic()`에 `min_positive_samples: int | None = None` 인자를
     추가한다 — `None`이면 기존 동작과 완전 동일, 값이 설정되면 기존 표본 수
     미달/불균형 체크 이후 추가로 `n_pos < min_positive_samples`일 때도
     identity fallback을 반환한다(§Decisions D4).
  5. `@dataclass ShadowTrainingRun`: `run_date: str`, `sample_count: int`,
     `positive_count: int`, `sufficient_data: bool`, `brier_raw: float | None`,
     `brier_calibrated: float | None`, `gate_passed: bool`,
     `candidate_path: str | None`.
  6. `run_shadow_training(db, min_calibration_samples: int | None = None,
     min_positive_samples: int = 15, holdout_fraction: float = 0.3) ->
     ShadowTrainingRun` — 오케스트레이션 함수:
     - `min_calibration_samples`가 `None`이면 `surge_config.min_calibration_samples`를
       읽어 지역 변수 `floor`에 대입한다(REQ-AI107-009 — settings import는 함수
       내부에서 지연 임포트, 기존 모듈의 순환 임포트 회피 관례를 따른다). `None`이
       아니면 전달된 값을 그대로 `floor`로 사용한다.
     - `get_surge_calibration_pairs_with_time(db)` 호출 → 표본 수/positive 수 계산.
     - 표본 수 < `floor` OR positive 수 < `min_positive_samples`이면
       `sufficient_data=False`로 즉시 반환(REQ-AI107-004) — candidate 저장/Brier
       계산 생략.
     - 충분하면 `split_walk_forward()` → 학습 세트로 **`train_isotonic(training_set,
       min_calibration_samples=floor, min_positive_samples=min_positive_samples)`를
       두 키워드 인자 모두 명시적으로 전달해 호출한다.** 이 호출에서 `floor`를
       생략(또는 미전달)하면 `train_isotonic()`은 자신의 독립적인 기본값
       `_DEFAULT_MIN_CALIBRATION_SAMPLES=50`(`surge_calibrator.py:123-126`)을
       대신 사용하게 되어, `surge_config.min_calibration_samples`가 50이 아닌
       값으로 튜닝될 경우 REQ-AI107-009가 의도한 설정 기반 floor가 실제 학습
       게이트에는 반영되지 않는 조용한 결함이 된다(오늘 시점 두 기본값이 우연히
       50으로 일치해 이 결함이 가려져 있다 — AC-107-011이 이 배선을 직접
       검증한다) → candidate `IsotonicModel`을
       `_CANDIDATE_DIR/candidate_{YYYYMMDD}.pkl`에
       pickle 저장(active 경로는 절대 건드리지 않음, REQ-AI107-002) →
       holdout에서 raw Brier(원시값 그대로)와 calibrated Brier(candidate
       `.predict()` 적용) 계산 → `gate_passed = brier_calibrated < brier_raw`.
  7. 매 실행 결과를 `_RUN_LOG_PATH`에 JSON 1줄로 append(REQ-AI107-003).
  8. `promote_candidate(candidate_path: Path, active_path: Path =
     _CALIBRATOR_PATH) -> None` — candidate 파일을 active 경로로 복사한다.
     **이 함수는 섀도우 학습 잡에서 절대 호출되지 않는다** — plan.md §C 절차를
     따르는 사람(또는 후속 SPEC)이 수동으로만 호출한다.
- 추적 REQ/AC: REQ-AI107-001, REQ-AI107-002, REQ-AI107-003, REQ-AI107-004,
  REQ-AI107-005, REQ-AI107-007, REQ-AI107-009 / AC-107-001~005, AC-107-007,
  AC-107-009, AC-107-011

### TASK-003: 스케줄러 배선(주간, 격리된 예외 처리)

- 대상: `backend/app/services/scheduler.py`.
- 구현: `_run_relation_inference()`와 동일한 형태의 핸들러
  `_run_surge_calibrator_shadow_training()`을 추가한다 — `SessionLocal()` 세션
  생성 → `try/except/finally`로 감싸 `run_shadow_training(db)` 호출 → 결과를
  구조화 로그(`[캘리브레이터섀도우학습]` 태그, 4개 필드: `run_date`,
  `sample_count`, `positive_count`, `gate_passed`)로 기록 → `finally`에서
  `_record_job_duration()` + `db.close()`. 예외는 `except Exception as e:
  logger.warning(...)`로 격리하고 재발생시키지 않는다(REQ-AI107-008 — 기존
  `_run_relation_inference`가 `raise`하는 패턴과 달리, 본 잡은 관측 전용이므로
  실패를 삼킨다 — 스케줄러 자체의 다른 잡 실행에 영향을 주지 않기 위함).
  `scheduler.add_job(_run_surge_calibrator_shadow_training, "cron",
  day_of_week="sun", hour=3, minute=0, timezone="Asia/Seoul",
  id="surge_calibrator_shadow_training", replace_existing=True)`로 등록.
- 추적 REQ/AC: REQ-AI107-008 / AC-107-006, AC-107-008

### TASK-004: 프로모션/롤백 절차 문서화(§C, 본 문서 하단)

- 대상: 본 plan.md §C(아래).
- SPEC-AI-106 §C 패턴(관측 확인 방법 → 판단 기준 → 실행 → 롤백)을 재사용한다.
- 추적 REQ/AC: REQ-AI107-006 / AC-107-010

### TASK-005: 테스트 스위트 + 회귀 검증

- 신규: `test_spec_ai_107.py` — TASK-001 신규 조회 함수, TASK-002의
  `split_walk_forward`/`compute_brier_score`/`train_isotonic(min_positive_samples=...)`/
  `run_shadow_training()`(충분/부족 두 경로) + `promote_candidate()`, TASK-003
  스케줄러 핸들러(정상/예외 두 경로, mock으로 `run_shadow_training`을 예외
  발생시켜 격리 확인)를 커버한다. `run_shadow_training()`이 resolved
  `min_calibration_samples`를 `train_isotonic()`에 실제로 전달하는지(AC-107-011,
  spy 기반 kwargs 검증)도 포함한다.
- 회귀: `uv run pytest tests/test_surge_calibrator.py tests/test_surge_ai036.py -q`
  전체 통과 확인(기존 AC-1~AC-6 + `min_calibration_samples` 설정 필드 존재 테스트
  무회귀).
- 전체: `uv run pytest tests/ --tb=short -q -m "not slow"` (CLAUDE.local.md
  검증 명령 계승) + `uv run ruff check . && uv run mypy app/`.
- 추적 REQ/AC: 전체 REQ-AI107-001~009 / 전체 AC-107-001~011

## C. 프로모션 및 롤백 절차 (REQ-AI107-006 산출물)

본 절차는 향후 실제로 캘리브레이터를 활성화(promote)하기로 결정하는 세션이 따라야
할 체크리스트다. 본 SPEC은 이 절차를 문서화만 하며 실행하지 않는다(§Non-Goals).

1. **게이트 통과 확인**: TASK-003 배포 이후 `journalctl -u newshive | grep
   '캘리브레이터섀도우학습'`로 최근 실행 로그를 검색하거나, `data/surge_calibrator/runs.jsonl`을
   직접 열어 최근 행의 `sufficient_data=true` AND `gate_passed=true` 여부를
   확인한다. 하나라도 `false`이면 아직 프로모션을 검토할 시점이 아니다 — 다음
   주 실행을 기다린다.
2. **연속성 확인(단발 통과로 판단하지 않는다)**: 프로젝트의 2026-07-28
   `theme_news_carry` 자기강화 피드백 루프 사고(오탐률 77% 도달 후 발견) 재발
   방지를 위해, 단 1회의 `gate_passed=true`만으로 즉시 프로모션하지 않는다.
   `runs.jsonl`에서 최근 3회(3주) 연속 `gate_passed=true`이고 `brier_calibrated`가
   `brier_raw` 대비 유의미하게(예: 5% 이상) 개선되는지 확인하는 것을 권장한다 —
   구체적 연속 횟수·개선폭 임계값은 이 절차를 실행하는 세션이 실제 관측 데이터
   분포를 보고 확정한다(본 SPEC은 구체적 수치를 강제하지 않는다 — §D5가 확인한
   대로 이 캘리브레이터는 자기강화 순환 구조가 아니므로 사고와 동일한 위험은
   아니지만, 데이터 부족 상태에서의 우연한 1회 통과를 배제하기 위한 보수적
   관행이다).
3. **프로모션 실행**: 조건이 충족되면
   `promote_candidate(Path("data/surge_calibrator/candidate_{YYYYMMDD}.pkl"))`를
   1회성 스크립트 또는 REPL로 직접 호출한다(TASK-002가 구현하는 함수를 재사용 —
   신규 코드 불필요). 이후 `data/surge_calibrator.pkl`이 갱신되며, 다음
   `get_calibrator()` 호출(신규 프로세스 시작 또는 명시적 재로드)부터
   `calibrate_confidence()`가 identity가 아닌 실제 보정값을 반환한다.
4. **롤백 경로**: 프로모션 후 이상 징후(품질 floor 게이트 통과율 급변, 급등
   커버리지 저하)가 관측되면, `runs.jsonl`에서 프로모션 이전의 마지막
   candidate 파일 경로를 확인해 그 파일로 다시 `promote_candidate()`를
   호출하거나, `data/surge_calibrator.pkl`을 삭제한다(파일 부재 시
   `load_calibrator()`가 identity fallback으로 안전하게 복귀한다 — 기존
   SPEC-AI-036 설계).

## D. 위험

| 위험 | 완화 |
|------|------|
| 섀도우 학습이 매주 실행되지만 아무도 `runs.jsonl`을 주기적으로 확인하지 않아 "죽은 관측 경로"가 재발할 가능성 | §C 절차 1항에 구체적 확인 명령(journalctl grep + 파일 직접 조회) 명시 — 자동 Telegram 알림은 §Non-Goals(최소주의) |
| `min_positive_samples=15` 잠정값이 실제 데이터 분포에 부적합할 가능성(너무 엄격하거나 너무 관대) | spec.md Open Question 2로 명시 — 첫 실행 로그(`positive_count`)로 실제 값을 관측한 뒤 후속 세션에서 조정 가능(단순 상수 변경, 재배포 불필요 수준의 저비용 조정) |
| walk-forward holdout이 최소 표본 floor(50) 근처에서 지나치게 작아(15개) Brier 비교의 통계적 신뢰도가 낮을 가능성 | plan.md §A.4에서 명시적으로 인지 — §C 프로모션 절차 2항의 "3주 연속 통과" 권장이 단발성 노이즈를 완화하는 1차 방어선 |
| `train_isotonic()` 시그니처 확장이 기존 호출부를 깨뜨릴 가능성 | REQ-AI107-007 — 신규 인자 기본값 `None`으로 기존 동작 완전 보존, TASK-005에서 기존 6개 AC 테스트 무회귀 확인 |
| 섀도우 학습 잡의 예외가 다른 스케줄러 잡에 전파될 가능성 | REQ-AI107-008 — 격리된 `try/except`(재발생 없음), TASK-005에서 예외 주입 테스트로 검증 |
