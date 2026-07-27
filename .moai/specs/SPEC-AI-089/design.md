# SPEC-AI-089 Design — 측정 스파이크 아키텍처 및 배선 옵션 비교

## 설계 원칙

1. **측정과 구현을 분리한다.** research.md가 보여주듯 "유니버스를 배선하라"는 지시는 최소 3가지
   서로 다른 구현(옵션 A/B/C, 아래)으로 해석될 수 있고, 그중 어느 것이 실제로 recall을 개선하는지
   현재는 알 수 없다. 잘못된 옵션을 먼저 구현하면 되돌리기 비쌀 수 있으므로(탐지 로직 변경 후
   운영 관찰 기간이 필요), 측정을 먼저 한다.
2. **측정 자체가 핫 패스 비용을 늘리지 않는다.** `gather_surge_candidates()`는 이미 계산이 끝난
   `_universe_codes`/`merged`를 갖고 있다 — 측정은 이 두 결과에 대한 순수 인메모리 집합 연산 +
   기존 테이블 조인이며, 신규 네트워크 조회를 추가하지 않는다(REQ-003/004).
3. **모든 신규 동작은 기본값 OFF.** SPEC-AI-076/084/086/087이 확립한 이 프로젝트의 강한 관례를
   따른다 — 측정 계측조차 명시적 설정 플래그 뒤에 둔다(우발적 프로덕션 성능 영향을 방지).

## M1 측정 아키텍처

```
gather_surge_candidates()
  ├─ (기존) 8개 1차 탐지기 실행 → merged
  ├─ (기존) build_scan_universe(existing_codes=merged.keys()) → _universe_codes, _entry_pool_map
  ├─ (기존) entry_pool 태깅 + persist_pool_counts/persist_universe_members
  └─ (신규, REQ-001) if config.universe_gap_measurement_enabled:
         gap = measure_universe_detection_gap(_universe_codes, _entry_pool_map, merged)
         → 로그 라인 1개 (REQ-007), 선택적으로 리포트 아티팩트에 append
```

`measure_universe_detection_gap`은 순수 함수(신규 DB 쓰기 없음, 기존 두 인메모리 구조체만
소비)로 설계한다 — `surge_detector.py`가 아닌 별도 모듈(예:
`app/services/surge_universe_gap_service.py`, SPEC-AI-068의 `surge_universe_pool_service.py`와
자매 모듈)에 둔다. 이는 SPEC-AI-074가 `_fetch_tracked_stock_codes`를
`stock_registry_service`로 추출한 선례(단일 출처, 관심사 분리)를 따른다.

REQ-002(무시그널 종목 풀 귀속)는 핫 패스가 아닌 **오프라인/배치 분석 스크립트** 또는 기존
평가 파이프라인(`surge_evaluation_service.py`, T+1 18:30 KST 잡)에 부가하는 것을 M1의 기본
설계로 한다 — 이는 `gather_surge_candidates()`의 실행 빈도(하루 6회)보다 훨씬 낮은 빈도(하루
1회, 이미 존재하는 평가 잡)로 실행되어 REQ-004(비용 예산)를 자연스럽게 만족한다.

## 배선 옵션 비교 (M2 결정 게이트의 입력 — 본 SPEC은 어느 것도 선택하지 않는다)

| 옵션 | 설명 | 예상 이득 | 예상 비용/리스크 | M1이 답해야 할 질문 |
|---|---|---|---|---|
| **A — 카테고리 1/2 탐지기 후보 합집합 확장** | Pool A/B/C 코드를 `theme_cluster`/`disclosure_pattern`/`volume_anomaly` 등의 입력 후보 집합에 합집합으로 추가 | 카테고리 2의 중복이 낮다면(연구 질문 1) 순증 recall 가능 | 탐지기별로 개별 배선 필요(N개 detector × 개별 리스크), 회귀 표면 넓음 | 연구 질문 1, 3 |
| **B — Pool B/`volume_breakout` 통합** | 중복 계산 제거: Pool B 산출물을 `volume_breakout`의 후보 소스로 재사용 | 네트워크 비용 절감(중복 fetch 제거) + 파라미터 통일로 일관성 개선 | 두 계산의 기존 차이(임계값 등)가 의도된 것이었다면 회귀 위험 | 연구 질문 2 |
| **C — 신규 앙상블 컴포넌트** | Pool B/C 소속 자체를 저가중치 점수원으로 앙상블에 추가 | 카테고리 3/4이 모두 놓치는 "순수 모멘텀만 있는" 종목 커버 | 앙상블 가중치 합=1.0 불변식 재조정 필요, 전체 시그널 분포 이동 위험 — 가장 높은 회귀 리스크 | 연구 질문 3 (Pool D 신규 소스와의 비교 포함) |
| **D(기각 후보) — group_cascade/gap_up_runners 필터 확장** | 카테고리 3(캐스케이드형)의 2차 필터에 유니버스 멤버십 추가 | research.md F-2가 보여주듯 1차 시드가 탐지되지 못하면 무의미 — 낮은 우선순위 | (기각 근거로만 기록) | — |

옵션 D는 research.md의 카테고리 3 분석에 근거하여 **낮은 우선순위**로 사전 기각하되, M2
리포트에서 사용자가 재고를 요청할 경우를 대비해 옵션 목록에 남겨둔다(임의로 완전히 배제하지
않음 — 최종 판단은 사용자 몫).

## M2 결정 게이트

M2는 자율 결정이 아니라 **human 게이트**다. orchestrator는 M1 측정 결과(연구 질문 1-4의 실측
답)를 `.claude/rules/moai/core/askuser-protocol.md` § Report-Before-Ask Gate를 준수하는 보고
형태로 사용자에게 제시한 뒤, AskUserQuestion으로 다음 중 하나를 확인받는다:

- 옵션 A/B/C 중 하나(또는 조합)를 승인하고 M3+에서 flag-gated로 구현
- 측정 결과가 배선의 가치를 뒷받침하지 않는다고 판단하여 배선을 보류(본 SPEC은 측정 리포트
  산출로 완료)
- 추가 측정이 필요하다고 판단하여 M1 범위를 확장

이 결정 자체는 본 SPEC 최초 작성 시점(v0.1.0 초안)에는 plan.md에
`[NEEDS CLARIFICATION: 배선 방식 A/B/C 중 선택]` 마커로 미해결 상태였다. plan-auditor iteration 1
FAIL(0.80, MP-7) 지적을 반영해 plan.md §A가 재작성되며 이 마커는 해소되었다 —
Implementation Kickoff Approval의 승인 범위를 M1(측정 스파이크)로 명시적으로 한정하는 "해소된
결정"으로 대체되었고, 배선 방식(옵션 A/B/C 중 선택 또는 배선 보류) 자체의 결정은 M1 완료 후에만
존재하는 별도의 AskUserQuestion 라운드(M2 결정 게이트)로 위임되었다(plan.md §A "해소된 결정"
참고). 즉 M1은 "일반 마일스톤"이 아니라 계획 자체를 확정하기 위한 선행 스파이크였다는 순서는
그대로 유지된다 — 다만 그 순서를 규정하는 마커는 더 이상 미해결 상태가 아니다.

## 롤아웃 안전장치 (M3+ 조건부)

M2에서 옵션이 승인될 경우에 한해:

1. 신규 설정 플래그 기본값 OFF (REQ-006).
2. Shadow 모드 우선 — 배선된 후보가 실제로 발행하는 시그널 수를 **로그만 하고 실제 발행하지
   않는** 중간 단계를 최소 1개 마일스톤으로 둔다(SPEC-AI-084의 "플래그 OFF 상태로 커밋" 관례와
   유사, 다만 본 SPEC은 한 단계 더 나아가 shadow 로깅까지 요구).
3. 카나리 판단 기준은 M1 리포트의 정량 수치(간극 비율, 예상 순증 시그널 수)를 근거로 M2에서
   함께 확정한다 — 임의 수치를 본 문서에서 사전에 못박지 않는다.

## 대안 검토 및 기각 근거

- **"즉시 옵션 A로 15개 탐지기 전부 배선"** (사용자 최초 지시의 문자 그대로의 해석) — research.md
  F-2/F-3이 보여주듯 카테고리 1(volume_anomaly)과 카테고리 3(cascade/carry)에는 유니버스 배선이
  구조적으로 무의미하거나 낮은 가치다. 무차별 배선은 회귀 표면만 넓히고 근본 문제(F-1)를 놓칠
  위험이 크다 — 기각.
- **"측정 없이 옵션 B(Pool B/volume_breakout 통합)만 바로 구현"** — 연구 질문 2(중복도)의 실측
  없이 두 계산을 통합하면, 현재의 파라미터 차이가 의도적 설계였는지 우연이었는지 알 수 없다 —
  M1 없이 진행 시 회귀 위험이 검증되지 않음 — 기각(대신 M1에서 우선 측정).
