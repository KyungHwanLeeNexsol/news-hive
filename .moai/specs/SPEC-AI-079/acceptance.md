# Acceptance Criteria: SPEC-AI-079

volume_breakout 상대임계(z-score) 확장 기능 활성화의 인수 기준.

## Given-When-Then Scenarios

### Scenario 1 (P0) — 플래그 활성화 시 촉매/z-score 확장 경로가 실행된다

**Given** `surge_detection.yaml`의 `volume_breakout.relative_threshold_enabled`가 `true`이고,
절대 거래량 리더 유니버스 밖의 종목이 (a) 당일 공시 또는 최근 뉴스 커버리지를 보유하고,
(b) 자기 20일 거래량 대비 z-score >= 2.0(고정 3.0배 비율은 미달, 예: 2.5배)인 상태에서,

**When** `detect_volume_breakout()`이 실행되면,

**Then** 해당 종목은 촉매 유니버스 확장으로 후보군에 합류하고, z-score 상대 임계로
`SurgeCandidate`로 인정되어 반환된다.

- 검증 근거(기존 테스트): `test_surge_ai066.py::TestVolumeBreakoutRelative::test_relative_threshold_catches_midcap`
  (2.5배 중대형주 포착), `::test_catalyst_universe_expansion`(거래량 순위 밖 공시 종목 합류).
- 실증 대응: 011090(에넥스) 유형 — 뉴스 커버리지 보유 + 절대 거래량 순위 밖 종목의 구제.

### Scenario 2 (P0) — 플래그 비활성화(레거시) 시 후보에서 제외된다 (하위 호환)

**Given** `relative_threshold_enabled`가 `false`(레거시)이고, 동일하게 절대 거래량 순위 밖·
고정 3.0배 미달(2.5배)인 종목이 있는 상태에서,

**When** `detect_volume_breakout()`이 실행되면,

**Then** 촉매 유니버스 확장 경로와 z-score 상대 임계 경로가 **모두 실행되지 않아** 해당 종목은
후보에서 제외된다. (플래그가 확장 경로의 **유일한 게이트**임을 증명 → rollback 완전성 보장)

- 검증 근거(기존 테스트): `test_surge_ai066.py::TestVolumeBreakoutRelative::test_flat_only_excludes_subthreshold`.

### Scenario 3 (P0, Edge) — cold-start 폴백 무회귀

**Given** `relative_threshold_enabled`가 `true`이나 종목의 baseline 표본이 부족
(`sample_count < zscore_min_baseline_samples`)해 z-score가 None인 상태에서,

**When** `detect_volume_breakout()`이 실행되면,

**Then** 고정 3.0배 비율 경로로 폴백하여, 3.5배는 통과하고 2.5배는 제외된다(회귀 없음).

- 검증 근거(기존 테스트): `test_surge_ai066.py::TestVolumeBreakoutRelative::test_cold_start_falls_back_to_flat`.

### Scenario 4 (P0) — 모델 기본값 및 소유 경계 불변

**Given** 본 SPEC이 YAML 런타임 값만 `true`로 전환한 상태에서,

**When** `VolumeBreakoutConfig()` 및 소유 경계 설정을 확인하면,

**Then**
- `VolumeBreakoutConfig().relative_threshold_enabled`는 여전히 `False`(Pydantic 모델 기본값 불변),
- `volume_breakout_bypass_threshold`는 `0.30`(AI-063 불변),
- `ensemble.weights.volume_breakout`은 `0.11`(AI-062 불변)이다.

- 검증 근거(기존 테스트): `test_surge_ai066.py::test_new_fields_on_existing_configs`(모델 기본값=False),
  `::TestVolumeBreakoutRelative::test_ownership_boundary_unchanged`(가중치/bypass 불변).

### Scenario 5 (P2, Optional) — z-score 경로 관측성

**Given** REQ-AI079-005(P2)를 채택한 상태에서,

**When** `detect_volume_breakout()` 스캔이 완료되면,

**Then** z-score 경로(`qualifies_relative=True`)로 유입된 후보 수와 고정 3.0배 경로 후보 수를
**구분하는 INFO 레벨 집계 로그 1줄**이 방출된다. (종목별 로그·신규 스키마 없음)

- 미채택 시 본 시나리오는 스킵되며 SPEC은 001~004만으로 완결된다.

## Edge Cases (엣지 케이스)

- [EC-1] 촉매 종목이 0개인 스캔: 확장 경로가 빈 리스트 반환 → 레거시 리더 유니버스만 사용, 무회귀.
- [EC-2] 촉매 조회 중 예외: `try/except`로 무시하고 리더 유니버스만 사용(`:3989-3990`), 스캔 지속.
- [EC-3] 유니버스 합류 후 `max_candidates`(100) 상한 절단: 우선순위(리더 → 촉매) 유지.
- [EC-4] auto-improver가 이 키를 조정 대상으로 삼지 않음 확인 → 재시작 후에도 `true` 유지.

## Quality Gate Criteria (품질 게이트)

- `cd backend && uv run pytest tests/test_surge_ai066.py --tb=short -q` — 전량 통과.
- `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"` — 전체 회귀 통과.
  - CI 재현 시 `-n 4` xdist로도 확인(과거 `surge_detection.auto.yaml` 워커 공유 레이스 이력).
- `cd backend && uv run ruff check .` — 변경 파일 린트 통과.
- diff가 `surge_detection.yaml` 1줄(+ 선택적 P2 로그/테스트)에 국한.

## Definition of Done (완료 정의)

- [ ] REQ-AI079-001: `surge_detection.yaml:217` = `true`, 설정 로드 시 `True` 확인.
- [ ] REQ-AI079-002: 촉매 확장 + z-score 상대 임계 경로가 활성 설정에서 실행됨(Scenario 1).
- [ ] REQ-AI079-003: 모델 기본값(False)/기타 임계/AI-062 가중치/AI-063 bypass/타 탐지기 diff 0(Scenario 4).
- [ ] REQ-AI079-004: `test_surge_ai066.py` 및 전체 회귀 스위트 통과.
- [ ] REQ-AI079-005 (P2): (채택 시) z-score-vs-flat 구분 INFO 로그 1줄, 스키마 변경 없음.
- [ ] 배포 후 며칠간 `[거래량폭발]` INFO 로그로 신호량/구성 변화 관찰(R-1 완화).
