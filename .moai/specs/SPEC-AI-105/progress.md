# SPEC-AI-105 Progress

## §E.1 Plan-phase Audit-Ready Signal

plan_status: audit-ready
plan_complete_at: 2026-08-06

Plan-phase artifacts (spec.md, plan.md, acceptance.md, progress.md) created.
Tier: M. 4 REQs deferred/documented-only (no live flag flip of the bridge master
switch); 1 new config flag (`scan_universe_bridge_shadow_enabled`) proposed to flip
from `false` to `true` as this SPEC's own deploy artifact (measurement-only, proven
zero production-behavior impact per REQ-AI105-006).

## §E.2 Run-phase Evidence

cycle_type=ddd (ANALYZE-PRESERVE-IMPROVE). Single-commit implementation (no
formal M1-M6 milestone split — plan.md §B TASK-001~006 executed sequentially
in one pass). alembic head confirmed `074_surge_horizon_shadow_observation`
before run-phase start (per plan.md TASK-001 mandatory pre-check), advanced to
`075_surge_bridge_shadow_candidate` after.

| AC ID | Status | Verification Command | Actual Output |
|-------|--------|----------------------|----------------|
| AC-105-001 | PASS | `pytest tests/test_spec_ai_105.py::TestPersistBridgeShadowCandidates::test_replace_semantics_second_call_replaces_first -q` | PASS — 두 번째 호출 결과만 잔존 확인 |
| AC-105-002 | PASS | `pytest tests/test_spec_ai_105.py::TestSurgeBridgeShadowCandidateSchema::test_composite_pk_and_column_types -q` | PASS — PK={trading_date,stock_code}, entry_pool/bridge_score not null |
| AC-105-003 | PASS | `pytest tests/test_spec_ai_105.py::TestShadowWiringNoRegression -q` | PASS — spy call_count: shadow OFF=1, shadow ON=2 (동일 함수 참조 재사용 확인) |
| AC-105-004 | PASS | 동일 테스트(위) | PASS — qualified 코드 집합 shadow ON/OFF 바이트 동등 + 실행 후 config.scan_universe_bridge_candidates_enabled == False 재확인 |
| AC-105-005 | PASS | `pytest tests/test_spec_ai_105.py::TestAnalyzeBridgeShadowPrecisionByDate::test_pool_a_pool_c_separated_matches_manual_calc test_spec_ai_105.py::TestAnalyzeBridgeShadowPrecisionByDate::test_key_set_is_exactly_pool_a_pool_c_no_blended -q` | PASS — 키 집합 정확히 {pool_a, pool_c}, 값 수동 산출값과 일치 |
| AC-105-006 | PASS | `pytest tests/test_spec_ai_105.py::TestAnalyzeBridgeShadowPrecisionByDate::test_total_zero_returns_none_precision_no_exception -q` | PASS — total=0 시 precision=None, 예외 없음 |
| AC-105-007 | PASS | `pytest tests/test_spec_ai_105.py::TestReportBridgeShadowSection -q` | PASS — "## Bridge Shadow 정밀도" 섹션에 pool_a/pool_c 분리 행 렌더링 확인 |
| AC-105-008 | PASS | `pytest tests/test_spec_ai_105.py::TestPoolBHardcodedExclusion -q` | PASS — pool_b_enabled=True 픽스처에서도 shadow 결과에 pool_b 부재 + fetch_stock_price_history_batch_sync 미호출(mock call count 0) |
| AC-105-009 | PASS | `pytest tests/test_spec_ai_092.py tests/test_spec_ai_096.py tests/test_spec_ai_102.py tests/test_spec_ai_104.py -q` | PASS — 76 passed (test_spec_ai_104.py 4개 파일 전량 포함, plan-phase 시점엔 미존재 예상했으나 run-phase 착수 시점 존재 확인되어 회귀 스위트에 포함) |
| AC-105-010 | PASS | `grep -A 25 "^## C\. 활성화 게이트 절차" plan.md \| grep -c "pool_a\|pool_c\|기준선"` + `grep "scan_universe_bridge_shadow" CHANGELOG.md` | PASS — grep count=10 (>=1), CHANGELOG.md에 경고 항목 존재 확인 |

**Preserve-list verification**: `generate_scan_universe_bridge_candidates()` 함수 본체
(surge_detector.py:5766-6012, 실제 라인 넘버는 신규 코드 삽입으로 shift됨) 무수정 —
호출부 wiring 추가만 수행. `_BRIDGE_MIN_SCORE`, pool 점수 산식, quota 배분,
8개 탐지기, `surge_trading_service.py` 전부 무수정 (`git diff --name-only`로 확인,
아래 §E.3 참고).

**Full backend regression suite**: `pytest tests/ --tb=short -q -m "not slow"` →
2426 passed, 4 skipped, 3 xpassed, 0 failed (전체 스위트 무회귀 확인, SPEC-AI-105
범위 밖 파일 전부 포함).

## §E.3 Run-phase Audit-Ready Signal

```yaml
run_complete_at: 2026-08-06
run_commit_sha: 07ad2edee552b893501968642041d62a969fcdcd
run_status: implemented
ac_pass_count: 10
ac_fail_count: 0
preserve_list_post_run_count: 8
l44_pre_commit_fetch: n/a (single-session, no parallel-session race detected)
l44_post_push_fetch: n/a (pending push)
new_warnings_or_lints_introduced: 0 (ruff check . -> "All checks passed!")
cross_platform_build:
  status: n/a (Python project, no GOOS/GOARCH cross-compile applicable)
total_run_phase_files: 8
m1_to_mN_commit_strategy: single-commit (no formal milestone split; TASK-001~006 executed sequentially in one implementation pass)
```

## §E.4 Sync-phase Audit-Ready Signal

```yaml
sync_complete_at: 2026-08-06
sync_commit_sha: pending-backfill-spec-ai-105-sync
sync_status: completed
changelog_entry_position: "[Unreleased] > Feature — SPEC-AI-105 (verified against implementation files, no edits required)"
readme_update: not-applicable (internal observability/shadow-measurement change, no new user-facing feature/CLI/API surface — consistent with SPEC-AI-104 precedent)
frontmatter_status_transitions:
  spec_md: "in-progress -> implemented -> completed (single sync commit)"
```

CHANGELOG.md `[Unreleased]` entry (added during run-phase) verified against actual
implementation files: `app/models/surge_bridge_shadow_candidate.py`,
`app/services/surge_bridge_shadow_service.py` (`persist_bridge_shadow_candidates()`),
`alembic/versions/075_surge_bridge_shadow_candidate.py`, `surge_detector.py:2707-2733`
wiring block, `surge_settings.py:733` (`scan_universe_bridge_shadow_enabled: bool = False`),
`surge_detection.yaml:318` (`scan_universe_bridge_shadow_enabled: true`),
`surge_universe_gap_service.py:253` (`analyze_bridge_shadow_precision_by_date()`).
All claims accurate — no CHANGELOG edit required. `grep -c "SPEC-AI-105" CHANGELOG.md`
returned 1 (single entry, no duplication) before this sync commit.

## §F Phase 4 Mode Selection

**Input parameters**: tier=M, scope=6 files (new model file, new alembic revision, new/extended service file, surge_settings.py, surge_detection.yaml, surge_detector.py wiring point, measure_universe_detection_gap_report.py, new test_spec_ai_105.py), domain count=1 (backend Python, single service area with a new migration), concurrency benefit=LOW (coding-heavy sequential DDD, migration-order-sensitive).

**Decision: sub-agent** (Mode 5) — same rationale as SPEC-AI-104: coding-heavy, sequential, single-domain, no parallelism opportunity (TASK-001's schema gates TASK-002/003).

**Plan Audit Gate skip decision**: SKIPPED Phase 1 re-execution. Verdict PASS (iteration 1, score 0.92, `.moai/reports/plan-audit/SPEC-AI-105-review-1.md`), score ≥ 0.90, artifact-hash unchanged since that verdict, within 24h (same session, 2026-08-06).
