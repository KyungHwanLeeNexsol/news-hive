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

## §E.3 Run-phase Audit-Ready Signal

M1(REQ-AI117-001) 완료. M2(REQ-AI117-002) 진단으로 진행.

## §E.4 Sync-phase Audit-Ready Signal

_<pending sync-phase>_
