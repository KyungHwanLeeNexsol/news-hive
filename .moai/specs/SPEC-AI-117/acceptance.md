---
id: SPEC-AI-117
title: "급등예측 파이프라인 신뢰성(Tier 0) — 인수 기준"
version: "0.1.0"
status: completed
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

# SPEC-AI-117 acceptance.md

## §A. AC Matrix

| AC | REQ | GEARS 문장 | 조건부 여부 |
|----|-----|------|------------|
| AC-AI117-001 | REQ-AI117-001 | **When** manager-develop가 `fund_manager.py`의 gather-timeout 완화 diff를 재작성 없이 커밋하고 main에 push하면, the system **shall** 새 커밋으로 재배포되어 `_GATHER_TIMEOUT_S`가 `2400`으로 로드됨을 `journalctl -u newshive` 또는 관리자 API로 확인 가능하게 해야 한다. | 필수 |
| AC-AI117-002a | REQ-AI117-002 | **When** REQ-AI117-002 진단이 시작되면, the system **shall** 프로덕션 서버에서 `SurgeDetectionConfig.gate_drop_observation_enabled`의 실제 로드값을 직접 확인해야 한다. | 필수(진단) |
| AC-AI117-002b | REQ-AI117-002 | **Where** `gate_drop_observation_enabled`가 서버에서 `true`로 확인되면, the system **shall** `surge_gate_drop_observations` 테이블에서 `trading_date='2026-08-20' AND stock_code IN ('049470','462860')` 조건으로 조회한 원본 결과(있음/없음)를 plan.md/CHANGELOG에 가공 없이 기록해야 한다. | 필수(진단) |
| AC-AI117-003 | REQ-AI117-003 | **Where** AC-AI117-002b의 조회 결과가 `gate_name='price_fetch_truncation'` 드롭 기록을 1건 이상 확인하면, the system **shall** `_apply_price_fetch_truncation()`의 절단 면제 조건을 `entry_pool != "existing" OR candidate.volume_breakout_score >= volume_breakout_bypass_threshold`로 확장하고, 면제 없이는 절단되던 케이스가 새 조건 추가 후에는 생존함을 검증하는 characterization 테스트를 추가해야 한다. | 조건부(AC-002b가 드롭 확인 시) |
| AC-AI117-004 | REQ-AI117-004 | **Where** `"[스캔유니버스] Pool B 조회 실패"` 경고가 2026-08-20(또는 근접 거래일)에 실제로 관측됨이 확인되면, the system **shall** 해당 실패를 WARNING 로그에서 텔레그램 관리자 채널 경보로 승격해야 한다. | 조건부(Pool B 실패 관측 시) |
| AC-AI117-005 | REQ-AI117-005 | **When** run-phase가 서버 접근 가능한 컨텍스트에서 시작되면, the system **shall** 서버 journalctl에서 2026-08-19 19:15 KST(±15분) 구간의 `surge_missing_evaluation_check` 잡 실행 로그와 11:26 전후 프로세스 재시작의 근본원인 로그를 조회하여, 그 원본 발췌를 spec.md/plan.md에 가공 없이 기록해야 한다. | 필수(진단) |
| AC-AI117-006 | REQ-AI117-006 | **While** 본 SPEC이 적용되는 동안, the system **shall not** 급등 탐지 7개 핵심 탐지기의 판정 로직·앙상블 가중치·quota 배분·`existing_codes` 필터·Pool A/B/C/D 소싱 쿼리 조건을 변경해서는 안 되며, the system **shall** `cd backend && uv run pytest tests/ -m "not slow"` 전체 회귀를 통과해야 한다. | 필수 |

## §B. Given-When-Then 시나리오

### 시나리오 1 — Item 1 배포 (AC-AI117-001)

- **Given** `backend/app/services/fund_manager.py`에 `_GATHER_TIMEOUT_S=1200→2400` +
  소요시간 로깅 diff가 미커밋 상태로 존재한다.
- **When** manager-develop이 이 diff를 재작성 없이 커밋하고 main에 push한다.
- **Then** 서버가 새 커밋으로 재배포되고, `_GATHER_TIMEOUT_S` 값이 `2400`으로 로드됨을
  `journalctl -u newshive -n 50` 또는 `/api/surge-trading` 관리자 엔드포인트로 확인할
  수 있다.

### 시나리오 2 — Item 2 진단 게이트 (AC-AI117-002a/b → AC-AI117-003 조건부 분기)

- **Given** `surge_gate_drop_observations` 테이블과 `gate_drop_observation_enabled`
  설정이 존재한다(SPEC-AI-115).
- **When** 서버에서 `gate_drop_observation_enabled` 실측값을 확인하고, `true`이면
  `trading_date='2026-08-20' AND stock_code IN ('049470','462860')`로 조회한다.
- **Then** (분기 A) `gate_name='price_fetch_truncation'` 행이 1건 이상이면
  REQ-AI117-003을 시행하고 characterization 테스트로 "면제 없이는 절단되고, 면제
  조건 추가 후에는 생존"함을 검증한다.
  **Then** (분기 B) 조회 결과가 없거나 설정이 `false`로 확인되면 REQ-AI117-003은
  시행하지 않고, 진단 원본 결과를 spec.md HISTORY/plan.md에 기록한다.

### 시나리오 3 — Item 3 진단 (AC-AI117-005)

- **Given** `surge_missing_evaluation_check` 스케줄러 잡이 평일 19:15 KST에 등록되어
  있다(SPEC-AI-092).
- **When** 서버 journalctl에서 2026-08-19 19:00~19:30 KST 구간과 11:00~12:00 KST
  구간을 각각 조회한다.
- **Then** "잡이 그날 실행됐는가", "실행됐다면 `repair_missing_surge_evaluation()`이
  어느 단계에서 종료됐는가", "11:26 재시작의 근본원인이 무엇인가"에 대한 원본 로그
  발췌가 spec.md/plan.md에 기록된다.

## §C. Edge Cases

1. **서버 접근 불가**: run-phase 컨텍스트가 서버 SSH/DB 접근 도구를 갖지 못한 경우,
   REQ-AI117-002/005는 완료 불가 — 구조화된 blocker 리포트를 반환하고 오케스트레이터가
   AskUserQuestion으로 서버 접근 경로를 확보한 뒤 재위임한다.
2. **journalctl 로그 로테이션**: 2026-08-19 로그가 이미 로테이션되어 사라진 경우,
   REQ-AI117-005는 "재현 불가 — 원본 증거 소실"로 기록하고 재발 방지책(로그 보존 기간
   연장 등)의 필요 여부만 Open Questions로 남긴다.
3. **`gate_drop_observation_enabled`가 false로 확인되고 auto.yaml에 명시적 override가
   있는 경우**: REQ-AI117-002의 "정합화" 하위 조건이 발동 — auto.yaml의 override를
   제거할지 여부는 auto.yaml이 자동개선 루프 소유 파일이므로 그 소유 SPEC(SPEC-AI-041)
   범위를 침범하지 않는 선에서 판단한다(단순 값 정합화이지 auto-improve 로직 변경이
   아님).
4. **REQ-AI117-003 시행 후 `merged` 크기가 `_POOL_MEMBER_WARNING_THRESHOLD`(200)를
   자주 초과하는 경우**: 코드 변경 없이 경고 로그 발생 빈도를 관찰 대상으로 기록한다
   (§Open Questions).

## §D. Closure Gates

- 모든 필수 AC(001, 002a, 002b, 005, 006)가 PASS해야 sync-phase 진입 가능.
- 조건부 AC(003, 004)는 해당 조건이 발동하지 않으면 "N/A — 조건 미충족"으로 기록하고
  PASS로 간주(스킵이 곧 올바른 동작).
- REQ-AI117-006 회귀 통과 없이는 어떤 마일스톤도 완료로 표시하지 않는다.

## §E. Full Regression

```bash
cd backend && uv run pytest tests/ --tb=short -q -m "not slow"
```
