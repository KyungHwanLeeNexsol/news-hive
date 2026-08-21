---
id: SPEC-AI-117
title: "급등예측 파이프라인 신뢰성(Tier 0) — 진행 상황"
version: "0.1.0"
status: in-progress
created: 2026-08-21
updated: 2026-08-21
author: Nexsol
priority: High
phase: "backend surge-detection v0.1.0"
module: "backend/app/services"
lifecycle: spec-anchored
tags: "surge-detection, reliability, backend"
tier: M
related_specs: [SPEC-AI-082, SPEC-AI-096, SPEC-AI-063, SPEC-AI-074, SPEC-AI-092, SPEC-AI-109, SPEC-AI-115]
---

# SPEC-AI-117 progress.md

## §E.1 Plan-phase Audit-Ready Signal

plan_status: audit-ready
plan_complete_at: 2026-08-21

_plan-phase 산출물(spec.md/plan.md/acceptance.md/progress.md) 작성 완료. plan-auditor
검토 대기 중._

## §E.2 Run-phase Evidence

### M1 — gather-timeout diff 배포 (REQ-AI117-001 / AC-AI117-001)

- 커밋: `73f94e5` `fix(SPEC-AI-117): M1 gather-timeout 40분 완화 배포`
- diff 내용: `_GATHER_TIMEOUT_S` 1200→2400 + 성공/타임아웃/예외 3개 경로
  `time.monotonic()` 소요시간 로깅. 세션이 `git diff HEAD`로 확인한 그대로
  재작성 없이 커밋(REQ-AI117-001 필수 조건 충족).
- 부수 수정: `tests/test_surge_ai083_intraday_rescan.py::TestCommonInvariants::test_gather_timeout_constant_unchanged`
  불변성 가드를 1200→2400으로 갱신(SPEC-AI-082→SPEC-AI-117 값 소유권 이전
  명시). 이 갱신 없이는 REQ-AI117-006 전체 회귀가 실패한다.
- Push: `git push origin main` 결과는 §E.3에 기록(배포 확인은 커밋 직후
  진행 예정).

- Push: `git push origin main` → `70e56db..ec015d6 main -> main` (커밋
  `73f94e5`, `ec015d6` 모두 반영).
- CI/CD 자동배포(`.github/workflows/ci.yml` deploy job, backend 경로 변경 →
  backend-test + backend-lint 통과 후 `scripts/deploy.sh` 실행) 확인:
  - 서버 `git log -1 --format='%h'` → `ec015d6` (2026-08-21 02:44:22 UTC 확인,
    push 후 자동 배포 완료).
  - 서버 파일 `grep -n '_GATHER_TIMEOUT_S' app/services/fund_manager.py` →
    `66:_GATHER_TIMEOUT_S: float = 2400  # 40분 (...)` — 값 로드 확인.
  - `systemctl show newshive -p ActiveState -p SubState -p
    ExecMainStartTimestamp -p NRestarts` → `NRestarts=0`,
    `ExecMainStartTimestamp=Fri 2026-08-21 02:46:04 UTC`, `ActiveState=active`,
    `SubState=running` — 크래시루프 없이 단일 재기동 확인.

| AC | Status | Verification Command | Actual Output |
|----|--------|----------------------|----------------|
| AC-AI117-001 | PASS | `git log -1 --format='%h'` (서버) + `grep _GATHER_TIMEOUT_S` (서버) + `systemctl show newshive` | 서버 `ec015d6`, `_GATHER_TIMEOUT_S=2400`, `NRestarts=0`/`active`/`running` |

### M2 — Item 2 진단 (REQ-AI117-002 / AC-AI117-002a/002b)

**AC-AI117-002a — gate_drop_observation_enabled 서버 실측값 확인**

- 정적 파일 확인: 서버 `app/surge_config/surge_detection.yaml:321` → `gate_drop_observation_enabled: true`.
- 서버 `app/surge_config/surge_detection.auto.yaml`(자동개선 루프 전용,
  레포 미포함) 원본:
  ```
  # surge_detection.auto.yaml — SPEC-AI-069 REQ-002 리셋 완료 (auto_improve_enabled=false)
  # base surge_detection.yaml이 유일 authoritative 소스. 특정 키 오버라이드 없음.
  ```
  → `gate_drop_observation_enabled` 키 오버라이드 없음(drift 없음).
- 앱의 실제 `get_surge_config()` 로더로 실측(서버 `venv/bin/python`,
  `app.surge_config.surge_settings.get_surge_config()`):
  ```
  gate_drop_observation_enabled = True
  ```
- **결론: `true`로 확인됨. 정합화(재조정) 불필요 — REQ-AI117-002 필수 조건의
  "false 확인 시 정합화" 하위 조건은 발동하지 않는다.**

**AC-AI117-002b — surge_gate_drop_observations 원본 조회**

쿼리: `trading_date='2026-08-20' AND stock_code IN ('049470','462860')`
(서버 DB, `SurgeGateDropObservation` ORM 직접 조회, 서버 `venv/bin/python`)

- 참고: 2026-08-20 전체 `gate_drop_observations` 행 수 26,353건(계측
  자체는 활발히 동작 중). 그날 관측된 distinct `gate_name`: `below_regime_threshold`,
  `sector_contagion_gate`, `evaluation_excluded_near_limit_carry`,
  `evaluation_excluded_same_day`, `price_fetch_truncation`,
  `strong_bypass_failed`, `immediate_bypass_failed`.

| stock_code | 결과 | gate_name | score_before_drop | market_regime | detector_set_json | reason_metadata_json |
|---|---|---|---|---|---|---|
| 462860 (더즌) | **있음(1건)** | `price_fetch_truncation` | 0.095 | BEAR | `["theme_cluster"]` | `{"entry_pool": "existing", "max_price_fetch_candidates": 50, "original_count": 1416, "pool_member_exempt_count": 116, "pre_truncation_rank": 859}` |
| 049470 (비트플래닛) | **없음(0건)** | — | — | — | — | — |

- 049470 추가 확인: `stock_code LIKE '%049470%'`로 **전체 기간** 조회 —
  0건(포맷 불일치 가능성 배제, 이 종목은 이 테이블에 단 한 번도 기록된 적이
  없다).
- **462860 해석(원본 사실만, 가공 없음)**: `pre_truncation_rank=859`가
  `max_price_fetch_candidates=50`를 크게 초과 — 이 세션의 spec.md §Context
  Item 2 가설(가격조회 사전절단이 `entry_pool="existing"`인 순수 신호
  부족 후보를 bypass 게이트 도달 전에 제거한다)과 정확히 일치하는 드롭
  기록이 확인됐다. `original_count=1416`은 그날 `merged` 크기가
  `_MAX_PRICE_FETCH_CANDIDATES`(50)를 28배 초과했음을 의미한다.
- **049470 해석(원본 사실만)**: instrumented 게이트(위 7개) 중 어느 것으로도
  드롭이 기록되지 않았다 — 이는 (a) 애초에 `merged`에 진입하지 못했거나
  (`build_scan_universe()`/`detect_volume_breakout()` 자체 유니버스에서
  발견되지 않음), (b) instrumented되지 않은 다른 경로(예: `_pre_score`
  가중합 계산 이전 단계, 또는 콜백이 없는 게이트)에서 사라졌을 가능성을
  시사한다. 이 세션은 그 이상의 근본원인을 추가로 규명하지 않는다(REQ-AI117-002
  범위 밖 — spec.md §Non-Goals "알고리즘/임계값 튜닝" 경계 유지).

**REQ-AI117-003 게이트 판정**: AC-AI117-002b가 `gate_name='price_fetch_truncation'`
드롭을 1건(462860) 확인 → **분기 A, REQ-AI117-003 시행**(acceptance.md
시나리오 2).

### M3 — 조건부: 절단 면제 확장 (REQ-AI117-003 / AC-AI117-003)

M2 진단(462860 `price_fetch_truncation` 드롭 1건 확인)이 REQ-AI117-003
시행 조건을 충족해 시행했다.

- 변경 파일: `app/services/surge_detector.py`
  - `_apply_price_fetch_truncation()`에 키워드 전용 파라미터
    `volume_breakout_bypass_threshold: float | None = None` 추가(기본값
    `None`이면 신규 조건이 비활성화되어 SPEC-AI-096 기존 동작과 완전히
    동일 — 무회귀).
  - 면제 조건: `entry_pool != "existing" OR (volume_breakout_bypass_threshold
    is not None AND candidate.volume_breakout_score >=
    volume_breakout_bypass_threshold)`.
  - 호출부(`gather_surge_candidates()`)에서
    `volume_breakout_bypass_threshold=config.volume_breakout.volume_breakout_bypass_threshold`
    (SPEC-AI-063 기존 값 재사용, 새 임계값 도입 없음) 전달.
  - `_MAX_PRICE_FETCH_CANDIDATES`(50) 숫자, `_pre_score()` 가중합 산출식,
    `_POOL_MEMBER_WARNING_THRESHOLD`(200) 경고 로직, pool_a/b/c/d 소속
    면제 로직(SPEC-AI-096) 자체는 무변경(REQ-AI117-003 필수 조건 전항목
    충족).
- 신규 테스트: `tests/test_spec_ai_117.py`
  `TestPriceFetchTruncationVolumeBreakoutBypassExemption` 4건 — M2 실측치
  (462860, volume_breakout_score=0.50, bypass_threshold=0.30) 그대로 사용해
  (a) 미지정 시 절단(무회귀 기준선), (b) 임계값 충족 시 생존, (c) 임계값
  미달 시 여전히 절단, (d) pool 소속 면제 로직 무변경을 각각 검증.

| AC | Status | Verification Command | Actual Output |
|----|--------|----------------------|----------------|
| AC-AI117-003 | PASS | `uv run pytest tests/test_spec_ai_117.py tests/test_spec_ai_096.py tests/test_spec_ai_115.py -v` | 28 passed |

## §E.3 Run-phase Audit-Ready Signal

M1(REQ-AI117-001) 완료·배포 검증 완료. M2(REQ-AI117-002) 진단 완료 —
`gate_drop_observation_enabled=true`(drift 없음), 462860 드롭 1건 확인/
049470 드롭 0건. M3(REQ-AI117-003) 시행 완료 — 절단 면제 확장 +
characterization 테스트 4건 PASS, 전체 회귀 2534 passed/0 failed
(`cd backend && uv run pytest tests/ -m "not slow"`), ruff clean. M4로 진행.

## §E.4 Sync-phase Audit-Ready Signal

_<pending sync-phase>_
