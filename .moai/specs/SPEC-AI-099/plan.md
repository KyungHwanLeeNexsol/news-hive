# SPEC-AI-099 Plan

## A. 구현 전략

Tier M, cycle_type: ddd(ANALYZE-PRESERVE-IMPROVE — `quality.yaml`
`constitution.development_mode: ddd`). 되돌리기 어려운 결정(신규 테이블 스키마,
캡처 지점 위치, 배치 쓰기 도입)을 먼저 다루고, 기계적 배선(카운터 함수, 스케줄러
등록)은 뒤로 미룬다.

핵심 판단:

- 이 SPEC의 위험은 새 알고리즘을 발명하는 데 있지 않다 — 이미 계산된 값을 새 테이블에
  옮겨 담는 것이 핵심이다. 유일한 진짜 위험은 §문제 2(캡처 지점의 위치)와 §문제 3
  (배치 쓰기가 스코어링 사이클 지연에 미치는 영향)이다.
- `compute_ensemble_score()`, 후보 승격/우회 로직, `FundSignal` 생성 경로는
  spec.md §Out of Scope에 따라 완전히 무수정이다 — 이 SPEC의 어떤 TASK도 그 함수들의
  동작을 바꾸지 않는다.

### A.1 신규 데이터 모델 (정확한 스키마 — 가장 되돌리기 어려운 결정)

신규 파일 `backend/app/models/surge_feature_snapshot.py`, 클래스
`SurgeFeatureSnapshot`, 테이블 `surge_feature_snapshots`:

| 컬럼 | 타입 | 근거 |
|------|------|------|
| `id` | `Integer`, PK, autoincrement | 동일 종목이 하루에도 여러 사이클(SPEC-AI-083 재스캔) 재등장 가능 — composite PK 대신 단순 자동증가 PK + 비고유 인덱스 |
| `stock_code` | `String(10)`, indexed | `SurgeCandidate.stock_code` |
| `scanned_at` | `DateTime(timezone=True)`, indexed | 스캔 사이클 실행 시각 — `date`가 아닌 `datetime`(하루 여러 사이클 구분, SPEC-AI-083) |
| `theme_cluster_score` | `Float` | `SurgeCandidate.theme_cluster_score` |
| `combo_score` | `Float` | `SurgeCandidate.combo_score` |
| `best_disclosure_score` | `Float` | `compute_ensemble_score` 내부 `max(pattern_score, immediate_disclosure_score)`(1558행) 재사용 |
| `legacy_score` | `Float` | `SurgeCandidate.legacy_score` |
| `news_delayed_score` | `Float` | `SurgeCandidate.news_delayed_score` |
| `volume_breakout_score` | `Float` | `SurgeCandidate.volume_breakout_score` |
| `momentum_continuation_score` | `Float` | `SurgeCandidate.momentum_continuation_score` |
| `squeeze_score` | `Float` | `SurgeCandidate.squeeze_score` |
| `active_groups` | `Integer` | `compute_ensemble_score` 내부 `active_groups`(1585행) 재사용 |
| `surge_score` | `Float` | `compute_ensemble_score` 반환값(보정 전 raw) |
| `price_5d_trend` | `Float`, nullable | `SurgeCandidate.price_5d_trend` |
| `entry_pool` | `String(20)` | `SurgeCandidate.entry_pool` |
| `active_detectors_json` | `Text`, nullable | `json.dumps(SurgeCandidate.active_detectors)` |
| `market_cap_eok` | `Integer`, nullable | `Stock.market_cap`(이미 조회된 값, 억원 단위 — 기존 컬럼 단위 관례 유지) |
| `price_at_signal` | `Integer`, nullable | `fund_manager.py`가 이미 호출하는 `fetch_current_price_with_change_sync` 재사용 |
| `qualified` | `Boolean` | 메인 루프 임계값 통과 또는 3개 우회 경로 중 하나로 최종 `qualified_codes`에 포함되었는지 |
| `outcome_trading_date` | `Date`, nullable | 정답 라벨 조인 키(다음 거래일) — 백필 전에는 `NULL` |
| `outcome_change_rate` | `Float`, nullable | `SurgeActualOutcome.change_rate` 백필값 |
| `outcome_was_surge` | `Boolean`, nullable | `SurgeActualOutcome.was_surge` 백필값 |
| `created_at` | `DateTime(timezone=True)`, server_default `func.now()` | 표준 관례 |

인덱스: `(stock_code, scanned_at)` 복합 인덱스(조회 패턴: 특정 종목의 시계열 조회),
`outcome_trading_date` 단일 인덱스(백필 잡의 대상 선정 쿼리).

마이그레이션 파일명(제안, 구현 시 `ls backend/alembic/versions/`로 최신 번호
재확인 후 확정): `071_surge_feature_snapshot.py`(직전 최신 확인:
`070_surge_pred_eval_high_based.py`).

### A.2 캡처 지점 및 배치 쓰기 (되돌리기 두 번째로 어려운 결정)

대상: `backend/app/services/surge_detector.py`의 앙상블 스코어링 함수(메인 루프
2192-2199행 + 우회 루프 2204/2229/2263행을 포함하는 상위 함수, 정확한 함수 시그니처는
구현 시 `grep -n "^def " surge_detector.py`로 재확인).

- 메인 루프(2192-2199행) 순회 중 각 후보의 `score`(임계값 적용 전, 페널티 적용 후)를
  `stock_code`를 키로 하는 임시 딕셔너리에 저장한다 — 아직 최종 `qualified` 여부를
  모르므로 스냅샷 객체를 즉시 생성하지 않는다.
- 4개 루프(메인 + 3개 우회) 모두 종료된 직후, 저장해 둔 임시 딕셔너리를 순회하며
  `SurgeFeatureSnapshot` 객체 리스트를 구성한다(`qualified` 필드는
  `stock_code in qualified_codes`로 결정).
- `db.add_all(snapshot_objects)` + `db.commit()`을 **1회** 호출한다. 예외 발생 시
  `db.rollback()` 후 로그만 남기고 상위 함수의 반환(기존 `FundSignal` 생성 결과)에는
  영향을 주지 않는다(REQ-AI099-002 필수 조건 — 부가 관측 경로).
- 신규 함수(예: `_persist_feature_snapshots(db, scanned_at, merged, scores, qualified_codes)`)로
  분리해 앙상블 스코어링 함수 본체의 가독성을 유지한다.
- `@MX:SPEC` 서브라인에 `SPEC-AI-099 REQ-AI099-001, REQ-AI099-002` 추가.

### A.5 PRESERVE 목록 (수정 금지)

| 대상 | 사유 |
|------|------|
| `compute_ensemble_score()`의 가중합/컨센서스 배율 계산 로직 | REQ-AI099-006 — 읽기만 하고 수정하지 않는다 |
| 메인 루프 + 3개 우회 루프의 임계값 통과/우회 판정 로직 자체 | REQ-AI099-006 — 스냅샷 캡처는 판정 이후에 삽입되는 관측 전용 코드다 |
| `fund_manager.py`의 `FundSignal` 생성/갱신 로직 | 무관 — 본 SPEC은 이 파일을 건드리지 않는다 |
| `ml_feature_engineering.py`(`capture_daily_features`, `check_ml_readiness`) | REQ-AI099-005 — 무수정, 신규 병렬 함수만 추가 |
| `surge_calibrator.py` | 무관 — 보정 전 raw 점수만 저장 대상 |
| `SurgeActualOutcome`/`SurgePredictionEvaluation` 스키마 | 조인 대상으로 읽기만 함 |

## B. 작업 분해

### TASK-001: `SurgeFeatureSnapshot` 모델 + 마이그레이션 (REQ-AI099-001)

- 대상: 신규 `backend/app/models/surge_feature_snapshot.py`, 신규 Alembic 마이그레이션
- A.1 스키마대로 SQLAlchemy 모델 정의. `(stock_code, scanned_at)` 복합 인덱스,
  `outcome_trading_date` 단일 인덱스 추가.
- 마이그레이션 파일은 구현 시 `ls backend/alembic/versions/` 재확인 후 다음 순번으로
  생성한다(A.1에서 확인한 최신은 070 — 070+1 이상일 수 있음, 병렬 작업 SPEC이
  먼저 머지되었을 가능성 고려).

추적: REQ-AI099-001 / AC-099-001

### TASK-002: 캡처 지점 배선 및 배치 쓰기 (REQ-AI099-001, REQ-AI099-002)

- 대상: `backend/app/services/surge_detector.py`
- A.2에 따라 메인 루프 순회 중 임시 딕셔너리에 점수 저장 → 4개 루프 종료 후
  `qualified_codes` 확정 → `SurgeFeatureSnapshot` 리스트 구성 →
  `db.add_all()` + `db.commit()` 1회.
- 예외 격리: `try/except` + 로그, 상위 함수의 기존 반환값/부작용(FundSignal 생성)에
  영향 없음을 확인한다.

추적: REQ-AI099-001, REQ-AI099-002 / AC-099-002, AC-099-003, AC-099-004

### TASK-003: 정답 라벨 백필 잡 (REQ-AI099-003)

- 대상: 신규 함수(제안 위치: `backend/app/services/surge_feature_snapshot_service.py`
  또는 `ml_feature_engineering.py` 인접 — 구현 시 확정)
- `outcome_trading_date`가 `NULL`이거나 아직 `SurgeActualOutcome`이 채워지지 않은
  스냅샷 행을 대상으로, `(stock_code, 다음 거래일)` 키로 `SurgeActualOutcome`을
  조회해 `outcome_change_rate`/`outcome_was_surge`를 채운다.
- 다음 거래일 계산(주말/공휴일 처리)은 기존 코드베이스의 거래일 계산 유틸리티가
  있는지 구현 시 확인(`grep -rn "next_trading_day\|is_trading_day" backend/app`)
  하고, 없으면 최소 구현(주말만 건너뜀, 공휴일 미처리)으로 시작해 Open Question으로
  기록한다.
- 실행 주기는 매일 새벽 1회로 확정한다(spec.md §Open Questions 2 확정, 기존
  `keyword_backfill`류 잡과 동일한 `add_job(..., "interval", hours=24, ...)` 패턴).
- 계산 실패는 `try/except` + 로그로 격리하고 다른 스케줄 잡에 영향을 주지 않는다.

추적: REQ-AI099-003 / AC-099-005, AC-099-006

### TASK-004: 보존 정책 배선 확인 (REQ-AI099-004)

- 대상: 없음(신규 코드 아님) — 신규 정리(cleanup) 잡을 **추가하지 않는 것 자체**가
  이 TASK의 산출물이다.
- plan.md 본 섹션에 사이클당 예상 행 수를 문서화한다: 스캔 사이클당 `merged` 후보
  수는 관측 범위에서 대략 수십~수백 개(SPEC-AI-096/097 스캔 유니버스 확장 이후
  변동 가능) × SPEC-AI-083 기준 1일 다회 재스캔 사이클(정확한 사이클 수는 구현 시
  `scheduler.py`에서 재확인) = 초기 1일 추정 수백~수천 행. 90일 누적 시 수만~수십만
  행 규모로, 단일 정수/실수/짧은 문자열 컬럼 위주라 초기 스토리지 부담은 낮다고
  판단하나 실측은 아니다(Open Question 1).

추적: REQ-AI099-004 / AC-099-007

### TASK-005: 신규 병렬 축적 카운터 (REQ-AI099-005)

- 대상: `backend/app/services/ml_feature_engineering.py` 인접 또는 신규 파일
  (구현 시 확정 — 기존 함수와의 응집도를 고려하면 같은 파일에 추가하는 편이 자연스러움)
- `check_feature_snapshot_readiness(db)` 신규 함수: `SurgeFeatureSnapshot`의 고유
  `scanned_at::date` 일수(또는 총 행 수 — 구현 시 어느 쪽이 "90일 상당"의 의미에
  더 부합하는지 확정, 제안은 고유 일수로 `MLFeatureSnapshot`과 의미를 맞춤)를
  계산해 기존 `check_ml_readiness()`와 동일한 응답 형태(`ready`/`days`/`message`)로
  반환한다.
- 기존 `check_ml_readiness()`의 시그니처/반환값/로그 메시지는 완전히 무수정으로
  둔다(REQ-AI099-005 필수 조건).

추적: REQ-AI099-005 / AC-099-008

### TASK-006: 무회귀·신규 검증

- 대상: 신규 `backend/tests/test_spec_ai_099.py`
- 케이스: 스냅샷 모델 생성/조회, 캡처 지점이 승격·비승격 후보 모두를 기록하는지
  (fixture로 양쪽 케이스 구성), 배치 쓰기가 1회 commit으로 이루어지는지(mock으로
  `db.commit()` 호출 횟수 검증), 배치 쓰기 실패가 상위 함수 반환값에 영향을
  주지 않는지, 정답 라벨 백필 잡이 `NULL`을 올바르게 채우는지, 신규 카운터 함수가
  기존 `check_ml_readiness()`와 독립적으로 동작하는지, `compute_ensemble_score`/
  `FundSignal` 생성 경로 무수정 확인(diff grep).
- 기존 테스트(`test_spec_ai_012.py`류, 실제 파일명은 구현 시 `ls backend/tests/`로
  재확인) 전체 무수정 통과 확인.

추적: REQ-AI099-001~006 전체 / AC-099-001~008

## C. 검증 계획

타겟 테스트:

```powershell
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests\test_spec_ai_099.py -q
```

전체 회귀:

```powershell
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests -q -m "not slow"
```

정적 검사:

```powershell
.\backend\.venv\Scripts\ruff.exe check .\backend
.\backend\.venv\Scripts\python.exe -m mypy .\backend\app
```

범위 규율 grep (기존 검증된 앙상블 계산 로직 무변경 확인, REQ-AI099-006):

```bash
git diff backend/app/services/surge_detector.py -- :^backend/tests
# 기대: compute_ensemble_score() 함수 본문, 메인 루프의 임계값 판정, 3개 우회
# 루프의 판정 조건에 라인 변경이 없어야 한다(자동 grep만으로는 완전히 커버되지
# 않으므로 코드 리뷰 병행 — 신규 캡처 코드는 판정 로직 "이후"에 삽입되는 순수 추가만
# 허용한다).
```

## D. 배포/롤백

TASK-001(신규 모델)/TASK-002(캡처 배선)는 순수 관측 경로 추가이며 기존 매매/시그널
로직에 영향을 주지 않는다 — 배포 자체는 무해하다. TASK-003(백필 잡)은 별도 스케줄
잡이므로 다른 잡과 독립적으로 비활성화 가능하다. TASK-005(카운터)는 로그 메시지만
남기므로 위험이 거의 없다.

롤백 트리거:

- TASK-002 배포 후 스캔 사이클 소요 시간이 유의하게(예: 수 초 이상) 증가 → 배치
  쓰기 구현을 조사, 필요 시 즉시 캡처 호출부만 되돌림(신규 모델/마이그레이션은
  그대로 두어도 무해)
- 배치 쓰기 실패가 `FundSignal` 생성 흐름에 영향을 주는 사례 발견(TASK-002 예외
  격리 실패) → 즉시 되돌림, TASK-006에 회귀 케이스 추가
- TASK-003 백필 잡이 다른 스케줄 잡의 실행 시간에 영향 → 백필 잡만 비활성화

롤백 단위: TASK-002는 캡처 함수 호출 1줄을 제거하면 완전 복구(모델/마이그레이션은
독립적으로 존재해도 무해). TASK-003/005는 독립 함수이므로 삭제만으로 완전 롤백된다.

## E. 리스크

- **캡처 지점이 스캔 사이클 지연을 늘릴 위험**: 배치 쓰기 1회라 해도 스캔 사이클마다
  DB write가 추가된다. TASK-006 회귀 테스트가 정상 동작을 커버하지만, 실제 프로덕션
  지연 영향은 배포 후 관찰 대상이다(D2에서 이미 개별 flush보다 낫다고 판단했으나
  "무해함"을 정량 확정하지는 않았다).
- **필드 범위가 좁아 향후 모델링에 불충분할 위험**: D3에서 원시 미노출 피처(거래량
  비율 등)를 명시적으로 제외했다 — 향후 모델링 SPEC이 이 필드만으로 충분한
  판별력을 얻지 못하면 후속 SPEC(탐지기 함수 시그니처 확장)이 필요하다. 이는 알려진
  트레이드오프이며 본 SPEC의 범위를 벗어난다.
- **무기한 보존이 장기적으로 스토리지 문제를 일으킬 위험**: D4에서 의도적으로
  선택했으나, TASK-004의 추정치가 실측이 아니므로 실제 축적 속도가 예상보다 빠를 수
  있다 — Open Question 1로 남긴 관리 임계치 재검토가 필요한 시점을 조기에 판단하지
  못할 위험이 있다.
- **정답 라벨 백필의 거래일 계산 부정확 위험**: TASK-003에서 기존 거래일 계산
  유틸리티가 없으면 최소 구현(주말만 처리)으로 시작하는데, 공휴일이 낀 주는
  `outcome_trading_date`가 실제로는 거래가 없는 날을 가리켜 백필이 영구히 `NULL`로
  남을 수 있다 — TASK-006에 공휴일 인접 케이스를 포함할 것을 권장하되, 완전한
  공휴일 캘린더 통합은 본 SPEC 범위 밖일 수 있다(구현 시 재판단).
