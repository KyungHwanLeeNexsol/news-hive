---
id: SPEC-AI-117
title: "급등예측 파이프라인 신뢰성(Tier 0) — 구현 계획"
version: "0.1.0"
status: in-progress
created: 2026-08-21
updated: 2026-08-21
author: Nexsol
priority: High
phase: "backend surge-detection v0.1.0"
module: "backend/app/services"
lifecycle: spec-anchored
tags: "surge-detection, reliability, gather-timeout, gate-drop-observation, volume-breakout, missing-evaluation-monitor, backend"
tier: M
related_specs: [SPEC-AI-082, SPEC-AI-096, SPEC-AI-063, SPEC-AI-074, SPEC-AI-092, SPEC-AI-109, SPEC-AI-115]
---

# SPEC-AI-117 plan.md

## §A. Context

- 작업 위치: `backend/` (프로젝트 루트: `C:\Users\Nexsol\Documents\news-hive`)
- 브랜치: `main` (Route A — Hybrid Trunk main-direct, Tier M이므로 직접 커밋+push)
- SPEC 산출물: `.moai/specs/SPEC-AI-117/{spec,plan,acceptance,progress}.md`
- 서버 배포 대상: OCI VM `140.245.76.242:8000`(bare metal, systemd 서비스명 `newshive`),
  SSH: `.codex-tmp/news-hive-key.key`(project memory 참고)
- 기존 인프라(PRESERVE, 재사용 대상):
  - `surge_gate_drop_observations` 테이블 + `on_drop` 콜백(SPEC-AI-115)
  - `surge_missing_evaluation_check` 스케줄러 잡 + `repair_missing_surge_evaluation()`
    (SPEC-AI-092/109)
  - `send_telegram_message` + `TELEGRAM_ADMIN_CHAT_ID` fail-open 패턴

## §B. Known Issues (관련 카테고리만 발췌)

- **B9 (Git 직접 커밋+push)**: Tier M, Route A — manager-develop이 각 마일스톤마다
  직접 커밋한다. `feat`/`fix(SPEC-AI-117): M{N} ...` 형식.
- **B10 (Scope Discipline)**: `fund_manager.py`의 diff는 **이미 작성된 내용을 그대로
  커밋**하는 것이 M1의 전부다 — 다른 부분을 손대지 않는다. `_apply_price_fetch_truncation()`
  변경(M3, 조건부)도 면제 조건 한 줄만 확장하며 주변 로직을 리팩터링하지 않는다.
- **B11 (AskUserQuestion 금지)**: REQ-AI117-002/005 진단 결과가 애매하거나(예: 서버
  접근 실패, journalctl 로그가 이미 로테이션되어 사라짐) 조건부 REQ 시행 여부를
  판단할 수 없는 경우, manager-develop은 구조화된 blocker 리포트를 반환한다 — 임의로
  "확인됐다고 가정"하고 진행하지 않는다.
- **B12 (CHANGELOG, manager-docs 전용)**: sync-phase에서 REQ-AI117-002/005의 진단
  **원본 결과**(쿼리 결과 행 수, 로그 라인 발췌)를 CHANGELOG에 그대로 인용한다 — 요약이나
  해석으로 대체하지 않는다.

## §C. Pre-flight

```bash
# 1. 현재 브랜치 + baseline
git branch --show-current
git rev-parse HEAD

# 2. Item 1 diff가 이 세션 확인 상태 그대로인지 재확인
git diff HEAD -- backend/app/services/fund_manager.py

# 3. 관련 설정 현재값 재확인 (레포 기준)
grep -n "gate_drop_observation_enabled\|max_scan_universe\|volume_breakout_bypass_threshold" \
  backend/app/surge_config/surge_detection.yaml

# 4. 전체 테스트 baseline (pre-existing 실패와 NEW 실패 구분용)
cd backend && uv run pytest tests/ --tb=short -q -m "not slow" 2>&1 | tail -20
```

## §D. Constraints (DO NOT VIOLATE)

- M1(diff 배포)에서 `fund_manager.py`의 diff 내용을 재작성하지 않는다 — 주석 문구,
  타임아웃 값, 로깅 위치 모두 이 세션이 `git diff`로 캡처한 그대로 커밋한다.
- M3(조건부 절단 면제 확장)은 REQ-AI117-002 진단이 `price_fetch_truncation` 드롭을
  실제로 확인한 경우에만 시행한다 — 진단 없이 코드를 먼저 바꾸지 않는다.
- M4(조건부 Pool B 경보)도 동일하게 진단 확인 후에만 시행한다.
- 7개 핵심 탐지기 판정 로직, 앙상블 가중치, `existing_codes` 필터(SPEC-AI-094), Pool
  A/B/C/D 소싱 쿼리 조건 자체는 어떤 마일스톤에서도 변경하지 않는다.
- `--no-verify` 금지. force-push 금지.
- 서버 배포(M1, M5 진단)는 기존 CI/CD(main push 자동 배포) 경로를 사용한다 — 수동
  `scripts/deploy.sh` 개입은 CI/CD 실패 시에만.
- 배포 Guard(15:15~16:10 KST 자동 대기, project memory) 시간대를 M1 배포 전 확인한다.

## §E. Self-Verification Deliverables (개요 — 상세는 acceptance.md)

- E1: AC PASS/FAIL 매트릭스
- E2: 전체 회귀 테스트 결과(`uv run pytest tests/ -m "not slow"`)
- E3: REQ-AI117-002/005 진단 원본 결과(쿼리 SQL + 결과, journalctl 발췌)
- E4: M1 배포 후 서버 재시작 확인(`journalctl -u newshive -n 50`)
- E5: 조건부 REQ(003/004) 시행 여부 및 그 판단 근거

## §F. Milestones

우선순위 순서(마일스톤 간 의존성 최소화, 독립적으로 배포 가능한 M1을 최우선, 조건부
분기를 결정하는 진단 마일스톤을 그 다음, 조건부 코드 변경은 진단 이후로 배치):

- **M1 — gather-timeout diff 배포 (REQ-AI117-001)**: 독립적, 이미 검토완료, 최소위험.
  `git diff`가 이 세션 캡처와 동일한지 재확인 후 커밋+push. 서버 배포 확인.
- **M2 — Item 2 진단 (REQ-AI117-002)**: `gate_drop_observation_enabled` 서버 실측값
  확인 → `surge_gate_drop_observations` 조회(2026-08-20, 049470/462860). 결과를
  M3/M4의 조건부 게이트로 사용.
- **M3 — 조건부: 절단 면제 확장 (REQ-AI117-003)**: M2가 드롭을 확인한 경우에만 시행.
  `_apply_price_fetch_truncation()` 면제 조건에 OR 절 추가 + characterization 테스트.
- **M4 — 조건부: Pool B 실패 경보 승격 (REQ-AI117-004)**: M2/로그 조회가 Pool B 실패를
  확인한 경우에만 시행.
- **M5 — Item 3 서버측 진단 (REQ-AI117-005)**: journalctl 조회(19:15 잡 실행 여부 +
  11:26 재시작 근본원인). 결과에 따라 후속 REQ 필요 여부만 판단(이 SPEC 범위 내
  추가 REQ로 확장할지는 진단 후 결정 — 강제하지 않음).
- **M6 — 무회귀 검증 + CHANGELOG (REQ-AI117-006)**: 전체 테스트, 진단 원본 결과를
  CHANGELOG에 인용, sync-phase 준비.

## §G. Anti-Patterns (이 SPEC에 특화)

- M3/M4를 M2 진단 없이(또는 진단이 "드롭 미확인"으로 나왔음에도) 시행하는 것 —
  `verification-claim-integrity.md`가 금지하는 무근거 결함 주장에 해당한다.
- M2/M5 진단 결과를 요약·해석해서 spec.md/CHANGELOG에 기록하는 것 — 원본 쿼리 결과와
  로그 발췌를 그대로 인용해야 한다(Evidence 섹션 원칙).
- M1 diff를 "더 안전하게" 재작성하는 것 — 이미 검토된 diff를 그대로 배포하는 것이
  이 마일스톤의 전부다.

## §H. Cross-References

- `.claude/rules/moai/core/verification-claim-integrity.md` — 진단 우선/조건부 REQ
  설계의 근거 원칙.
- `~/.claude/projects/{hash}/memory/project_surge_2026_08_11_monitor_vs_fix_decision.md` —
  2026-08-24까지 알고리즘 튜닝 보류 결정(Open Questions 항목 2와 연결).
