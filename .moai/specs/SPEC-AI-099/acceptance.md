# SPEC-AI-099 Acceptance Criteria

> GEARS 정규 문장 형식. 각 AC는 **볼드 WHEN/WHILE/WHERE 트리거 + 볼드 shall/shall not 절**로
> 구성한다.

## §A. AC 매트릭스 (REQ ↔ AC 매핑)

| AC ID | 대응 REQ | 심각도 |
|-------|----------|--------|
| AC-099-001 | REQ-AI099-001 | Must-Pass |
| AC-099-002 | REQ-AI099-001, REQ-AI099-002 | Must-Pass |
| AC-099-003 | REQ-AI099-002 | Must-Pass |
| AC-099-004 | REQ-AI099-002 | Must-Pass |
| AC-099-005 | REQ-AI099-003 | Must-Pass |
| AC-099-006 | REQ-AI099-003 | Must-Pass |
| AC-099-007 | REQ-AI099-004 | Must-Pass |
| AC-099-008 | REQ-AI099-005 | Must-Pass |
| AC-099-009 | REQ-AI099-006 | Must-Pass |

## §B. 인수 기준 (정규 문장)

### AC-099-001 — 신규 스냅샷 모델이 승격/비승격 후보 모두를 개별 행으로 저장한다

**When** 앙상블 스코어링 사이클이 N개의 후보를 평가하면, the system **shall**
`SurgeFeatureSnapshot` 테이블에 정확히 N개의 신규 행(그 사이클에서 이미 존재하던
행에 대한 UPDATE가 아닌 INSERT)을 생성해야 하며, 최종 임계값 통과 여부와 무관하게
평가된 모든 후보를 포함해야 한다.

- 검증 방법: pytest — fixture로 N개 후보(일부는 임계값 통과, 일부는 미통과) 구성 후
  스코어링 함수 실행, 생성된 스냅샷 행 수가 N과 일치하고 `qualified` 필드가 올바르게
  분기됨을 확인

### AC-099-002 — 스냅샷 레코드는 불변이다 (재스캔 시 갱신되지 않는다)

**While** 동일 종목이 이전 사이클에 이미 스냅샷 행을 가진 상태에서, the system
**shall** 새 사이클의 스코어링 결과를 기존 행에 UPDATE하지 않고 새로운 행으로
추가해야 하며, 기존 스냅샷 행의 값을 **shall not** 변경해서는 안 된다.

- 검증 방법: pytest — 동일 `stock_code`로 2회 연속 사이클 실행 후, 스냅샷 테이블에
  2개의 서로 다른 `id`/`scanned_at`을 가진 행이 존재하고 1차 행의 값이 변경되지
  않았음을 확인

### AC-099-003 — 배치 쓰기가 사이클당 1회의 commit으로 이루어진다

**When** 스코어링 사이클(메인 루프 + 3개 우회 루프)이 완료되면, the system
**shall** 그 사이클의 모든 스냅샷 행을 단일 배치 쓰기 호출로 영속화해야 하며,
후보마다 개별 `db.commit()`/`db.flush()`를 호출해서는 **shall not** 안 된다.

- 검증 방법: pytest — DB 세션의 `commit`/`flush` 메서드를 mock하여 호출 횟수가
  후보 수와 무관하게 사이클당 상수(1 또는 1+기존 `FundSignal` 관련 호출 수만큼)임을
  확인

### AC-099-004 — 배치 쓰기 실패가 기존 시그널 생성 흐름을 막지 않는다

**When** 스냅샷 배치 쓰기가 예외를 발생시키면, the system **shall** 그 예외를
포착해 로그로 남기고 기존 `FundSignal` 생성/갱신 결과를 **shall not** 되돌리거나
스캔 사이클 전체를 실패시켜서는 안 된다.

- 검증 방법: pytest — 스냅샷 쓰기 호출부에 예외를 주입한 fixture로 실행 후,
  `FundSignal` 행이 정상적으로 생성/갱신되었음을 확인(스냅샷 실패와 무관)

### AC-099-005 — 정답 라벨이 조인 가능할 때 백필된다

**Where** `SurgeActualOutcome`에 스냅샷의 `outcome_trading_date`와 `stock_code`가
일치하는 행이 존재하면, the system **shall** 백필 잡 실행 시 해당 스냅샷 행의
`outcome_change_rate`/`outcome_was_surge`를 그 값으로 채워야 한다.

- 검증 방법: pytest — `SurgeActualOutcome` fixture 존재 케이스에서 백필 잡 실행 후
  스냅샷 행의 두 필드가 정확히 일치함을 확인

### AC-099-006 — 정답이 아직 없으면 라벨이 `NULL`로 유지된다

**While** 해당 `(stock_code, outcome_trading_date)` 조합의 `SurgeActualOutcome`
행이 아직 존재하지 않으면, the system **shall** `outcome_change_rate`/
`outcome_was_surge`를 `NULL`로 유지해야 하며 **shall not** 0이나 임의값으로
채워서는 안 된다.

- 검증 방법: pytest — `SurgeActualOutcome` fixture가 없는 케이스에서 백필 잡 실행
  후 두 필드가 여전히 `NULL`임을 확인, `ZeroDivisionError`나 예외 없이 정상 종료됨을
  확인

### AC-099-007 — 신규 테이블에 자동 삭제 잡이 등록되지 않는다

**While** 본 SPEC이 적용된 상태에서, the system **shall not**
`SurgeFeatureSnapshot` 테이블을 대상으로 하는 자동 삭제/정리 스케줄 잡을 등록해서는
안 된다.

- 검증 방법: 코드 리뷰 — `scheduler.py`에 `SurgeFeatureSnapshot`/
  `surge_feature_snapshots`를 대상으로 하는 `DELETE`/정리 함수 등록이 없음을 확인
  (`grep -rn "surge_feature_snapshot" backend/app/services/scheduler.py` → 정리
  잡 등록 매치 0건이어야 함, 백필 잡 등록은 허용)

### AC-099-008 — 신규 축적 카운터가 기존 카운터와 독립적으로 동작한다

**When** 신규 축적 상태 조회 함수를 호출하면, the system **shall** 신규
`SurgeFeatureSnapshot` 테이블의 축적 상태를 기존 `check_ml_readiness()`와 동일한
응답 형태로 반환해야 하며, 기존 `check_ml_readiness()`의 반환값·로그 메시지는
**shall not** 이 신규 함수 도입으로 인해 변경되어서는 안 된다.

- 검증 방법: pytest — 두 함수를 각각 호출해 독립적인 결과를 반환함을 확인, 기존
  `test_ml_feature_engineering.py`(파일명은 구현 시 재확인)류 기존 테스트가
  무수정으로 통과함을 확인

### AC-099-009 — 앙상블 계산 로직과 후보 승격 로직이 완전히 무변경이다

**While** 본 SPEC이 적용된 상태에서, the system **shall not**
`compute_ensemble_score()`의 가중합/컨센서스 배율 계산, 메인 루프의 임계값 판정,
3개 우회 루프의 판정 조건을 변경해서는 안 되며, `fund_manager.py`의 `FundSignal`
생성/갱신 로직을 **shall not** 변경해서는 안 된다.

- 검증 방법: 코드 리뷰 — `git diff`로 위 함수/로직 본문에 라인 변경이 없음을 확인
  (plan.md §C 참고, 자동 grep만으로는 불충분해 코드 리뷰를 병행) + 기존
  `test_spec_ai_012.py`류 characterization 테스트 무수정 통과

```bash
git diff --name-only | grep -E 'fund_manager\.py'
# 기대: 0 매치 — 본 SPEC은 surge_detector.py와 신규 파일만 건드린다
```

## §C. Given-When-Then 시나리오 (AC 보강용, AC 정의 아님)

### 시나리오 1 — 승격되지 않은 후보도 향후 학습을 위한 음성 예시로 저장된다

- **Given** 앙상블 스코어링 사이클에 10개 후보가 평가되고, 그중 3개만 임계값을
  통과(또는 우회 경로로 승격)한다.
- **When** 스코어링 사이클이 완료된다.
- **Then** `SurgeFeatureSnapshot`에 10개 행이 모두 저장되고, `qualified=True`인
  행이 정확히 3개, `qualified=False`인 행이 7개다. (AC-099-001)

### 시나리오 2 — 정답 라벨이 T+1에 자연스럽게 채워진다

- **Given** T일에 종목 X가 스캔되어 스냅샷 행이 생성되고, `outcome_trading_date`가
  T+1(다음 거래일)로 설정된다. T+1일 장 마감 후 `SurgeActualOutcome`에 종목 X의
  T+1 결과가 저장된다.
- **When** 백필 잡이 T+1일 이후 실행된다.
- **Then** 종목 X의 스냅샷 행에 `outcome_change_rate`/`outcome_was_surge`가
  채워진다. (AC-099-005)

### 시나리오 3 — 스냅샷 쓰기 실패가 매매 시그널 생성을 막지 않는다

- **Given** 스냅샷 배치 쓰기 도중 DB 커넥션 오류가 발생한다.
- **When** 스코어링 사이클이 계속 진행된다.
- **Then** `FundSignal` 생성/갱신은 정상적으로 완료되고, 오류는 로그에만 남는다.
  (AC-099-004)

## §D. Edge Cases

- **그 사이클에 평가된 후보가 0개인 경우**: 배치 쓰기 호출 자체를 건너뛰거나 빈
  리스트로 `db.add_all([])`를 호출해도 무해해야 한다 — 예외를 발생시켜서는 안 된다.
- **`outcome_trading_date` 계산이 공휴일에 걸리는 경우**: plan.md §E 리스크에서
  명시했듯 최소 구현(주말만 처리)이 공휴일을 오처리할 수 있다 — 이 경우 라벨이
  영구히 `NULL`로 남는 안전한 실패(fail-safe)이며, 잘못된 라벨이 채워지는 것보다
  낫다(AC-099-006의 "임의값으로 채우지 않는다" 원칙과 일관).
- **동일 종목이 하루에 여러 사이클(SPEC-AI-083 재스캔)에서 반복 평가되는 경우**:
  각 사이클마다 별도 행이 생성된다(AC-099-002) — 이는 의도된 동작이며 중복이 아니다.
- **`SurgeActualOutcome`이 영구히 채워지지 않는 종목(상장폐지, 거래정지 등)**:
  해당 스냅샷 행은 `outcome_change_rate`/`outcome_was_surge`가 `NULL`로 무기한
  남는다 — 이는 D4(무기한 보존) 정책 하에서 허용되는 상태이며, 별도 정리 로직을
  요구하지 않는다.

## §E. Definition of Done

- [ ] AC-099-001 통과 — 승격/비승격 후보 모두 개별 행으로 저장.
- [ ] AC-099-002 통과 — 스냅샷 레코드 불변성(재스캔 시 갱신 아닌 신규 행).
- [ ] AC-099-003 통과 — 배치 쓰기가 사이클당 1회 commit.
- [ ] AC-099-004 통과 — 배치 쓰기 실패가 기존 시그널 생성 흐름 무영향.
- [ ] AC-099-005 통과 — 정답 라벨 백필(조인 가능 시).
- [ ] AC-099-006 통과 — 정답 미존재 시 `NULL` 유지.
- [ ] AC-099-007 통과 — 신규 테이블에 자동 삭제 잡 미등록.
- [ ] AC-099-008 통과 — 신규 카운터가 기존 `check_ml_readiness()`와 독립.
- [ ] AC-099-009 통과 — 앙상블 계산/승격 로직/`FundSignal` 경로 완전 무변경.
- [ ] `ruff check` / `mypy` 통과.
- [ ] 기존 회귀 테스트 전체 통과: `cd backend && uv run pytest tests/ -m "not slow"`.
- [ ] spec.md §Open Questions 2(백필 잡 실행 주기)가 구현 착수 전 확정됨.
- [ ] spec.md §Open Questions 1(행 수 관리 임계치)과 3(캘리브레이션 후 값 병행 저장
      여부)의 미확정 상태는 본 SPEC의 DoD를 막지 않는다 — 데이터 캡처·조회 가능
      상태까지가 Must-Pass 범위이며, 모델 학습 자체는 이 SPEC의 범위가 아니다.
