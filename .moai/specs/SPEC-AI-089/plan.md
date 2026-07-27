# SPEC-AI-089 Plan — 스캔 유니버스→탐지 배선 측정 스파이크

## §A — 결정 게이트 (가장 변경 가능성 높은 결정 — 최우선 검토)

### 해소된 결정 — Implementation Kickoff Approval의 범위는 M1으로 한정한다

배선 방식(design.md § 배선 옵션 비교의 옵션 A/B/C, 또는 배선 보류)은 본 SPEC 작성 시점에는
실측 데이터가 없어 확정할 수 없다. 이 미확정 상태를 결정 지점으로 명시적으로 다루기 위해,
다음을 **해소된 결정(resolved decision)**으로 기록한다 — 이는 Implementation Kickoff
Approval 이전에 반드시 해소되어야 했던 마커를 대체하는 내용이며, 더 이상 미해결 마커가
아니다:

- 본 SPEC의 **Implementation Kickoff Approval은 M1(측정 스파이크)의 실행만을 승인**한다.
  M1은 읽기 전용 계측이며 어떤 탐지 로직도 변경하지 않는다(REQ-003).
- 배선 방식(옵션 A/B/C 중 선택, 또는 배선 보류) 결정은 **M1 완료 후에만 존재하는 새로운
  AskUserQuestion 라운드**(M2 결정 게이트)로 명시적으로 위임한다. 이 라운드는 M1의 실측
  결과(간극 비율, 무시그널 종목 풀 귀속 분류)를 근거로 진행하며, 본 SPEC의 Implementation
  Kickoff Approval에 의해 사전 승인되지 않는다.
- **M2는 본 SPEC의 Implementation Kickoff Approval이 승인하는 자율 실행 범위에 포함되지
  않는다.** M2 승인이 없으면 M3+(실제 배선 구현)는 시작되지 않으며, M1 완료 + 리포트
  제출만으로 본 SPEC은 유효하게 완료된다(구현 없이 완료되는 것이 valid한 결과 —
  acceptance.md Definition of Done 참고).

design.md § 배선 옵션 비교의 옵션 A(탐지기 후보 합집합 확장)/B(Pool B·volume_breakout 통합)/
C(신규 앙상블 컴포넌트)는 서로 다른 코드 변경 범위·리스크 프로파일을 가진다. 그 선택은 M2에서
사용자가 내린다(design.md § M2 결정 게이트).

이 SPEC의 run-phase는 **M1까지만 자율 실행**하고, M1 완료 시점에 orchestrator가 결과를
Report-Before-Ask Gate 준수 형태로 사용자에게 제시한 뒤 새로운 AskUserQuestion 라운드로
M2를 진행한다. M3+는 M2 승인 내용에 따라 본 SPEC의 후속 마일스톤으로 진행하거나, 승인된
범위가 크면 별도 후속 SPEC(SPEC-AI-09X)으로 분리할 수 있다 — 이 분리 여부 자체도 M2에서
함께 결정한다.

## §B — 신규 인터페이스/데이터 형태 (M1 산출물의 형태 — 두 번째로 변경 가능성 높음)

### B.1 측정 함수 시그니처 (제안, M1에서 확정)

```python
# app/services/surge_universe_gap_service.py (신규 모듈, design.md 근거)
def measure_universe_detection_gap(
    universe_codes: list[str],
    entry_pool_map: dict[str, str],   # {code: "pool_a"|"pool_b"|"pool_c"|"pool_d"|"existing"}
    merged_candidates: dict[str, "SurgeCandidate"],
) -> dict:
    """풀별 raw 개수, 탐지망 교집합 개수, 미탐지망 차집합 개수를 반환한다.

    반환 dict 키(제안): pool_a_total, pool_a_covered, pool_b_total, pool_b_covered,
    pool_c_total, pool_c_covered (D 포함 시 pool_d_*). 신규 DB 스키마 없음 — 로그/리포트
    아티팩트 전용 반환값.
    """
```

이 시그니처는 M1 구현 중 확정되며, 정확한 반환 필드명은 M1 완료 보고서에 실제 사용된 형태로
기록한다(본 plan.md는 설계 방향만 제안).

### B.2 REQ-002 귀속 분석 산출물 형태

오프라인 분석(design.md 근거로 `surge_evaluation_service.py` 부가 또는 별도 스크립트)의 산출물은
`.moai/reports/surge-universe-gap/{YYYY-MM-DD}.md` 형태의 사람이 읽을 수 있는 리포트로 한다
(코드 변경이 아닌 분석 리포트이므로 `.moai/reports/`가 올바른 위치 — `.moai/specs/`가 아님, per
`moai-workflow-spec` § SPEC vs Report 분류).

## §C — 마일스톤 (우선순위 기반, 시간 추정 없음)

**본 SPEC의 run-phase 실행 범위는 M1으로 한정된다.** M2(결정 게이트)와 M3+(조건부 구현)는
계획 참고용으로 아래에 기술하지만, 본 SPEC의 Implementation Kickoff Approval이 승인하는
자율 실행 대상이 아니다 — M2는 M1 완료 후에만 존재하는 별도의 human AskUserQuestion
라운드이고, M3+는 M2 승인이 있어야만(그것도 별도 후속 SPEC으로 분리될 수 있음) 존재하는
조건부·정보 제공용 범위다.

### M1 — 측정 계측 구현 (Priority: High, 본 SPEC의 run-phase 실행 범위 — 유일한 자율 실행 마일스톤)

1. `measure_universe_detection_gap()` 신규 함수 작성 (§B.1) — 순수 함수, 신규 네트워크 조회 없음.
2. `gather_surge_candidates()`에 §design.md 아키텍처 다이어그램대로 훅 추가 — 신규 설정 플래그
   `universe_gap_measurement_enabled: bool = False`(기본 OFF) 뒤에 게이팅.
3. REQ-002 귀속 분석 — 표본 기간(최소 3~5 거래일, 무시그널 실제급등 종목이 존재하는 최근 구간)에
   대해 `SurgeActualOutcome` × `SurgeUniverseMember` × `FundSignal` 조인으로 산출.
4. 연구 질문 1-3(research.md § 열린 질문)에 대한 실측 답을 리포트에 기록.
5. 기존 회귀 테스트 전체 통과 확인.

### M2 — 결정 게이트 (본 SPEC 범위 밖·정보 제공용 — orchestrator가 사용자와 함께 진행하는 human 게이트, 자율 실행 아님)

1. M1 리포트를 Report-Before-Ask Gate 요건에 맞춰 정리(투자 원천별 커버리지, 정량 수치).
2. AskUserQuestion으로 옵션 A/B/C/보류/확장측정 중 선택.
3. 결정 내용(선택된 옵션 또는 보류 여부)을 `plan.md` §A의 "해소된 결정" 항목에 추가 기록.

### M3+ — 조건부 구현 (본 SPEC 범위 밖·정보 제공용 — Priority: Medium, M2 승인 시에만 진행)

M2에서 승인된 옵션에 따라 세부 마일스톤을 M2 시점에 재수립한다. 본 SPEC은 M3+ 세부 작업을
사전에 확정하지 않는다(옵션 A/B/C가 서로 다른 코드 변경 집합을 요구하므로, 사전 확정은 거짓
정밀도다). M2에서 "본 SPEC 범위 내 진행" 또는 "별도 후속 SPEC 분리" 여부도 함께 결정.

## §D — 사전 점검(Pre-flight)

```bash
# 1. 현재 브랜치/베이스 확인
git branch --show-current
git rev-parse HEAD

# 2. 대상 모듈 임포트 사전 점검
cd backend && uv run python -c "from app.services.surge_detector import gather_surge_candidates, build_scan_universe; print('OK')"

# 3. 기존 유니버스/평가 테스트 베이스라인
cd backend && uv run pytest tests/test_surge_universe_members.py tests/test_surge_universe_pool_bugfix.py tests/test_surge_evaluation_service.py -q -m "not slow"

# 4. SPEC-AI-086/087 회귀 없음 확인 (선행 SPEC 무변경 검증)
cd backend && uv run pytest tests/test_surge_detector.py -q -m "not slow" -k "universe or scan_universe"
```

## §E — 제약 (DO NOT VIOLATE)

- M1은 `gather_surge_candidates()`의 기존 8개 탐지기 로직, `build_scan_universe()`의 풀 계산·
  quota 배분 로직을 **읽기만** 한다 — 어떤 방식으로도 수정하지 않는다.
- `_GATHER_TIMEOUT_S`(1200) 예산에 영향을 주는 변경 금지 — 측정은 인메모리 연산 + 기존 조인만.
- `SurgeDetectionConfig.ensemble.weights` 합=1.0 불변식(`validate_ensemble_weights`) M1에서
  건드리지 않음(M3+ 옵션 C가 승인될 경우에만 재고 대상, 그 경우도 별도 마이그레이션 계획 필요).
- SPEC-AI-043 예측기록모드 유지 — `SurgeTrade`/`SurgePortfolio` 실행 로직 무변경.
- `.moai/reports/`와 `.moai/specs/`의 구분을 지킨다 — 분석 리포트는 `.moai/reports/
  surge-universe-gap/`, SPEC 아티팩트는 `.moai/specs/SPEC-AI-089/`.
- Never use `--no-verify`; Conventional Commits(`feat(SPEC-AI-089): M1 ...`) 형식 준수.

## §F — 자가검증 산출물 (Self-Verification Deliverables)

manager-develop이 M1 완료를 보고할 때 다음을 포함한다(verification-claim-integrity.md 5-section
형식 준수):

1. **AC PASS/FAIL 매트릭스** — acceptance.md의 각 AC에 대한 실행 명령 + 실제 출력.
2. **비용 예산 불변식 증거** — M1 계측 활성화 상태로 `gather_surge_candidates()`를 로컬/스테이징
   환경에서 1회 실행한 소요 시간이 (a) 계측 비활성 상태 대비 **5% 이내 증가**하고 (b)
   `_GATHER_TIMEOUT_S`(1200초)보다 최소 120초 낮은 수준(**1080초 이하**)을 유지함을 보이는
   측정값(REQ-AI089-004 / AC-089-004 검증 — spec.md·acceptance.md와 동일한 정량 임계값).
3. **회귀 없음 증거** — §D의 pre-flight 테스트 명령을 재실행한 결과, M1 이전과 시그널 생성 결과가
   바이트 동등함(계측 플래그 기본 OFF 상태).
4. **M1 리포트 경로** — `.moai/reports/surge-universe-gap/` 하위 산출 리포트 파일 경로.
5. **차단 사항(있다면)** — 연구 질문 1-3 중 신규 스키마 없이 답할 수 없는 것이 발견되면 구조화된
   차단 보고 형태로 기술(AskUserQuestion을 직접 호출하지 않음).

## §G — Anti-Patterns (본 SPEC에서 특히 주의)

- **M2 없이 M3+ 진행**: M1 리포트만 보고 에이전트가 자율적으로 옵션을 선택해 구현하는 것은
  Report-Before-Ask Gate 위반이자 이 SPEC의 핵심 설계 의도(design.md § M2 결정 게이트) 위반이다.
- **측정 로직을 탐지 경로에 병합**: `merge_surge_candidates`나 개별 탐지기 함수 본체를 "측정
  겸 로깅"을 이유로 수정하는 것은 REQ-003 위반이다. 측정은 항상 별도 훅으로 추가한다.
- **옵션 A/B/C를 동시에 구현**: M2가 열린 결정임을 무시하고 "일단 다 만들어 두자"는 접근은
  회귀 표면을 불필요하게 넓힌다 — M2에서 승인된 것만 구현한다.

## §H — Cross-References

- research.md § 재검증 대상, § 신규 발견, § 열린 질문 — 이 계획의 모든 마일스톤 순서의 근거.
- design.md § M1 측정 아키텍처, § 배선 옵션 비교, § M2 결정 게이트.
- SPEC-AI-086/087 spec.md — 선행 SPEC의 Exclusion/Ownership 경계.
- `.claude/rules/moai/core/askuser-protocol.md` § Report-Before-Ask Gate — M2 진행 시 준수 대상.
