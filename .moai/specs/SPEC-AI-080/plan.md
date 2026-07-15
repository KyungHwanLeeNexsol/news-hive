# Implementation Plan: SPEC-AI-080

동일-당일 고확신 공시 촉매의 즉시 급등 시그널 발화 — 이벤트 구동 공시 경로 repurpose + recall 지표 편입.

## Technical Approach (기술 접근)

핵심은 **새 탐지기 신설이 아니라 기존 이벤트 구동 경로의 전용화(repurpose)** 다. DART 수집 시점에
실행되는 `process_disclosure_impact()`(disclosure_impact_scorer.py:355)에, 고확신 이벤트 클래스 +
계약금액/시총 스케일 `impact_score` 임계를 만족하면 **30분 반영 게이트를 우회하고 즉시 급등-집계
시그널을 발화**하는 분기를 추가한다.

설계 근거(검증됨, spec.md §2):

- **`impact_score` 재사용(REQ-002).** `score_disclosure_impact()`(`:163`)의 계약 경로(`:181-190`)가
  이미 `ratio = 계약금액/시총 → min(ratio*500, 100)`로 스케일한다. 따라서 즉시 발화 게이팅은
  이 점수 + 신규 config 임계(예: `immediate_surge_min_impact`)만으로 충분하고, surge_detector의
  flat 0.82 상수는 손대지 않는다(범위 축소).
- **고확신 클래스 한정(REQ-003).** `_IMMEDIATE_EVENT_PATTERNS`(surge_detector.py:1325-1342) 및
  계약/M&A 키워드 계열을 화이트리스트로 재사용. 루틴 거버넌스는 이미 5점 캡으로 자연 배제.
- **recall 편입(REQ-004).** 발화 시그널을 `signal_type="surge_candidate"` +
  `surge_metadata`(SPEC-AI-075 태깅 패턴, same-day-event-driven 근거)로 발신. T-1 종가 이후 접수분은
  `created_at`(T-1)로 기존 T-1→T 버킷에 자연 편입. 당일(T) 장중 접수분은 `evaluate_surge_predictions`에서
  T-1→T 버킷 배제 + 별도 same-day 서브지표로 분리(SPEC-AI-075 배제 로직 재사용/대칭).
  **단(v0.2.0, spec.md [E-9]): 이 "자연 편입"은 익일 배치 재탐지 업서트(fund_manager.py:1436-1464)와
  SPEC-AI-039 캐리오버(fund_manager.py:1542-1597)가 `created_at`을 무조건 T로 덮어써 그대로는 유지되지
  않는다. 배치(10:00·15:20 KST)가 평가(18:30 KST)보다 먼저 돌므로 덮어쓰기가 평가 전에 반영된다 →
  즉시 발화 행의 T-1 `created_at`과 식별 마커를 이 두 사이트가 보존하도록 통합해야 한다(REQ-004 불변식,
  REQ-006, DP-1). 또한 발화 시그널은 `surge_metadata`를 non-None으로 채워야 predicted_set에 포함된다
  (surge_evaluation_service.py:554).**
- **페이퍼 트레이딩 미배선(REQ-005).** 신규 발화 경로는 `_create_disclosure_signal`을 재사용하지
  않거나, 재사용 시 `execute_signal_trade` 호출 분기를 타지 않도록 별도 함수로 구현.

## 결정 지점 (Decision Points — Run 단계 확정)

- **DP-1 (기존 업서트/캐리오버 통합 방식, REQ-006 — v0.2.0 개정):** [E-9] 발견으로 원래 프레이밍
  "(i) 신규 (종목,날짜) 디듀프 vs (ii) 배치 윈도우 이후 한정"은 무효화됨 — **네이티브 5역일 업서트
  (fund_manager.py:1436-1464)가 이미 중복 INSERT를 막고 있어 "신규 디듀프"는 대체로 중복 구현**이고,
  진짜 문제는 그 업서트와 SPEC-AI-039 캐리오버(fund_manager.py:1542-1597)가 즉시 발화 행의
  `created_at`(과 업서트의 경우 `surge_metadata`)을 덮어써 T-1 귀속을 파괴하는 것이다. 개정 선택지:
  (i) **마커 인지형 스킵** — 즉시 발화 행을 surge_metadata 마커로 식별해 두 덮어쓰기 사이트가 created_at·
  마커를 보존하도록 기존 메커니즘에 통합, (ii) 윈도우 한정 — 익일 재탐지·캐리오버 덮어쓰기는 못 막아
  **단독 불충분**, (i)의 보완재, (iii) 평가 버킷팅을 `coalesce(originally_created_at, created_at)`로 이동 —
  전 캐리오버 시그널 recall 의미 변경 → 회귀 위험 큼. **권장: (i) 마커 인지형 스킵** — 기존 네이티브
  메커니즘 재사용, blast radius를 두 사이트로 최소화, REQ-004 불변식 직접 충족. Annotation 사이클에서 확정.
- **DP-2 (서브지표 영속화, REQ-004/OQ-4):** 당일 서브지표를 평가 함수 내 파생 계산으로만 둘지,
  `surge_prediction_evaluation`에 라벨 컬럼 추가할지. **권장: 파생 계산(스키마 무변경)**. 스키마
  확장 필요 시 사용자 승인.
- **DP-3 (타임존, OQ-1):** `created_at` UTC/KST 정합 확인 후 심야 접수 보정 여부 결정.

## Files to Modify (변경 파일 — Run 단계 참조)

| 파일 | 예상 변경 | REQ |
|------|-----------|-----|
| `backend/app/services/disclosure_impact_scorer.py` | `process_disclosure_impact`에 고확신 즉시 발화 분기 추가; 페이퍼 트레이딩 미배선 신규 발화 함수 | REQ-001/002/003/005 |
| `backend/app/services/surge_evaluation_service.py` | `evaluate_surge_predictions`에 즉시 발화 시그널 recall 편입 + 당일 접수분 지평 분리(서브지표) | REQ-004 |
| `backend/app/services/fund_manager.py` | **[v0.2.0 신규]** surge_candidate 재탐지 업서트(`:1436-1464`)와 SPEC-AI-039 캐리오버(`:1542-1597`)가 즉시 발화 행(surge_metadata 마커)의 `created_at`/`surge_metadata`를 덮어쓰지 않도록 마커 인지형 스킵 분기 추가. 마커 미검출 시 기존 거동 완전 불변 — **이 두 사이트는 다른 surge_candidate 생산자 행도 공유 조회 키로 덮어쓰는 고 fan_in 경로라 무회귀가 특히 중요(spec.md R-7)** | REQ-004 불변식/006 |
| `backend/app/surge_config/surge_detection.yaml` | 신규 config 키(예: `immediate_surge.enabled`, `immediate_surge_min_impact`, 이벤트 클래스 목록/임계) | REQ-001/002/003 |
| `backend/app/services/surge_detector.py` | **원칙적으로 미변경** — flat 0.82는 범위 밖([X-4]). 필요 시 키워드 목록 공유용 read-only 참조만 | (해당 시) REQ-003 |

- **`surge_detector.py` flat 0.82는 건드리지 않는다**(spec.md [X-4]). 위 표의 `surge_detector.py`는
  화이트리스트 상수 공유를 위한 read-only 임포트에 한함 — 로직/상수 변경 아님.
- **[v0.2.0] `fund_manager.py` 변경은 오직 마커 인지형 스킵 분기 추가**로 한정 — surge_candidate 업서트/
  캐리오버의 기존 스코어링·carry decay·매수 배선은 불변. 즉시 발화 마커가 없는 모든 기존 시그널에 대해
  거동이 비트 단위로 동일해야 함(무회귀).
- 4개 파일 수정 예상(disclosure_impact_scorer, surge_evaluation_service, fund_manager, surge_detection.yaml)
  → **Multi-File Decomposition 규칙 적용**: 아래 마일스톤 단위로 분해.

## Milestones (우선순위 기반, 시간 추정 없음)

### M0 (P0) — Run 전 확정 (Decision Points)
- OQ-1(타임존), DP-1(디듀프/윈도우), DP-2(서브지표 영속화) 확정.
- 재현 테스트 기준일(신테카바이오 07-09 16:41 유형)을 characterization 픽스처로 확보.

### M1 (P0) — 즉시 발화 분기 (disclosure_impact_scorer.py)
- `process_disclosure_impact`에 고확신 클래스 + `impact_score >= immediate_surge_min_impact` 판정 →
  즉시 `surge_candidate`(+surge_metadata) 발화 함수 추가 (REQ-001/002/003).
- `run_reflection_check`/`detect_unreflected_gap` 게이트를 이 클래스에 한해 우회하되, 다른 공시
  유형의 기존 반영-갭 경로는 불변 (spec.md [X-3]).
- 신규 발화 경로는 `execute_signal_trade`를 호출하지 않음 (REQ-005).

### M2 (P0) — recall 지표 편입 + 지평 분리 (surge_evaluation_service.py)
- T-1 종가 이후 접수분: 기존 T-1→T `predicted_set`에 자연 편입 확인 (REQ-004 첫째).
- 당일(T) 장중 접수분: T-1→T 버킷 배제(SPEC-AI-075 `surge_metadata` 배제 패턴 재사용) +
  별도 same-day 서브지표 산출 (REQ-004 둘째).
- **[v0.2.0]** 즉시 발화 시그널의 `surge_metadata`가 **non-None**이어야 predicted_set에 포함됨
  (surge_evaluation_service.py:554 `surge_metadata.isnot(None)`) + `_is_near_limit_up_carry_signal`
  (:482-503)에 near_limit_up_carry로 오판되지 않아야 함(마커에 near_limit_up_carry 미포함) — 회귀 테스트로 고정.

### M3 (P0/P1) — 기존 업서트/캐리오버 통합 + T-1 귀속 보존 (REQ-006, REQ-004 불변식 — v0.2.0 개정)
- **[P0]** fund_manager.py:1436-1464 재탐지 업서트와 :1542-1597 캐리오버가 즉시 발화 행(surge_metadata
  마커)의 `created_at`·마커를 덮어쓰지 않도록 마커 인지형 스킵 추가(DP-1 (i)). 마커 미검출 시 기존 거동 완전 불변.
- **[P0]** 재현 테스트: "즉시 발화(created_at=T-1) → 익일 배치 재탐지/캐리오버 실행 → created_at이 T-1로
  보존, 18:30 평가 시 T-1 버킷에 유지" 실패→통과 (Scenario 7).
- **[P1]** 동일 (종목,영업일) 중복 INSERT 미발생 확인(기존 업서트 조회 키에 신규 경로 정합).

### M4 (P0) — config + 무회귀
- `surge_detection.yaml` 신규 키 추가 및 로드 확인.
- 전체 회귀: `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"`.
  - **CI xdist 주의**: 과거 `surge_detection.auto.yaml` 워커 공유 레이스 이력 → `-n 4`로도 확인.
- `cd backend && uv run ruff check . && uv run mypy app/`.

### M5 (P2, optional) — 관측성 (REQ-007)
- 즉시 발화 신호량/구성(이벤트 클래스별, T-1편입 vs 당일서브지표) 집계 로그/서브지표.
- 신규 테이블/컬럼/마이그레이션 없음. 미채택도 유효(001~006으로 완결).

## Development Methodology

- 프로젝트 quality.yaml 모드에 따름(기존 코드 대상 → DDD ANALYZE-PRESERVE-IMPROVE 적합).
- **Reproduction-First(CLAUDE.md Rule 4)**: recall 편입은 관찰 가능한 사실로 재현 테스트 선작성 —
  "T-1 종가 이후 접수 고확신 공시 → 즉시 발화 시그널이 T-1 predicted_set에 포함"을 재현하는
  실패→통과 테스트. 당일 접수분은 "T-1 버킷 배제 + 서브지표 집계"를 검증.
- **PRESERVE**: `detect_unreflected_gap`의 저반응 용도, 다른 공시 유형의 반영-갭 시그널,
  SPEC-AI-018 배치 bypass, SPEC-AI-043 매매 비활성에 대한 characterization으로 무회귀 보호.

## Post-Implementation Review (잠재 이슈)

- 활성화 후 첫날부터 surge_candidate 수 증가 예상 → precision 관찰(R-1). 며칠간 로그/서브지표 추적.
- auto-improver가 recall 상승을 감지해 min_score를 낮추는 연쇄 가능성 → 범위 밖이나 활성화 후
  auto-improver 로그 모니터링 권장.
- Rollback: `surge_detection.yaml`의 `immediate_surge.enabled`를 false로 되돌리면 즉시 발화 경로
  전체 비활성(기존 이벤트 구동/배치 경로는 불변 유지) — 설정 게이트로 완전 되돌림 보장하도록 설계.
- 타임존 경계(R-5/OQ-1)와 이중집계(R-2/REQ-006)는 배포 후 recall 수치의 급격한 이상 변화로
  조기 감지 가능 — 첫 며칠 수치 모니터링을 DoD에 포함.
- **[v0.2.0/R-6]** created_at 덮어쓰기 보호가 실제로 작동하는지 배포 후 검증 — 즉시 발화 종목의
  T-1 recall 귀속이 익일 배치(10:00/15:20) 실행 이후에도 유지되는지 로그·DB로 확인. 마커 인지형 스킵이
  기존 시그널(마커 없음)의 created_at 갱신 거동을 바꾸지 않는지(carry-over/재탐지 정상 동작) 무회귀 확인.
