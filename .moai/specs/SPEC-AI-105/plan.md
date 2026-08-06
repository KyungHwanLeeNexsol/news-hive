# SPEC-AI-105 Plan

## A. 구현 전략

Tier M, cycle_type: ddd(ANALYZE-PRESERVE-IMPROVE — `.moai/config/sections/quality.yaml`
`constitution.development_mode: ddd`). 범위는 spec.md §Goals 1-5에 근거한 4가지 변경
(shadow 계측 신규 함수 + 영속화, pool별 정밀도 분석 함수, 리포트 병기, 활성화 게이트
문서화 + 전제조건 정정)에 한정하며, bridge 스코어링 함수 본체·마스터 스위치 실제 값·
탐지기/앙상블/quota/매매 실행 경로는 건드리지 않는다.

핵심 판단(결정 가역성이 높은 순 — 되돌리기 어려운 결정을 먼저 확정):

1. **신규 테이블 `surge_bridge_shadow_candidates`의 스키마**(spec.md REQ-AI105-002) —
   가장 되돌리기 어려운 결정이다. 이 테이블은 REQ-AI105-003 분석 함수와 향후 활성화
   게이트 판단(REQ-AI105-007)이 직접 소비하는 데이터 계약이므로, 나중에 스키마를
   바꾸면 분석 함수·리포트·향후 SPEC이 연쇄 수정된다. TASK-001에서 `SurgeUniverseMember`
   (SPEC-AI-068)의 composite PK + 일자당 replace 관례를 그대로 따르는 형태로 먼저
   확정한다.
2. **shadow 호출이 pool_b를 절대 포함하지 않도록 하드코딩하는 지점**(spec.md §Decisions
   D4) — config 값과 무관하게 코드 레벨에서 고정해야 하는 안전 불변식이므로, TASK-002에서
   `generate_scan_universe_bridge_candidates()` 호출부가 아니라 shadow 전용 wrapper
   함수 내부에서 `_target_pools`를 우회 없이 강제하는 방식으로 구현한다(가역성 중간 —
   나중에 pool_b shadow를 추가하려면 별도 SPEC이 이 지점을 명시적으로 개정해야 한다).
3. **분석 함수의 pool 분리 반환 규약**(spec.md REQ-AI105-003, §Decisions D2) — blended
   합산을 금지하는 반환 스키마 결정. 리포트(TASK-003)가 직접 소비하므로 TASK-002보다
   먼저 확정한다.
4. **활성화 게이트 절차 §C 문서 + 전제조건 정정** — 코드 배포가 아니라 문서 갱신이므로
   가역성이 가장 높다. 관측 데이터 축적 이후 후속 SPEC이 숫자만 갱신하면 된다.

### A.1 PRESERVE 목록(수정 금지)

| 대상 | 사유 |
|------|------|
| `generate_scan_universe_bridge_candidates()` 함수 본체(`surge_detector.py:5766-6012`) | REQ-AI105-001/006 — config override로 재호출만 하며 내부 로직은 절대 수정하지 않는다(§Decisions D1) |
| `_BRIDGE_MIN_SCORE`, pool_a/pool_c/pool_b 점수 산식, `scan_universe_bridge_max_candidates`, `scan_universe_bridge_pool_limits` 기본값 | SPEC-AI-092/102 소유 — 값·산식 무변경 |
| `scan_universe_bridge_candidates_enabled`(실제 마스터 스위치 값) | 이 SPEC 배포 후에도 `false` 유지(REQ-AI105-006) |
| 8개 탐지기의 스코어링 알고리즘, `compute_ensemble_score()` | REQ-AI105-006 — shadow 계측과 무관 |
| `_source_scan_universe_pools()`, `_assemble_scan_universe()`의 quota 배분(`reserved_b/c/d`) | SPEC-AI-065/074/076/078/086 소유 — 무변경 |
| `surge_trading_service.py` 전체 | 매수 주문 실행 경로 — REQ-AI105-006 |
| `measure_universe_detection_gap()`, `analyze_no_signal_pool_attribution()`, `analyze_pool_precision_by_date()`(surge_universe_gap_service.py 기존 함수) | SPEC-AI-089/104 소유 — 신규 함수를 자매로 추가할 뿐 기존 함수는 무수정 |
| `pool_d_min_slots`, Pool D 소싱 쿼리 전부 | SPEC-AI-104 소유 — 본 SPEC과 무관(§Context D3 정정 참고) |
| `scan_universe_bridge_pool_b_enabled`(SPEC-AI-102) | shadow 계측 하드코딩 배제 대상일 뿐 이 플래그 자체는 무변경(§Decisions D4) |

## B. 작업 분해

### TASK-001: `SurgeBridgeShadowCandidate` 모델 + 마이그레이션 + 영속화 함수

- 대상: `backend/app/models/surge_bridge_shadow_candidate.py`(신규),
  `backend/alembic/versions/`(신규 리비전), `backend/app/services/surge_universe_pool_service.py`
  (또는 신규 `surge_bridge_shadow_service.py`)에 `persist_bridge_shadow_candidates()` 추가.
- 스키마: composite PK `(trading_date, stock_code)`, `entry_pool: String(10)`,
  `bridge_score: Float, nullable=False`, `created_at: DateTime(timezone=True),
  server_default=func.now()`.
- 영속화 규약: `SurgeUniverseMember.persist_universe_members()`(`surge_universe_pool_service.py:110`)와
  동일한 일자당 delete-then-insert semantics를 그대로 재사용한다(동일 날짜 재실행 시
  스테일 코드 방지).
- **run-phase 착수 직전 필수 확인**: `cd backend && uv run alembic heads`로 현재 head가
  여전히 `074_surge_horizon_shadow_observation`인지 재확인한다 — 병렬 SPEC이 먼저
  머지되면 head가 이동할 수 있다(spec.md REQ-AI105-002 필수 조건).
- 추적 REQ/AC: REQ-AI105-002 / AC-105-001, AC-105-002

### TASK-002: shadow 계측 config + 호출부 wiring

- 대상: `backend/app/surge_config/surge_settings.py`, `backend/app/surge_config/surge_detection.yaml`,
  `backend/app/services/surge_detector.py`(호출부, `:2690-2705` 인근).
- config 신규 필드: `scan_universe_bridge_shadow_enabled: bool = False`(Pydantic 기본값
  무변경). `surge_detection.yaml`에서 이 SPEC의 배포 산출물로 `true`로 전환한다
  (SPEC-AI-104가 `universe_gap_measurement_enabled`를 다룬 것과 동일한 패턴 — 계측
  플래그는 무영향이 증명되므로 yaml 배포값을 직접 전환).
- 호출부 wiring: 기존 `_bridge_candidates = generate_scan_universe_bridge_candidates(...)`
  호출(`:2694`) **바로 다음**에, `config.scan_universe_bridge_shadow_enabled`가 `true`일
  때만 실행되는 별도 블록을 추가한다. 이 블록은:
  1. `config.model_copy(update={"scan_universe_bridge_candidates_enabled": True})`로
     shadow 전용 config 사본을 만든다.
  2. **pool_b 하드코딩 배제(§Decisions D4, §A 핵심판단 2)**: `entry_pool_map`을
     `{code: pool for code, pool in _entry_pool_map.items() if pool != "pool_b"}`로
     필터링한 사본을 만들어 shadow 호출에 전달함으로써, `scan_universe_bridge_pool_b_enabled`가
     이미 `true`인 배포 환경에서도 shadow 계측이 pool_b HTTP 조회를 유발하지 않도록
     구조적으로 보장한다.
  3. `generate_scan_universe_bridge_candidates(db, shadow_config, universe_codes,
     filtered_entry_pool_map, merged)`를 호출하되, **반환값을 `_bridge_candidates`나
     `qualified`에 절대 대입하지 않는다** — 별도 지역 변수(`_shadow_candidates`)로만
     받는다.
  4. `persist_bridge_shadow_candidates(db, date.today(), _shadow_candidates)`를 호출한다.
  5. 전체를 `try/except`로 감싸 실패 시 로그만 남기고 무시한다(기존 bridge 호출부와
     동일한 fail-open 관례).
- 추적 REQ/AC: REQ-AI105-001 / AC-105-003, AC-105-004

### TASK-003: pool별 shadow 정밀도 분석 함수

- 대상: `backend/app/services/surge_universe_gap_service.py`에
  `analyze_no_signal_pool_attribution()`/`analyze_pool_precision_by_date()`(SPEC-AI-104)의
  자매 함수로 `analyze_bridge_shadow_precision_by_date(db, trading_date)` 추가.
- 반환 스키마: `{"pool_a": {"total": int, "surge_count": int, "precision": float | None},
  "pool_c": {...}}` — **`pool_a`/`pool_c` 키를 항상 분리 반환하며 blended 합산 키를
  추가하지 않는다**(§Decisions D2, REQ-AI105-003).
- 구현: `surge_bridge_shadow_candidates.entry_pool == pool` × `trading_date == trading_date`로
  pool별 shadow 코드 집합을 구하고, `SurgeActualOutcome.trading_date == trading_date
  AND was_surge.is_(True)`와 교집합 비율을 계산한다. `total == 0`이면 `precision=None`.
  신규 DB 쓰기 없음.
- 추적 REQ/AC: REQ-AI105-003 / AC-105-005, AC-105-006

### TASK-004: 리포트에 pool별 shadow 정밀도 병기

- 대상: `backend/scripts/measure_universe_detection_gap_report.py`(SPEC-AI-089/104
  기존 스크립트 확장) `_render_report()`.
- TASK-003의 `analyze_bridge_shadow_precision_by_date()` 결과를 신규 섹션(예: "## Bridge
  Shadow 정밀도")으로 병기 — `pool_a`/`pool_c`를 별도 행으로 표시(blended 표시 금지,
  §Decisions D2).
- 추적 REQ/AC: REQ-AI105-005 / AC-105-007

### TASK-005: characterization 테스트 + 회귀 검증

- 신규: `test_spec_ai_105.py` — TASK-001 영속화 함수(delete-then-insert 재실행 안정성),
  TASK-002 wiring(shadow_enabled=False일 때 완전 무동작 + shadow_enabled=True일 때도
  `qualified`/`merged` 불변 + pool_b 하드코딩 배제 검증), TASK-003 함수(pool 분리 반환 +
  division-by-zero guard), TASK-004 리포트 렌더링 단위 테스트.
- 회귀: `uv run pytest tests/test_spec_ai_092.py tests/test_spec_ai_096.py
  tests/test_spec_ai_102.py -q` 전체 통과 확인(`test_spec_ai_104.py`는 SPEC-AI-104가
  아직 draft/미배포라 파일이 존재하지 않음 — run-phase 착수 시점에 존재하면 추가한다).
- 추적 REQ/AC: REQ-AI105-006 / AC-105-008, AC-105-009

### TASK-006: 전제조건 정정 + 활성화 게이트 문서화 + CHANGELOG

- spec.md §Context "핵심 정정"(Pool D 무관성)을 본 섹션(§C)과 CHANGELOG.md에 반영한다.
- spec.md §Decisions D5(비교 기준선)와 REQ-AI105-007의 복합 절차(관측기간 + 기준선
  비교 + 좁은 범위 우선 활성화)를 본 섹션(§C)에 최종 절차로 기록한다.
- CHANGELOG.md `[Unreleased]`에 "bridge shadow 계측 전환(`scan_universe_bridge_shadow_enabled:
  true`) — 매매/탐지 경로 무영향, 관측 전용. 실제 bridge 마스터 스위치는 여전히
  `false`" 경고를 남긴다(SPEC-AI-096 REQ-AI096-006 / SPEC-AI-104 관례 계승).
- 추적 REQ/AC: REQ-AI105-004, REQ-AI105-007 / AC-105-010

## C. 활성화 게이트 절차 (REQ-AI105-007 산출물)

1. TASK-002 배포 이후, 최소 10거래일(SPEC-AI-096 D4 제안값 계승) 동안 shadow 계측
   상태를 유지하며 pool별 관측 데이터를 축적한다.
2. 관측 창 종료 후 `measure_universe_detection_gap_report.py`를 재실행해
   `analyze_bridge_shadow_precision_by_date()` 산출물(pool_a/pool_c 분리)을 확인하고,
   같은 기간 `SurgePredictionEvaluation.precision`(시스템 전체 일일 정밀도, 이미
   영속화됨)을 기준선으로 비교한다.
3. 판단 기준(문서화만, 실제 실행은 범위 밖) — **pool_a와 pool_c를 독립적으로 판정**:
   - precision측: 해당 pool의 shadow 정밀도가 기준선 대비 뚜렷이 낮지 않은가(구체적
     정량 임계값은 실측 분포 확보 후 확정 — spec.md §Open Questions 1).
   - 표본 부족(해당 pool의 shadow 후보가 관측 창 내내 0건): 관측 창 연장이 유효한
     결론이다.
   - Pool C 특칙(§Decisions D2 push-back 계승): pool_c 정밀도가 기준선에 근접하더라도
     그 자체가 "필터가 유효했다"는 증거는 아니다 — pool_c 자신의 유니버스 진입 기준
     (5%)이 이미 강한 사전선별이므로, shadow 관측 데이터에서 pool_c 단독 정밀도가
     시스템 평균과 비슷한 수준이라면 이는 "pool_c 진입 자체가 이미 좋은 신호"라는
     해석과 "bridge 점수가 추가 변별력을 준다"는 해석을 구분하지 못한다 — 이 구분은
     이 SPEC의 범위 밖이며, 다음 후속 SPEC이 판단해야 할 항목으로 명시적으로 남긴다.
4. 위 기준을 pool_a 또는 pool_c 중 하나 이상이 충족하면, **기존
   `scan_universe_bridge_pool_limits`의 0-값 메커니즘**(예: 아직 기준을 충족하지
   못한 pool은 `0`으로, 충족한 pool만 기존 기본값으로)을 사용해 `scan_universe_bridge_candidates_enabled`를
   `true`로 전환하는 좁은 범위 우선 활성화를, 신규 "대상 pool 부분집합" 플래그 추가
   없이 진행할 수 있다 — 이 전환 자체는 **별도 SPEC 또는 운영 판단**으로 상정한다
   (본 SPEC의 배포 산출물이 아니다).
5. 관측 중 precision이 기준선 대비 유의하게 낮거나
   `generate_scan_universe_bridge_candidates()`(shadow 호출 경로) 예외율이 상승하면
   `scan_universe_bridge_shadow_enabled`를 즉시 `false`로 되돌린다(단일 값 변경,
   데이터 손실 없음 — shadow 테이블 행은 그대로 보존).

## D. 위험

| 위험 | 완화 |
|------|------|
| shadow 계측이 pool_c의 근본적 무필터 특성을 "정밀도가 낮지 않다"로 오독시켜 성급한 활성화를 부를 가능성 | §C 절차 3항에 Pool C 특칙을 명시 — 정밀도 수치만으로 자동 판단하지 않고 다음 후속 SPEC의 별도 검토를 요구 |
| 신규 테이블이 매 스캔 사이클마다 행을 추가해 장기적으로 커질 가능성 | `scan_universe_bridge_max_candidates`(20)로 이미 상한이 걸려 있어 일자당 최대 20행 — 다른 관측 테이블(`SurgeUniverseMember`)과 동일한 성장률 |
| shadow config override(`model_copy`)가 원본 config 객체를 실수로 공유 참조해 마스터 스위치가 실제로 바뀌는 회귀 | AC-105-004에서 override 이후 원본 `config.scan_universe_bridge_candidates_enabled`가 `false`로 남아있음을 명시적으로 단위 테스트 |
| pool_b 하드코딩 배제 로직이 향후 코드 이동으로 누락되는 회귀 | TASK-005 characterization 테스트에 `scan_universe_bridge_pool_b_enabled=True`로 설정한 fixture에서도 shadow 결과에 pool_b가 등장하지 않음을 명시적으로 포함 |
