# SPEC-AI-104 Plan

## A. 구현 전략

Tier M, cycle_type: ddd(ANALYZE-PRESERVE-IMPROVE — `.moai/config/sections/quality.yaml`
`constitution.development_mode: ddd`). 범위는 spec.md §Goals 1-5에 근거한 5가지 변경
(precision 측정 신규 함수, 리포트 pool_d 열 결함 수정 + precision 병기, config canary
2건 전환, 활성화 게이트 기준 문서화)에 한정하며, 탐지기 스코어링·quota 배분·bridge
마스터 스위치·매수 실행 경로는 건드리지 않는다.

핵심 판단(결정 가역성이 높은 순 — 되돌리기 어려운 결정을 먼저 확정):

1. **신규 함수 `analyze_pool_precision_by_date()`의 반환 스키마**(spec.md §Decisions D3,
   REQ-AI104-005) — 가장 되돌리기 어려운 결정이다. 이 함수는 REQ-AI104-006 리포트와
   향후 활성화 게이트 판단(REQ-AI104-007)이 직접 소비하는 데이터 계약이므로, 스키마를
   나중에 바꾸면 리포트·plan.md 문서·향후 SPEC이 모두 연쇄 수정된다. TASK-001에서
   기존 `analyze_no_signal_pool_attribution()`의 반환 스키마(딕셔너리 키 명명 관례)와
   `measure_universe_detection_gap()`의 `*_gap_ratio` None-guard 관례를 그대로 따르는
   형태로 먼저 확정한다.
2. **`pool_d_min_slots` canary 값이 Pydantic 기본값이 아닌 YAML 값만 전환되는지
   재검증**(spec.md §Decisions D1) — 기존 테스트가 모델 기본값을 단언하고 있다면 이
   결정은 사실상 고정(가역성 낮음)이고, 없다면 향후 재량 여지가 남는다(가역성 중간).
   TASK-002에서 `test_spec_ai_086.py`/`test_spec_ai_096.py`/`test_spec_ai_102.py`를
   직접 확인한다.
3. **관측 창 5거래일 + precision 정량 임계값의 최종 확정**(spec.md §Open Questions 1-2)
   — 코드 배포가 아니라 관측 데이터 축적 이후의 문서 갱신이므로 가역성이 가장 높다.
   본 SPEC은 절차만 정의하고 숫자 확정은 배포 이후 후속 관찰로 미룬다.
4. 리포트 스크립트의 pool_d 열 추가 + precision 병기 형식(표 컬럼 순서 등) — 순수
   출력 포맷이라 언제든 조정 가능, 가역성 최고.

### A.1 PRESERVE 목록(수정 금지)

| 대상 | 사유 |
|------|------|
| `surge_trading_service.py` 전체, `fetch_current_prices_batch()` | 매수 주문 실행 경로 — REQ-AI104-003/008 |
| 8개 탐지기의 스코어링 알고리즘, `compute_ensemble_score()` | REQ-AI104-008 — 데이터 소싱 시점/범위와 무관 |
| `_source_scan_universe_pools()`의 Pool A/B/C/D 소싱 쿼리 필터·정렬 로직 | SPEC-AI-065/074/076/078/086 소유 — 본 SPEC은 config 값(`pool_d_min_slots`)만 전환, 쿼리 자체는 무변경 |
| `_assemble_scan_universe()`의 quota 배분 산술(`reserved_b/c/d`, clamp) | SPEC-AI-076/086 소유 — 무변경 |
| `generate_scan_universe_bridge_candidates()`, `scan_universe_bridge_candidates_enabled` | SPEC-AI-092/096 D4/102 소유 — 본 SPEC은 canary 값 전환 시에도 이 마스터 스위치를 False로 유지 |
| `measure_universe_detection_gap()`, `analyze_no_signal_pool_attribution()` (surge_universe_gap_service.py 기존 두 함수) | SPEC-AI-089 소유 — 신규 함수를 자매로 추가할 뿐 기존 두 함수는 무수정 |
| `existing` 병합 필터(`_pool_member_codes`), `scan_universe_include_existing` | SPEC-AI-094 소유 — 무관 |

## B. 작업 분해

### TASK-001: `analyze_pool_precision_by_date()` 신규 함수 구현

- 대상: `backend/app/services/surge_universe_gap_service.py`에
  `analyze_no_signal_pool_attribution()`의 자매 함수로 추가.
- 입력: `db: Session`, `trading_date: date`. 출력: pool별(`pool_a`/`pool_b`/`pool_c`/`pool_d`)
  `{total: int, surge_count: int, precision: float | None}` — `total==0`이면
  `precision=None`(기존 `*_gap_ratio` None-guard 관례 계승).
- 구현: `SurgeUniverseMember.entry_pool == pool` × `SurgeUniverseMember.trading_date ==
  trading_date` 로 pool별 코드 집합을 구하고, `SurgeActualOutcome.trading_date ==
  trading_date AND was_surge.is_(True)`로 실제 급등 코드 집합을 구해 교집합 비율을
  계산한다. 신규 DB 쓰기·마이그레이션 없음.
- 추적 REQ/AC: REQ-AI104-005 / AC-104-003, AC-104-004

### TASK-002: config canary 전환 사전조사 + 적용

- 대상: `backend/app/surge_config/surge_settings.py`, `backend/app/surge_config/surge_detection.yaml`.
- 사전조사(코드 변경 전): `grep -rn "pool_d_min_slots" backend/tests/` 로 모델 기본값을
  단언하는 기존 테스트가 있는지 확인한다. 있으면 그 값(0)과 신규 변경이 충돌하지 않음을
  확인한다(§A.핵심 판단 2).
- 적용: `surge_detection.yaml`의 `pool_d_min_slots: 0` → `pool_d_min_slots: 10`,
  `universe_gap_measurement_enabled: false` → `true`로 전환. `surge_settings.py`의
  Pydantic 기본값(`pool_d_min_slots: int = 0`)은 무변경.
- 추적 REQ/AC: REQ-AI104-002, REQ-AI104-004 / AC-104-001, AC-104-002

#### TASK-002 사전조사 결과 (run-phase 기록)

`grep -rn "pool_d_min_slots" backend/tests/` 실행 결과, 다음 3개 지점에서 **Pydantic 모델
기본값**(`0`)을 단언하는 기존 테스트를 확인했다:

- `test_spec_ai_086.py:91` — `assert cfg.pool_d_min_slots == 0` (기본 `SurgeDetectionConfig()`)
- `test_spec_ai_086.py:463` — 동일 단언(다른 테스트 케이스)
- `test_spec_ai_096.py:350` — `assert cfg.pool_d_min_slots == 0` (`scan_universe_bridge_candidates_enabled=False`
  상태 확인 테스트의 일부)

세 지점 모두 `SurgeDetectionConfig()`(인자 없는 기본 인스턴스화, 즉 Pydantic 모델 기본값)를
대상으로 하며, YAML 배포값을 로드하는 `get_surge_config()`를 대상으로 하지 않는다. 따라서
§Decisions D1의 "YAML 값만 canary로 전환, Pydantic 기본값 무변경" 결정과 **충돌하지 않는다**
— `surge_settings.py`의 `pool_d_min_slots: int = 0` 선언을 그대로 유지하면 위 3개 테스트는
canary 전환 후에도 그대로 통과한다.

추가로 확인: `universe_gap_measurement_enabled`는 현재 `surge_detection.yaml`에 키 자체가
**존재하지 않는다**(`grep -n "universe_gap_measurement_enabled" backend/app/surge_config/surge_detection.yaml`
결과 0건) — `get_surge_config()`가 `SurgeDetectionConfig.model_validate(surge_raw)`로 로드하므로
yaml에 없는 필드는 Pydantic 기본값(`False`)으로 폴백한다. 따라서 이 SPEC은 기존 값을
"수정"하는 것이 아니라 **신규 키를 yaml에 추가**해야 한다(REQ-AI104-004).

채택 근거: 사전조사 결과 충돌 없음을 확인했으므로 TASK-002 적용(§B TASK-002 적용 항목)을
그대로 진행한다.

### TASK-003: 측정 리포트 pool_d 열 결함 수정 + precision 지표 병기

- 대상: `backend/scripts/measure_universe_detection_gap_report.py` `_render_report()`.
- 거래일별 표에 `pool_d` 열을 추가(기존 "표본 합산" 집계 섹션과의 합계 일치를
  characterization 테스트로 검증).
- TASK-001의 `analyze_pool_precision_by_date()` 결과를 같은 리포트의 신규 섹션(예:
  "## Pool별 정밀도(Precision)")으로 병기 — pool_d와 pool_a/b/c baseline을 나란히 표시.
- 추적 REQ/AC: REQ-AI104-001, REQ-AI104-006 / AC-104-001, AC-104-005

### TASK-004: characterization 테스트 + 회귀 검증

- 신규: `test_spec_ai_104.py` — TASK-001 함수 단위 테스트(division-by-zero guard 포함),
  TASK-003 리포트 렌더링 pool_d 열 존재 + 합계 일치 검증.
- 회귀: `pytest tests/test_spec_ai_086.py tests/test_spec_ai_089.py tests/test_spec_ai_094.py
  tests/test_spec_ai_096.py tests/test_spec_ai_102.py -q` 전체 통과 확인(canary 전환 후에도
  기존 계약 불변임을 증명 — REQ-AI104-003/008; test_spec_ai_094.py는 §A.1 PRESERVE 목록의
  `existing` 병합 필터 회귀를 보장한다).
- 추적 REQ/AC: REQ-AI104-003, REQ-AI104-008 / AC-104-006, AC-104-007

### TASK-005: 활성화 게이트 기준 문서화 + CHANGELOG

- spec.md §Decisions D4의 복합 게이트(recall측 unique-catch + precision측 baseline 비교)를
  본 섹션(§C)에 최종 절차로 기록한다.
- CHANGELOG.md `[Unreleased]`에 "Pool D canary 관측 전환(`pool_d_min_slots: 10`,
  `universe_gap_measurement_enabled: true`) — 매매/탐지 경로 무영향, 관측 전용" 경고를
  남긴다(SPEC-AI-096 REQ-AI096-006 관례 계승).
- 추적 REQ/AC: REQ-AI104-007 / AC-104-008

## C. 활성화 게이트 절차 (REQ-AI104-007 산출물)

1. TASK-002 배포 이후, 최소 5거래일(SPEC-AI-096 D3 제안값 계승) 동안 canary 상태를
   유지하며 관측 데이터를 축적한다.
2. 관측 창 종료 후 `uv run python scripts/measure_universe_detection_gap_report.py --days N`을
   재실행해 recall측(pool_d unique-catch 여부)과 precision측(pool_d vs pool_a/b/c baseline)을
   함께 검토한다.
3. 판단 기준(문서화만, 실제 실행은 범위 밖):
   - recall측: 관측 창 내 pool_d 귀속 unique-catch(pool_a/b/c에는 없고 pool_d에만 있는
     무시그널 실제급등 종목)가 1건 이상 관측되었는가.
   - precision측: pool_d 정밀도가 pool_a/b/c 평균 대비 뚜렷이 낮지 않은가(구체적 임계값은
     실측 분포 확보 후 확정 — spec.md §Open Questions 1).
   - 표본 부족(pool_d 소속 종목이 관측 창 내내 0건): 관측 창 연장이 유효한 결론이다.
4. 위 기준을 모두 충족하면 `pool_d_min_slots`를 canary 값(10)을 넘어 추가 상향하거나
   `scan_universe_bridge_candidates_enabled`(SPEC-AI-096 D4) 활성화 절차로 진행하는
   것을 **별도 SPEC 또는 운영 판단**으로 상정한다 — 본 SPEC의 배포 산출물이 아니다.

## D. 위험

| 위험 | 완화 |
|------|------|
| canary 전환 후에도 뉴스-종목 관계 품질이 낮아 pool_d가 순수 노이즈일 가능성 | precision측 측정(TASK-001)이 정확히 이 위험을 정량화하기 위한 산출물이다 — 활성화 이전에 데이터로 확인 |
| 관측 창(5거래일) 내 실제 급등 표본 자체가 적어 결론을 내리기 어려울 가능성 | §C 절차 3항에 "표본 부족 시 창 연장"을 명시적 유효 결론으로 포함 |
| `universe_gap_measurement_enabled=true` 전환이 스캔 사이클 소요시간에 영향 | SPEC-AI-089 REQ-AI089-004 기존 [HARD] 불변식(비활성 대비 5% 이내, 안전 상한 대비 120초 여유) 재확인만 필요 — 신규 코드 없음 |
| Pydantic 기본값 관련 기존 테스트와의 충돌 | TASK-002 사전조사에서 선행 확인 |
