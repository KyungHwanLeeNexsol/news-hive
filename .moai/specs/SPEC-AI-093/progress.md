# SPEC-AI-093 Progress

## §E.1 Plan-phase Audit-Ready Signal

- plan_status: audit-ready
- plan_complete_at: 2026-07-30
- plan-auditor iteration 1: PASS, score 0.90 (`.moai/reports/plan-audit/SPEC-AI-093-review-1.md`)
- plan-auditor iteration 2 (re-audit after minor doc fixes, artifact hash changed post-verdict-1): PASS, score 0.96 (`.moai/reports/plan-audit/SPEC-AI-093-review-2.md`)
- Implementation Kickoff Approval: 사용자 승인 완료 (2026-07-30, AskUserQuestion "구현 착수 (/moai run SPEC-AI-093)")

## §F Phase 4 Mode Selection

**Input parameters**:
- tier: M
- scope (file count): 2 (backend/app/services/surge_actual_outcome_service.py 수정, backend/tests/test_surge_actual_outcome_service.py 확장)
- domain count: 1 (backend service layer, 단일 서비스)
- file language mix: 100% Python
- concurrency benefit: LOW (DDD ANALYZE-PRESERVE-IMPROVE 순차 사이클, coding-heavy)

**Mode evaluation**:

| Mode | Selected? | Rationale |
|------|-----------|-----------|
| 1 trivial | No | 실측 로직 추가 + fallback 분기 + 로깅 — 단순 오타/포맷 수정 아님 |
| 2 background | No | Write 작업이며 결과를 바로 검증해야 함 |
| 3 agent-team | No | RETIRED |
| 4 parallel | No | coding-heavy 단일 도메인 — Anthropic coding-task parallelism caveat |
| 5 sub-agent | **Yes** | 단일 서비스, 순차 DDD 사이클에 적합 (Anthropic coding-task 기본값) |
| 6 workflow | No | 파일 수 2개, 기계적 반복 변환 아님 (≥30파일 기준 미충족) |

**Decision: sub-agent**

**Justification**: SPEC-AI-093은 단일 백엔드 서비스(`surge_actual_outcome_service.py`)에 국한된 Tier M 변경으로, 병렬화로 얻을 이득이 없는 coding-heavy 작업이다. quality.yaml의 `development_mode: ddd` 설정에 따라 manager-develop을 cycle_type=ddd로 순차 위임한다.

Implementation Kickoff Approval 통과 확인 + 사용자 선호(전체 수집) 완료 반영됨.

## §E.2 Run-phase Evidence

Route A (Hybrid Trunk main-direct, Tier M) — manager-develop cycle_type=ddd.

### 변경 파일 (2개, PRESERVE 범위 준수)

| 파일 | 성격 |
|------|------|
| `backend/app/services/surge_actual_outcome_service.py` | EXTEND — 고가 실측 수집 + fallback 로깅 + 파생 지표 |
| `backend/tests/test_surge_actual_outcome_service.py` | EXTEND — 기존 14개 단언 무수정, mock 범위만 확장 + 신규 18개 |

`was_surge` 소비자 5개 파일(`surge_evaluation_service.py` / `surge_universe_gap_service.py` /
`surge_auto_improver.py` / `surge_detector.py` / `scheduler.py`)과 `naver_finance.py`의
`fetch_current_price_with_change` 경로는 무수정이다(REQ-AI093-004, D1).

### TASK 이행

- TASK-001: `compute_high_change_rate()` 순수 함수 — `date` 매칭으로 T/T-1 특정(인덱스 접근 금지)
- TASK-002: `collect_daily_surge_outcomes`에 동일 세마포어(`_PRICE_CONCURRENCY`) 기반 일봉 조회 배선
- TASK-003: 5개 사유 코드 개별 DEBUG 로깅 + 배치 요약 INFO 1건 (카운터는 함수 지역 상태 — xdist 레이스 회피)
- TASK-004: `evaluate_high_based_outcomes()` — `COALESCE(high_change_rate, change_rate) >= 10.0` 파생 판정 + coverage guard
- TASK-005: 조회시도 / 캐시적중 / 외부호출(추정) 계측 로그 1건
- TASK-006: 기존 14개 테스트 무회귀 + `was_surge` 소비자 회귀 스위트 통과

### 구현 시 확정한 Open Question

| # | 확정값 | 근거 |
|---|--------|------|
| 1 | coverage 임계값 기본 `0.90` (`SURGE_HIGH_COVERAGE_THRESHOLD`로 오버라이드) | spec.md §Open Questions 1 제안값 채택 |
| 2 | 노출 표면 = 서비스 계층 함수 `evaluate_high_based_outcomes()` | `/prediction-history` API 확장은 PRESERVE 범위 밖 파일을 건드리므로 후속 SPEC |
| 3 | `pages=3` (`SURGE_HIGH_HISTORY_PAGES`로 오버라이드) | 아래 근거 참조 |

`pages=3` 근거 — `_price_cache`는 `stock_code`만으로 키를 잡으므로 `pages=1`(약 10거래일)로
조회하면 짧은 일봉 리스트가 공유 캐시에 기록되어 20거래일 이상을 요구하는 탐지기 계산을
굶길 수 있다. 코드베이스에서 이미 안전선으로 쓰이는 `fetch_stock_price_history_sync` 기본값
(`pages=3`, 약 30거래일)에 맞췄다. 연휴 직후 T-1 포함도 함께 보장된다.

## §E.3 Run-phase Audit-Ready Signal

- run_status: audit-ready
- run_complete_at: 2026-07-30
- 타깃 테스트: `tests/test_surge_actual_outcome_service.py` 32 passed (기존 14 + 신규 18)
- 소비자 회귀: `test_surge_evaluation_service.py` + `test_spec_ai_090.py` + `test_spec_ai_089.py` 86 passed
- 전체 회귀: `pytest tests/ -q -m "not slow"` → 2244 passed, 4 skipped, 3 xpassed
- xdist 레이스 확인: `-n 4` 81 passed
- 정적 검사: `ruff check` 통과 / `mypy` 미검증 (환경에 mypy 미설치 — Gap)
- run_commit_sha: pending-backfill-run
