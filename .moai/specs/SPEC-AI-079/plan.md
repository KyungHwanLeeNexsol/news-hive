# Implementation Plan: SPEC-AI-079

volume_breakout 상대임계(z-score) 확장 기능 활성화 — 설정값 전환 + 무회귀 검증.

## Technical Approach (기술 접근)

본 SPEC은 **로직 변경이 아니라 활성화 스위치 전환**이다. SPEC-AI-066에서 완성된 코드 경로가
`cfg.relative_threshold_enabled` 한 개 불리언으로 게이팅되어 있으므로, YAML 런타임 값 1줄만
전환하면 전체 기능이 프로덕션에서 가동된다.

핵심 설계 결정(검증 근거는 spec.md §2):
- **YAML 런타임 값만 전환**(`surge_detection.yaml:217` `false` → `true`).
- **Pydantic 모델 기본값(`surge_settings.py:142` `= False`)은 유지** — `test_surge_ai066.py:223`이
  모델 기본값=False를 단언하므로 이를 바꾸면 회귀. YAML 부재 폴백의 "안전 기본값(staged rollout)"
  의미도 보존된다.
- **auto.yaml 대상 여부 확인**: 이 키가 auto-improver(`surge_auto_improver.py`)가 덮어쓰는
  대상인지 Run 단계에서 확인. 대상이면 base yaml 변경이 재시작마다 유지되는지 검증(대상 아니면
  단순 base yaml 변경으로 충분). (관측 결과 이 키는 auto-improver 조정 대상 목록에 없음 —
  weights/min_score만 조정 — 이나 Run 단계에서 재확인.)

## Files to Modify (변경 파일)

| 파일 | 변경 | REQ |
|------|------|-----|
| `backend/app/surge_config/surge_detection.yaml` | `:217` `relative_threshold_enabled: false` → `true` | REQ-AI079-001 |
| `backend/tests/test_surge_ai066.py` | (선택) 활성화 상태 스모크 가드 1건 추가 검토 | REQ-AI079-004 |
| `backend/app/services/surge_detector.py` | (P2 optional만) `:4059` 부근 z-score-vs-flat 집계 INFO 1줄 | REQ-AI079-005 |

- **변경 파일 3개 미만**(핵심 경로는 YAML 1줄). Multi-File Decomposition 규칙 비해당.
- surge_detector.py 변경은 **P2 optional 채택 시에만** 발생. 미채택 시 YAML 1줄 + 테스트 확인만.

## Milestones (우선순위 기반, 시간 추정 없음)

### M1 (P0) — 활성화
- `surge_detection.yaml:217` 값을 `true`로 변경 (REQ-AI079-001).
- 변경 후 설정 로드 확인: `cd backend && uv run python -c "from app.surge_config.surge_settings import get_surge_config; print(get_surge_config().volume_breakout.relative_threshold_enabled)"` → `True` 출력.

### M2 (P0) — 무회귀 검증
- `cd backend && uv run pytest tests/test_surge_ai066.py --tb=short -q` 전량 통과 (REQ-AI079-004).
  - 특히 `TestVolumeBreakoutRelative`(양경로) + `test_new_fields_on_existing_configs`(모델 기본값=False) 통과 확인.
- `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"` 전체 회귀 통과.
  - **CI xdist 주의**: 과거 `surge_detection.auto.yaml` xdist 워커 공유 레이스 이력 있음 →
    CI 재현 시 `-n 4`로도 확인(로컬 기본 실행은 재현 안 될 수 있음).
- `cd backend && uv run ruff check .` (변경 파일 대상) 통과.

### M3 (P0) — 범위 봉쇄 검증
- diff가 `surge_detection.yaml` 1줄(+ 선택적 테스트/로그)에 국한됨을 확인 (REQ-AI079-003).
- Pydantic 모델 기본값(`surge_settings.py:142`)이 여전히 `= False`인지 확인.
- AI-062 가중치(0.11)/AI-063 bypass(0.30) diff 0 확인.

### M4 (P2, optional) — 관측성
- 채택 결정 시에만: `detect_volume_breakout()` 후보 루프에서 `qualifies_relative` 카운터를
  누적해 `:4059` 부근 스캔당 집계 INFO 1줄 추가 (REQ-AI079-005).
- 신규 테이블/컬럼/마이그레이션 없음. 종목별 INFO 스팸 금지.
- **미채택도 유효한 결과** — 001~004만으로 SPEC 완결 가능.

## Development Methodology

- 프로젝트 quality.yaml 모드에 따름(DDD 기본, 기존 코드 대상).
- 본 변경은 신규 로직이 없어 characterization test는 **기존 `test_surge_ai066.py`가 그 역할을
  이미 수행**한다(플래그 True/False 양경로 커버). M4(P2) 로그 추가 시에만 소규모 테스트 검토.
- Reproduction-First(Rule 4): 본 SPEC은 버그 수정이 아닌 기능 활성화 →
  "재현 테스트"는 실증 사례(011090 유형 = 촉매 종목이 z-score로 후보 진입)를 검증하는
  기존 `test_relative_threshold_catches_midcap` / `test_catalyst_universe_expansion`으로 충족.

## Post-Implementation Review (잠재 이슈)

- 활성화 후 첫 스캔부터 surge_candidate 후보 수 증가 예상 → precision 관찰 필요(R-1).
  Run 완료 후 며칠간 `[거래량폭발]` INFO 로그로 유니버스/후보 수 추이 확인.
- auto-improver가 recall 개선을 감지해 min_score를 낮추는 연쇄 효과 가능성 →
  본 SPEC 범위 밖이지만 활성화 후 auto-improver 로그 모니터링 권장.
- Rollback 경로: 문제 발생 시 `surge_detection.yaml:217`을 `false`로 되돌리면 즉시 레거시 복귀
  (플래그가 유일한 게이트이므로 완전 되돌림 보장).
