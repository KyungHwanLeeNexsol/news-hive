# SPEC-AI-107 Acceptance Criteria

> GEARS 정규 문장 형식. 각 AC는 **볼드 WHEN/WHILE/WHERE 트리거 + 볼드 shall/shall not 절**로
> 구성한다.

## §A. AC 매트릭스 (REQ ↔ AC 매핑)

| AC ID | 대응 REQ | 심각도 |
|-------|----------|--------|
| AC-107-001 | REQ-AI107-001 | Must-Pass |
| AC-107-002 | REQ-AI107-002 | Must-Pass |
| AC-107-003 | REQ-AI107-003 | Must-Pass |
| AC-107-004 | REQ-AI107-004 | Must-Pass |
| AC-107-005 | REQ-AI107-005 | Must-Pass |
| AC-107-006 | REQ-AI107-008 | Must-Pass |
| AC-107-007 | REQ-AI107-007 | Must-Pass |
| AC-107-008 | REQ-AI107-008 | Must-Pass |
| AC-107-009 | REQ-AI107-009 | Must-Pass |
| AC-107-010 | REQ-AI107-006 | Should-Pass |
| AC-107-011 | REQ-AI107-009 | Must-Pass |

## §B. 인수 기준 (정규 문장)

### AC-107-001 — 섀도우 학습이 시간순 분할로 candidate 아티팩트를 생성한다

**When** 주간 섀도우 학습 잡이 표본 수·positive 수 floor를 모두 충족한 데이터로
실행되면, the system **shall** `created_at` 기준 시간순으로 분할된 학습 구간으로
isotonic 모델을 학습하고, 그 결과를 `data/surge_calibrator/candidate_{YYYYMMDD}.pkl`
경로에 저장해야 한다.

- 검증 방법: 단위 테스트 — 고정 fixture(시간순으로 섞이지 않은 90일치 표본,
  positive ≥15, 전체 ≥50)로 `run_shadow_training(db)`를 호출한 뒤
  `candidate_path`가 반환값에 포함되고 그 경로의 파일이 실제로 존재함을 확인.

### AC-107-002 — active pkl과 in-process 싱글턴이 무변경이다

**While** 섀도우 학습 잡이 실행되는 동안, the system **shall not**
`data/surge_calibrator.pkl`의 파일 mtime/내용 해시를 변경해서는 안 되며,
**shall not** `get_calibrator()`가 반환하는 in-process 싱글턴 객체를 교체해서는
안 된다.

- 검증 방법: 단위 테스트 — 실행 전 active pkl의 SHA-256 해시(또는 부재 확인)와
  `id(get_calibrator())`를 기록한 뒤 `run_shadow_training(db)` 실행, 실행 후
  동일 해시/부재 상태 및 동일 `id()`임을 확인.

### AC-107-003 — 실행 로그가 필수 필드를 포함해 1줄 append된다

**When** 섀도우 학습 실행이 완료되면(충분/부족 경로 모두), the system **shall**
`data/surge_calibrator/runs.jsonl`에 `run_date`, `sample_count`,
`positive_count`, `sufficient_data`, `gate_passed` 5개 필드를 포함한 JSON 1줄을
append해야 하며, **shall not** 기존 행을 덮어써서는 안 된다.

- 검증 방법: 단위 테스트 — 실행 전 로그 파일의 줄 수를 기록, 실행 후 정확히
  +1줄이고 마지막 줄을 JSON 파싱해 5개 필드가 모두 존재함을 확인. 2회 연속
  실행 시 줄 수가 +2가 됨을 확인(append 검증).

### AC-107-004 — 데이터 부족 시 Brier 계산과 candidate 저장을 건너뛴다

**While** 수집된 표본 수가 floor 미만이거나 positive 표본 수가
`min_positive_samples` 미만이면, the system **shall** 실행 로그에
`sufficient_data: false`를 기록해야 하며, **shall not** `candidate_path`를
채우거나 candidate 파일을 디스크에 생성해서는 안 된다.

- 검증 방법: 단위 테스트 — (a) 표본 수 49개(floor=50 미만) fixture, (b) 표본
  수 60개이나 positive 3개(floor=15 미만) fixture 두 케이스 모두에서
  `sufficient_data=False`이고 `candidate_path is None`이며 대상 디렉토리에
  신규 `.pkl` 파일이 생성되지 않았음을 확인.

### AC-107-005 — 신규 DB 테이블/마이그레이션이 0개다

**When** 본 SPEC이 구현되면, the system **shall not** `backend/alembic/versions/`에
신규 리비전 파일을 추가해서는 안 되며, **shall not** 신규 SQLAlchemy 모델
클래스를 도입해서는 안 된다.

- 검증 방법: `git diff --name-only`에 `backend/alembic/versions/` 하위 신규
  파일이 없음을 확인 + `git diff -- backend/app/models/`가 빈 결과임을 확인.

### AC-107-006 — 섀도우 학습 예외가 스케줄러의 다른 잡에 전파되지 않는다

**When** `run_shadow_training(db)` 호출이 예외를 발생시키면, the system **shall**
그 예외를 스케줄러 핸들러 내부의 격리된 `try/except`로 잡아 경고 로그만 남겨야
하며, **shall not** 예외를 재발생(re-raise)시켜서는 안 된다.

- 검증 방법: 단위 테스트 — `run_shadow_training`을 예외를 던지도록 mock한 뒤
  `_run_surge_calibrator_shadow_training()`을 직접 호출, 예외 없이 정상
  반환하고 경고 로그 1줄이 남음을 `caplog`로 확인.

### AC-107-007 — `train_isotonic()` 기존 호출부가 바이트 단위로 무회귀다

**While** `min_positive_samples` 인자가 생략되면(기본값 `None`), the system
**shall** `train_isotonic()`의 반환값이 이 SPEC 이전과 완전히 동일해야 한다.
**When** `min_positive_samples`가 명시적으로 전달되고 positive 표본 수가 그
값 미만이면, the system **shall** identity fallback(`is_identity=True`) 모델을
반환해야 한다.

- 검증 방법: `uv run pytest tests/test_surge_calibrator.py -v`의 기존
  AC-1~AC-6 6개 테스트 전량 무수정 통과 확인 + 신규 테스트로
  `train_isotonic(pairs, min_positive_samples=15)`를 positive 5개 fixture로
  호출해 `is_identity=True`임을 확인.

### AC-107-008 — 섀도우 학습 잡이 매주 정확히 1회만 등록된다

**When** 스케줄러가 초기화되면, the system **shall**
`surge_calibrator_shadow_training` id로 `day_of_week="sun"`,
`hour=3, minute=0, timezone="Asia/Seoul"` cron 트리거를 정확히 1개 등록해야
한다.

- 검증 방법: 단위 테스트 — `scheduler.get_job("surge_calibrator_shadow_training")`가
  `None`이 아니고 그 트리거의 `day_of_week`/`hour`/`minute` 속성이 기대값과
  일치함을 확인.

### AC-107-009 — 표본 수 floor가 설정 가능한 값에서 온다

**When** `run_shadow_training(db)`가 `min_calibration_samples` 인자 없이
호출되면, the system **shall** `SurgeEnsembleConfig.min_calibration_samples`
설정값을 표본 수 floor로 사용해야 한다.

- 검증 방법: 단위 테스트 — `surge_config.min_calibration_samples`를
  monkeypatch로 30으로 낮춘 뒤 표본 35개 fixture로 실행, `sufficient_data`가
  기본값(50) 기준으로는 `False`이나 monkeypatch된 30 기준으로는 데이터 부족
  경계를 통과함을 확인(표본 수 조건만 분리 검증 — positive 조건은 별도
  fixture로 충족).

### AC-107-010 — 프로모션/롤백 절차가 plan.md §C에 문서화된다

**When** plan-phase 산출물이 완성되면, plan.md's §C section **shall**
REQ-AI107-006의 3개 최소 항목(게이트 통과 확인 방법, 프로모션 실행 방법, 롤백
경로)을 포함해야 한다.

- 검증 방법: `grep -A 40 "^## C\. 프로모션 및 롤백 절차" .moai/specs/SPEC-AI-107/plan.md`로
  §C 섹션 헤딩과 "게이트 통과 확인"/"프로모션 실행"/"롤백 경로" 키워드 포함
  여부를 기계적으로 확인. 절차 서술의 논리적 완결성은 육안 리뷰를 보조 수단으로만
  사용한다.

### AC-107-011 — resolved 표본 수 floor가 `train_isotonic()`에 실제로 전달된다

**When** `run_shadow_training(db)`가 표본 수·positive 수 floor를 모두 충족한
데이터로 실행되어 학습 단계까지 도달하면, the system **shall** AC-107-009가
resolve한 `min_calibration_samples` 값을 `train_isotonic()` 호출의
`min_calibration_samples` 키워드 인자로 그대로 전달해야 한다 — `train_isotonic()`
자체의 독립적인 기본값(`_DEFAULT_MIN_CALIBRATION_SAMPLES=50`)에 암묵적으로
의존해서는 안 된다.

- 검증 방법: 단위 테스트 — `train_isotonic`을 spy(예: 원본 함수를 감싸고 호출
  kwargs를 기록한 뒤 그대로 위임하는 `unittest.mock.patch` wrapper, 또는
  유효한 `IsotonicModel`을 반환하는 `Mock(wraps=...)`)로 대체한다.
  `surge_config.min_calibration_samples`를 `train_isotonic()`의 자체 기본값(50)과
  다른 값(예: 37)으로 monkeypatch하고, `min_calibration_samples` 인자 없이
  `run_shadow_training(db)`를 호출한다(표본 수·positive 수 floor를 모두
  충족하는 fixture 사용). spy가 기록한 호출 kwargs에서
  `min_calibration_samples == 37`임을 확인한다 — `50`이 기록되면 실패
  (`train_isotonic()`의 자체 기본값이 조용히 사용되었다는 뜻이며, 이는 이
  AC가 방지하려는 정확한 결함이다).

## Scenarios (Given-When-Then, 최소 2)

### 시나리오 1 — 충분한 데이터로 섀도우 학습이 정상 완료되고 active pkl은 무변경이다

**Given** `FundSignal` 테이블에 `signal_type="surge_candidate"`,
`is_correct is not None`, `verified_at is not None`인 표본 80개(positive 20개,
`created_at`이 최근 90일에 고르게 분포)가 존재하고, `data/surge_calibrator.pkl`은
아직 존재하지 않는다(identity fallback 상태).

**When** 일요일 03:00 KST 섀도우 학습 잡이 실행된다.

**Then** `data/surge_calibrator/candidate_20260809.pkl`(실행일 기준)이 생성되고,
`data/surge_calibrator/runs.jsonl`에 `sample_count=80, positive_count=20,
sufficient_data=true, gate_passed=<Brier 비교 결과>`를 포함한 행이 append되며
(AC-107-001, AC-107-003), `data/surge_calibrator.pkl`은 여전히 부재
상태이거나(최초 실행) 이전과 동일한 내용으로 무변경이다(AC-107-002).

### 시나리오 2 — positive 표본 부족으로 데이터 부족 경로가 실행된다

**Given** 표본 60개(floor 50 이상 충족) 중 positive가 4개뿐이다
(`min_positive_samples=15` 미달).

**When** 섀도우 학습 잡이 실행된다.

**Then** `run_shadow_training()`은 `sufficient_data=False`를 반환하고,
`runs.jsonl`에 `sample_count=60, positive_count=4, sufficient_data=false`를
포함한 행이 append되며, 어떤 candidate `.pkl` 파일도 신규 생성되지 않고
Brier 점수 계산이 시도되지 않는다(AC-107-004).

### 시나리오 3 — DB 조회 예외가 발생해도 스케줄러의 다른 잡은 영향받지 않는다

**Given** `get_surge_calibration_pairs_with_time(db)` 호출이(예: DB 커넥션
일시 장애로) `SQLAlchemyError`를 발생시키도록 mock되어 있다.

**When** `_run_surge_calibrator_shadow_training()`이 실행된다.

**Then** 예외는 핸들러 내부에서 격리되어 경고 로그 1줄만 남고
(`[캘리브레이터섀도우학습] 실패 (무시): ...`), 함수는 예외 없이 정상
반환하며, 이후 스케줄러에 등록된 다른 잡(예: `relation_inference`)의 실행
스케줄에는 어떤 영향도 주지 않는다(AC-107-006).

## Edge Cases

- **`data/surge_calibrator/` 디렉토리가 아직 존재하지 않는 최초 실행**:
  `run_shadow_training()`은 candidate 저장 직전에 `mkdir(parents=True,
  exist_ok=True)`로 디렉토리를 생성한다(기존 `save_calibrator()`의 동일 패턴을
  재사용) — 본 SPEC은 이 경로에 대한 별도 오류 처리를 추가하지 않는다.
- **`runs.jsonl` 파일이 아직 존재하지 않는 최초 실행**: append 모드(`"a"`)로
  파일을 열면 파일이 없을 때 자동 생성된다 — 별도 초기화 로직 불필요.
- **holdout 구간이 0개가 되는 극단적 경계**(예: `holdout_fraction=0.3`이지만
  전체 표본이 정확히 floor(50)에 걸쳐 있어 반올림으로 holdout이 0이 되는
  경우): `split_walk_forward()`가 빈 holdout을 반환하면 `compute_brier_score([])`가
  ZeroDivisionError를 유발하므로, `run_shadow_training()`은 holdout이 비어
  있으면 `sufficient_data=False`(데이터 부족과 동일 경로)로 처리한다 — 별도
  예외 케이스로 분기하지 않고 기존 데이터 부족 경로에 흡수한다.
- **주말/휴장일**: 섀도우 학습은 시그널 생성 잡과 달리 `_is_kr_market_open()`
  가드를 사용하지 않는다 — 캘리브레이션 대상 표본은 과거 검증 완료 데이터이므로
  당일 장 개장 여부와 무관하다(의도적 설계, 별도 처리 불필요).

## Quality Gate Criteria

- `uv run pytest tests/ --tb=short -q -m "not slow"` 전체 통과(CLAUDE.local.md
  검증 명령 계승).
- `uv run ruff check . && uv run mypy app/` 신규 결함 0건(기존 baseline 결함은
  예외).
- 신규 코드(`split_walk_forward`, `compute_brier_score`, `run_shadow_training`,
  `promote_candidate`, `get_surge_calibration_pairs_with_time`, 스케줄러
  핸들러)에 대한 단위 테스트 커버리지 100%(정상/데이터부족/예외격리 3개 경로
  모두 포함).
- `git diff --name-only`에 `backend/alembic/versions/`, `fund_manager.py`
  (품질 floor 게이트 라인), `signal_verifier.py`의 Bayesian
  `calibrate_confidence()` 함수 본체가 포함되지 않음(TASK-001의 신규 sibling
  함수 추가만 허용).

## Definition of Done

- [ ] AC-107-001 ~ AC-107-010 전량 PASS
- [ ] 3개 시나리오 전량 재현 검증
- [ ] plan.md §C 프로모션/롤백 절차 최종본 기록(게이트 확인/실행/롤백 3항목 포함)
- [ ] CHANGELOG.md `[Unreleased]`에 섀도우 학습 배선 항목 추가(active pkl
      무변경, 프로모션은 별도 수동 절차임을 명시)
- [ ] `git diff --name-only`가 plan.md §A.1 PRESERVE 목록과 배치되지 않음을
      리뷰로 확인
