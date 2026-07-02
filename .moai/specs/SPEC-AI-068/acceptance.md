# SPEC-AI-068 인수 조건 (acceptance.md)

## Definition of Done

- [ ] REQ-001~005 전부 구현, 각 REQ에 대응하는 테스트 존재
- [ ] `SurgePredictionEvaluation`에 `scannable_recall`/`coverage`/`scannable_actual_count`/
      `total_actual_count` 컬럼 + 마이그레이션
- [ ] 거래일별 스캔 유니버스 종목코드 조회 경로 존재
- [ ] `surge_evaluation_service.py:531-535` 거짓 전제 주석/로직 제거
- [ ] 실제급등주 scannable/non-scannable 라벨링 저장
- [ ] 테스트 커버리지 85%+, `ruff`/`mypy` 무경고, 전체 급등 스위트 회귀 없음
- [ ] 예측기록 모드 불변(매수 로직 diff 0)

---

## Scenario 1: Scannable Recall과 Coverage가 분리 계산된다 (REQ-002/003/004)

**Given** T-1(전일) 스캔 유니버스에 종목 {A, B, C, D}가 영속화되어 있고,
당일 실제급등주(was_surge)가 {A, B, X, Y, Z}이며(전체 5종목, 이 중 유니버스 교집합 = {A, B}),
우리가 T-1에 발신한 시그널이 {A}일 때,
**When** 18:30 KST 평가 잡이 실행되면,
**Then** `scannable_actual_count = 2`({A,B}), `total_actual_count = 5`,
`scannable_recall = 1/2 = 0.5`(발신 {A} ∩ scannable_actual {A,B}),
`coverage = 2/5 = 0.4`가 각각 **분리 컬럼**에 저장된다.
**And** 시장 전체 top-movers({X,Y,Z} 포함)를 recall 분모로 쓰던 기존 계산은 사용되지 않는다.

## Scenario 2: 스캔 유니버스 종목코드가 거래일별로 영속화된다 (REQ-001)

**Given** `build_scan_universe`가 Pool A={A}, Pool B={B,C}, Pool C={D}로 유니버스를 확정하고
`max_scan_universe`로 잘라낸 결과가 {A,B,C,D}일 때,
**When** 신호 생성이 완료되면,
**Then** 해당 거래일 레코드로 `{A:pool_a, B:pool_b, C:pool_b, D:pool_c}` 종목코드+풀 태그가
영속화되고, 나중에 거래일 키로 조회 가능하다.
**And** 기존 `pool_a/b/c_count`, `scan_universe_size` 개수 값은 그대로 유지된다(하위호환).

## Scenario 3: 급등 유형이 라벨링되고 공식 목표가 scannable로 한정된다 (REQ-005)

**Given** 당일 실제급등주 {A(유니버스 포함), X(유니버스 미포함)}가 있을 때,
**When** 평가가 실행되면,
**Then** A는 `surge_type="scannable"`, X는 `surge_type="non_scannable"`로 저장되고,
공식 정확도 목표(Scannable Recall)는 scannable 모집단만을 대상으로 측정된다.
**And** non_scannable 집단에 대한 실시간 조기탐지 파이프라인은 생성되지 않는다(경계 정의만).

---

## Edge Cases

- **EC-1 (유니버스 교집합 0)**: `scannable_actual = ∅`이면 `scannable_recall = null`(측정 불가),
  잡은 실패하지 않고 계속 진행한다.
- **EC-2 (과거 날짜 유니버스 부재)**: T-1 유니버스 코드가 없는 과거 날짜는 `scannable_recall=null`,
  `coverage`도 계산 불가 시 `null`로 두고 "coverage-미상"으로 표기한다.
- **EC-3 (실제급등주 0)**: `total_actual_count = 0`이면 `coverage = null`.
- **EC-4 (조인 키 불일치)**: FundSignal은 stock_code 직접 컬럼이 없어 Stock 조인 필수 —
  조인 실패 종목은 로그 후 집합에서 제외하되 잡 전체를 중단하지 않는다.
- **EC-5 (동일 날짜 재실행)**: 유니버스 영속화는 일자당 upsert(중복 레코드 금지).

## 품질 게이트 (Quality Gates)

- 지표 계산 정합성: 최소 1개 실측 거래일에 대해 손계산 대조 로그 첨부.
- `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"` 통과.
- 예측기록 모드 확인: 매수/포트폴리오 파일 diff 0.
