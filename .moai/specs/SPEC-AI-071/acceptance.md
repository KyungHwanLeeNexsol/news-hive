# SPEC-AI-071 Acceptance Criteria

Given-When-Then 시나리오와 엣지케이스. 모든 기준은 관찰 가능(upsert 배치 내용/테이블 행/`was_surge`
카운트/로그 문자열/테스트 출력)해야 하며, 신호 생성 경로·매수 로직·DB 스키마 diff는 0이어야 한다.

---

## AC-071-001 (REQ-001/003) — `stocks` 부재 코드는 upsert·was_surge에서 제외

**Given** `stocks` 테이블에 종목 A(추적 종목)가 있고 코드 X(예: `520099`, 인버스 2X ETN)는 없으며,
Naver top-movers 결과가 A와 X를 모두 포함하고 둘 다 `change_rate >= 10.0` 인 상태

**When** `collect_daily_surge_outcomes(db, trading_date)` 가 실행되면

**Then**:
- upsert 배치(`rows_to_upsert`)에 A는 포함되고 **X는 포함되지 않는다**.
- `SurgeActualOutcome`에 (trading_date, A)는 `was_surge=True`로 적재되고, (trading_date, X)는
  적재되지 않는다.
- 반환된 `was_surge` 급등 카운트가 X를 세지 않는다(X 제외 전 대비 감소).
- 신호 생성 경로(`build_scan_universe`/`gather_surge_candidates`/`compute_ensemble_score`) diff 0.

---

## AC-071-002 (REQ-002) — top-100 밖 T-1 예측 종목은 계속 포함

**Given** 종목 P가 `stocks`에 존재하고 T-1에 `surge_candidate` 시그널이 있으나, T당일 Naver
top-100 상승률 목록에는 없는 상태(즉 top-movers 스크레이프에는 안 잡히고 T-1 예측 보완으로만 유입)

**When** `collect_daily_surge_outcomes(db, trading_date)` 가 실행되면

**Then**:
- T-1 예측 보완 로직(`:72-101`)이 P를 `code_to_market`에 추가한다.
- REQ-001의 `stocks` 교집합 필터가 P를 **제외하지 않는다**(P ∈ `stocks` 이므로).
- P가 upsert 배치에 포함되어 `SurgeActualOutcome`에 적재된다(P의 `change_rate` 기준 `was_surge`
  분류대로).
- 보완 로직 코드 diff 0 (보존만).

---

## AC-071-003 (REQ-001) — 추적 종목 정상 집계 회귀 없음

**Given** `stocks`에 있는 정상 종목 B가 top-movers에 포함되고 `change_rate = 12.5` 인 상태

**When** `collect_daily_surge_outcomes(db, trading_date)` 가 실행되면

**Then**:
- B가 필터를 통과해 upsert되고 `was_surge=True`로 적재된다.
- 필터 도입이 정상 추적 종목의 급등 집계를 축소하지 않음이 확인된다(정상 종목 오제외 회귀 없음).

---

## AC-071-004 (REQ-004) — 제외 종목 수 로깅

**Given** 결합 코드 집합에 `stocks` 부재 코드가 N개 포함된 상태

**When** REQ-001 필터가 적용되면

**Then**:
- 로그에 제외된 코드 수(N)가 관측 가능한 형태로 남는다(기존 수집 로그 형식과 일관).
- 잡은 예외 없이 정상 완료된다.

---

## 엣지케이스

- **EC-1 `stocks` 조회 실패(fail-open)**: `Stock.stock_code.in_(...)` 필터 조회가 DB 오류(SSL 끊김
  등)로 실패하면, 시스템은 배치를 중단하지 않고 **미필터 집합으로 진행**(경고 로그)한다. 그날 하루만
  ETN이 재유입될 수 있으나 정답 수집 전체를 잃지 않는다. 필요 시 명시적 rollback으로 세션 상태를
  복구한다(기존 종목명 조회 실패 처리 관례와 일관).
- **EC-2 교집합 결과 0건**: 결합 코드가 전부 `stocks` 밖인 극단이면 upsert 대상이 0 → 기존 "upsert할
  레코드 없음" 경로(`:142-144`)로 0을 반환하고 잡은 실패하지 않는다.
- **EC-3 미추적 실제 기업**: `stocks`에 없는 정상 기업 코드(예: `900300`)도 ETN과 동일하게 제외된다
  — 후보였던 적이 없어 TP가 될 수 없다는 동일 논리. 특수 케이스 분기 없이 자연 제외됨을 확인한다.
- **EC-4 중복 코드**: `code_to_market`은 dict라 코드 유일성이 보장되므로 필터가 유일 집합에 1회 적용
  되고 중복 upsert가 발생하지 않는다.
- **EC-5 종목명 fallback 수렴(부수 효과)**: 필터 후 upsert되는 모든 코드가 `stocks`에 존재하므로
  종목명 미해결 경고(`stock_name == stock_code`, `:172-179`)가 사실상 0으로 수렴한다 — 요구사항은
  아니나 회귀로 오판하지 않는다.

---

## Definition of Done

- [ ] 현행 동작 characterization test 존재(PRESERVE): 필터 도입 전 `stocks` 부재 코드가 포함되던
      동작 스냅샷.
- [ ] `stocks` 교집합 필터가 결합 코드 집합에 대해 가격 조회/upsert 이전에 적용됨(AC-071-001).
- [ ] `stocks` 부재 코드(ETN·미추적 기업)가 upsert 배치·`was_surge` 카운트에서 제외됨(AC-071-001/003, EC-3).
- [ ] top-100 밖 T-1 예측 종목이 계속 포함됨이 테스트로 보장(AC-071-002, REQ-002 회귀 가드).
- [ ] 정상 추적 종목의 급등 집계 회귀 없음(AC-071-003).
- [ ] 제외 종목 수 로깅(AC-071-004).
- [ ] 모든 엣지케이스(EC-1~EC-5) 테스트 커버.
- [ ] 테스트 커버리지 85%+, `ruff check` 무경고, 전체 급등 스위트 회귀 없음.
- [ ] 신호 생성 경로 diff 0, 매수 로직 diff 0, DB 스키마 diff 0(신규 테이블/마이그레이션 없음).
- [ ] 과거 데이터 백필/재계산 없음(전진 전용, Exclusion 1 준수).
