# SPEC-AI-090 Plan — 연속성 계열 탐지기 평가 기준 재검토 측정 스파이크

## §A — 결정 게이트 (가장 변경 가능성 높은 결정 — 최우선 검토)

### 해소된 결정 — Implementation Kickoff Approval의 범위는 M1으로 한정한다

대안 평가 기준(기준 B/C)을 두 탐지기의 기여도 평가에 실제로 채택할지, 채택한다면
`momentum_continuation`의 앙상블 가중치를 어떻게 조정할지(또는 `near_limit_up_carry`의
confidence 공식/임계를 어떻게 조정할지)는 본 SPEC 작성 시점에는 실측 hit-rate 데이터가 없어
확정할 수 없다. 이를 명시적 결정 지점으로 다루기 위해 다음을 **해소된 결정**으로 기록한다:

- 본 SPEC의 **Implementation Kickoff Approval은 M1(측정 스파이크)의 실행만을 승인**한다.
  M1은 읽기 전용 파생 계산이며 어떤 탐지 로직·가중치·기존 집계 정의도 변경하지 않는다
  (spec.md REQ-AI090-004).
- 대안 기준 채택 여부·조정 방향 결정은 **M1 완료 후에만 존재하는 새로운 AskUserQuestion
  라운드**(M2 결정 게이트)로 명시적으로 위임한다. 이 라운드는 M1의 실측 결과(재현 검증,
  4-기준 hit-rate 비교표)를 근거로 진행하며, 본 SPEC의 Implementation Kickoff Approval에
  의해 사전 승인되지 않는다.
- **M2는 본 SPEC의 Implementation Kickoff Approval이 승인하는 자율 실행 범위에 포함되지
  않는다.** M2 승인이 없으면 M3+(가중치/공식 조정 구현)는 시작되지 않으며, M1 완료 + 리포트
  제출만으로 본 SPEC은 유효하게 완료된다(구현 없이 완료되는 것이 valid한 결과).

이 SPEC의 run-phase는 **M1까지만 자율 실행**하고, M1 완료 시점에 orchestrator가 결과를
Report-Before-Ask Gate 준수 형태로 사용자에게 제시한 뒤 새로운 AskUserQuestion 라운드로 M2를
진행한다. M3+는 M2 승인 내용에 따라 본 SPEC의 후속 마일스톤으로 진행하거나, 범위가 크면
별도 후속 SPEC(SPEC-AI-09X)으로 분리할 수 있다 — 이 분리 여부 자체도 M2에서 함께 결정한다.

## §B — 신규 인터페이스/데이터 형태 (M1 산출물의 형태 — 두 번째로 변경 가능성 높음)

### B.1 대안 기준 판정 함수 시그니처 (제안, M1에서 확정)

```python
# app/services/continuation_bar_measurement_service.py (신규 모듈, 읽기 전용 파생 계산)
def classify_continuation_outcome(
    t1_change_rate: float,
    t_change_rate: float | None,   # None이면 T당일 SurgeActualOutcome 행 부재
    threshold_pct: float,           # 기준 B는 0.0, 기준 C는 3.0 또는 5.0
) -> str:
    """반환값: "success" | "fail" | "unmeasurable" (t_change_rate가 None인 경우).

    순수 함수 — DB/네트워크 접근 없음. 기존 was_surge(>=10.0%) 판정과 별개로,
    완화된 임계(threshold_pct)를 기준으로 성공/실패를 판정한다.
    """
```

### B.2 4-기준 재채점 산출물 형태

```python
def measure_continuation_detector_bars(
    db: "Session",
    sample_dates: list["date"],
    detectors: tuple[str, ...] = ("momentum_continuation", "near_limit_up_carry"),
) -> dict:
    """탐지기별·기준별(was_surge/기준B/기준C@3%/기준C@5%) hit-rate·측정불가 건수를 반환한다.

    반환 dict 키(제안): {detector: {criterion: {"hit": int, "miss": int,
    "unmeasurable": int, "hit_rate": float | None}}}. 신규 DB 스키마 없음 —
    로그/리포트 아티팩트 전용 반환값.
    """
```

이 시그니처는 M1 구현 중 확정되며, 정확한 반환 필드명은 M1 완료 보고서에 실제 사용된 형태로
기록한다(본 plan.md는 설계 방향만 제안).

### B.3 M1 리포트 산출물 형태

`.moai/reports/continuation-detector-eval-bar/{YYYY-MM-DD}.md` — 사람이 읽을 수 있는 리포트
(코드 변경이 아닌 분석 리포트이므로 `.moai/reports/`가 올바른 위치, SPEC-AI-089 관례 계승).
REQ-001 재현 검증 결과 + REQ-003의 4-기준 hit-rate 비교표 + 측정불가 건수를 포함한다.

## §C — 마일스톤 (우선순위 기반, 시간 추정 없음)

**본 SPEC의 run-phase 실행 범위는 M1으로 한정된다.** M2(결정 게이트)와 M3+(조건부 구현)는
계획 참고용으로 아래에 기술하지만, 본 SPEC의 Implementation Kickoff Approval이 승인하는
자율 실행 대상이 아니다.

### M1 — 측정 계측 구현 (Priority: High, 본 SPEC의 run-phase 실행 범위 — 유일한 자율 실행 마일스톤)

1. REQ-001: §Context 표의 관측치를 표본 거래일에 대해 재조회하고 원본 쿼리·출력을 기록한다.
   재현되지 않으면 그 사실을 리포트 최상단에 명시하고 이후 단계 진행 여부를 재판단한다.
2. REQ-002: `classify_continuation_outcome()` 순수 함수 작성(§B.1) — 기준 B(임계 0.0%)와
   기준 C(임계 +3.0%/+5.0%) 판정 로직. 명명된 상수로 임계값 정의.
3. REQ-003: `measure_continuation_detector_bars()` 작성(§B.2) — REQ-001에서 재현 확인된
   거래일 중 `solo_count > 0`인 날짜(최소 3일)에 대해, `evaluate_detector_contribution()`의
   solo attribution 로직을 참고하여 별도로 재현한 읽기 전용 쿼리로 solo 시그널을 식별하고
   4-기준 병렬 재채점.
4. REQ-005 준비: M1 리포트(§B.3)를 Report-Before-Ask Gate 요건에 맞춰 작성.
5. REQ-004 검증: 기존 회귀 테스트 전체 통과 확인(§D).
6. REQ-006: 단일 로그 라인 기록.

### M2 — 결정 게이트 (본 SPEC 범위 밖·정보 제공용 — human 게이트, 자율 실행 아님)

1. M1 리포트를 사용자에게 제시.
2. AskUserQuestion으로 다음 중 선택: (a) 대안 기준 채택 + `momentum_continuation` 앙상블
   가중치 조정 방향 논의, (b) 대안 기준 채택 + `near_limit_up_carry` confidence/임계 조정
   방향 논의, (c) 두 탐지기 모두 현행 유지(측정 결과가 미흡하거나 표본 부족), (d) 확장 측정
   (표본 기간 연장) 필요.
3. 결정 내용을 `plan.md` §A의 "해소된 결정" 항목에 추가 기록.

### M3+ — 조건부 구현 (본 SPEC 범위 밖·정보 제공용 — Priority: Medium, M2 승인 시에만 진행)

M2에서 승인된 방향에 따라 세부 마일스톤을 M2 시점에 재수립한다. 본 SPEC은 M3+ 세부 작업을
사전에 확정하지 않는다 — `momentum_continuation`(앙상블 가중치 레버)과
`near_limit_up_carry`(confidence 공식/임계 레버)는 서로 다른 코드 변경 집합을 요구하므로
사전 확정은 거짓 정밀도다.

## §D — 사전 점검 (Pre-flight)

```bash
# 1. 현재 브랜치/베이스 확인
git branch --show-current
git rev-parse HEAD

# 2. 대상 모듈 임포트 사전 점검
cd backend && uv run python -c "from app.services.surge_detector import detect_momentum_continuation, detect_near_limit_up_carries; from app.services.surge_contribution_service import evaluate_detector_contribution; print('OK')"

# 3. 기존 기여도/평가 테스트 베이스라인
cd backend && uv run pytest tests/test_surge_contribution_service.py tests/test_near_limit_up_carry.py tests/test_surge_evaluation_service.py -q -m "not slow"

# 4. 앙상블 가중치 합=1.0 불변식 회귀 확인 (SPEC-AI-090이 건드리지 않았음을 재확인)
cd backend && uv run pytest tests/test_surge_detector.py -q -m "not slow" -k "ensemble or weight"
```

## §E — 제약 (DO NOT VIOLATE)

- M1은 `detect_momentum_continuation`/`detect_near_limit_up_carries`/
  `compute_ensemble_score`/`evaluate_detector_contribution`의 기존 로직을 **읽기만** 한다 —
  어떤 방식으로도 수정하지 않는다.
- `surge_detection.yaml`의 `ensemble.weights` 값(특히 `momentum_continuation: 0.12`)과
  `near_limit_up_carry` 관련 `NearLimitUpConfig` 기본값을 M1에서 변경하지 않는다(M3+ 승인
  시에만 재고 대상).
- `surge_detector_contribution` 테이블에 신규 로직을 통해 쓰지 않는다 — REQ-002/003의 결과는
  리포트 파일에만 기록한다.
- SPEC-AI-043 예측기록모드 유지 — `SurgeTrade`/`SurgePortfolio` 실행 로직 무변경.
- `.moai/reports/`와 `.moai/specs/`의 구분을 지킨다 — 분석 리포트는
  `.moai/reports/continuation-detector-eval-bar/`, SPEC 아티팩트는
  `.moai/specs/SPEC-AI-090/`.
- Never use `--no-verify`; Conventional Commits(`feat(SPEC-AI-090): M1 ...`) 형식 준수.

## §F — 자가검증 산출물 (Self-Verification Deliverables)

manager-develop이 M1 완료를 보고할 때 다음을 포함한다(verification-claim-integrity.md
5-section 형식 준수):

1. **AC PASS/FAIL 매트릭스** — spec.md의 각 AC-090-00N에 대한 실행 명령 + 실제 출력.
2. **재현 검증 원본 출력** — REQ-001의 재조회 쿼리와 실제 반환값(§Context 표와의 일치/불일치
   판정 포함).
3. **4-기준 hit-rate 표** — REQ-003 산출물 전체(탐지기 × 기준 × hit/miss/unmeasurable).
4. **회귀 없음 증거** — §D의 pre-flight 테스트 명령을 재실행한 결과, M1 이전과
   `surge_detection.yaml`/`surge_detector_contribution` upsert 경로가 diff 0임.
5. **M1 리포트 경로** — `.moai/reports/continuation-detector-eval-bar/` 하위 산출 리포트
   파일 경로.
6. **차단 사항(있다면)** — REQ-001 재현 실패, 또는 `solo_count > 0`인 거래일이 3일 미만으로
   표본이 부족한 경우, 구조화된 차단 보고 형태로 기술(AskUserQuestion을 직접 호출하지 않음).

## §G — Anti-Patterns (본 SPEC에서 특히 주의)

- **M2 없이 M3+ 진행**: M1 리포트만 보고 에이전트가 자율적으로 가중치·공식을 조정하는 것은
  Report-Before-Ask Gate 위반이자 이 SPEC의 핵심 설계 의도 위반이다.
- **momentum_continuation과 near_limit_up_carry를 동일한 레버로 취급**: 전자는 앙상블
  가중치 레버가 존재하지만 후자는 `standalone_bypass` 분류로 앙상블에 편입되지 않으므로
  가중치 레버가 없다(§선행 SPEC). M2 논의·M3+ 구현 모두 이 구분을 유지해야 한다.
- **대안 기준 결과를 기존 `surge_detector_contribution` 테이블에 소급 반영**: REQ-002/003은
  완전히 별도의 읽기 전용 파생 계산이다 — 기존 `solo_tp`/`coincident_hit_rate` 정의를 이
  SPEC에서 바꾸거나 덮어쓰지 않는다.
- **표본 부족 상태에서 결론 단정**: `solo_count`가 매우 작은 날(§Context 표에서 대부분
  1~5건)이 대부분이므로, 표본이 3일 미만이거나 solo 시그널 총량이 극히 적으면 리포트에
  통계적 한계를 명시하고 M2에서 "확장 측정 필요"를 하나의 선택지로 반드시 포함한다.

## §H — Cross-References

- spec.md § Context — 이 계획의 모든 마일스톤 순서의 근거(오케스트레이터 DB 조회 원본 데이터).
- spec.md § 선행 SPEC — `momentum_continuation`(ensemble_weighted_sum) vs
  `near_limit_up_carry`(standalone_bypass) 분류 근거(`surge_contribution_service.py`
  `DETECTOR_REGISTRY`).
- SPEC-AI-070 spec.md/`surge_contribution_service.py` — `evaluate_detector_contribution()`
  attribution 방식(REQ-003이 참고하되 수정하지 않는 로직).
- SPEC-AI-089 plan.md §A/§C — M1/M2 분리 패턴의 선행 사례.
- `.claude/rules/moai/core/askuser-protocol.md` § Report-Before-Ask Gate — M2 진행 시
  준수 대상.
