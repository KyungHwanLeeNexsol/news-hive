# SPEC-AI-096 Progress

## §E.1 Plan-phase Audit-Ready Signal

plan_status: audit-ready
plan_complete_at: 2026-08-03
plan_auditor_verdict: PASS (0.95, iteration 1)
plan_auditor_report: inline (session transcript) — no report file persisted this run

## §F Phase 4 Mode Selection

**Input parameters**: tier=M, scope≈6 files (alembic migration + model + service + surge_detector.py + surge_settings.py + surge_detection.yaml, plus CHANGELOG/tests in M5), domain count=1 (backend/Python, single service area), file language mix=100% Python/YAML, concurrency benefit=LOW (sequential milestone dependency — M1 data model precedes M2/M3 per plan.md §A rationale), Agent Teams prereqs=n/a (Mode 3 retired).

**Mode evaluation**:
- trivial: not selected — multi-file, multi-milestone change, not a typo/single-line fix
- background: not selected — write-capable work requiring sequential verification per milestone
- agent-team: not selected — Mode 3 retired
- parallel: not selected — single domain, coding-heavy, milestones have explicit sequential dependency (M1 must land before M2/M3 per plan.md rationale)
- sub-agent: **selected**
- workflow: not selected — scope (~6 files) far below the ~30-file mechanical-transform threshold; this is semantic/new-logic work, not a uniform mechanical transform

**Decision**: sub-agent

**Justification**: Coding-heavy Tier M work with an explicit milestone dependency chain (plan.md §A: M1 data-model change first because it is hardest to reverse, M2 next because it's the highest-risk production-visible change, M3-M5 mechanical/documentation). Per Anthropic's coding-task parallelism caveat, sequential sub-agent is the correct default for coding work; there is no independent-perspective research benefit here that Mode 4 would provide. A single `manager-develop` (cycle_type=ddd) delegation processes M1→M5 in order within one run-phase session.

Implementation Kickoff Approval: confirmed by user via AskUserQuestion (Route A / Hybrid Trunk main-direct selected over --pr) prior to this Mode Selection log entry.

## §E.2 Run-phase Evidence

### AC PASS/FAIL Matrix

| AC ID | Status | Verification Command | Actual Output |
|-------|--------|-----------------------|----------------|
| AC-096-001 | PASS | `pytest tests/test_spec_ai_096.py::TestPoolDCountPersistence -q` | `3 passed` — pool_d_count 저장/조회 왕복, 신규 행 default=0, alembic 070→071 리비전 체인(`ScriptDirectory`) 정적 확인 |
| AC-096-002 | PASS | `pytest tests/test_spec_ai_096.py::TestPoolDKeyBackwardCompat tests/test_surge_universe_pool_bugfix.py::TestPoolCountsPersistenceRoundTrip -q` | `2 passed` + 기존 3개 무수정 통과(단, `test_round_trip`의 정확 dict-equality 단언에 `"pool_d": 0` 항목 추가 필요 — REQ-AI096-002 자체가 요구하는 반환 dict 확장이므로 예상된 변경) |
| AC-096-003 | PASS | `pytest tests/test_spec_ai_096.py::TestMaxScanUniverseDefaultAndClamp -q` | `4 passed` — Pydantic 필드 기본값 250, `get_surge_config()` 로드 결과 250 |
| AC-096-004 | PASS | 위와 동일 + `pytest tests/test_spec_ai_086.py::TestMaxScanUniverseClamp -q` | clamp 250→250 no-op 확인, `TestMaxScanUniverseClamp` 24 tests 무수정 통과(기존 clamp 케이스는 전부 explicit override 사용) |
| AC-096-005 | PASS | `pytest tests/test_spec_ai_096.py::TestPriceFetchTruncationPoolExemption -q` | `1 passed` — 60개(40 pool + 20 existing) 입력 시 절단 없이 60개 전원 생존 |
| AC-096-006 | PASS | `pytest tests/test_spec_ai_096.py::TestPriceFetchTruncationActualCut -q` | `1 passed` — 120개(40 pool + 80 existing) 입력 시 pool 40개 전원 생존 + existing 상위 50개(사전점수 내림차순)만 생존, `len==90` |
| AC-096-007 | PASS | `pytest tests/test_spec_ai_096.py::TestPriceFetchTruncationWarningLog -q` | `2 passed` — pool 소속 201개(>200) 시 경고 로그 발생, 40개(<=200) 시 미발생 |
| AC-096-008 | PASS | `pytest tests/test_spec_ai_096.py::TestPoolDCanaryActivationNoCodeChange tests/test_spec_ai_086.py::TestPoolDQuotaIntegration -q` | `1 passed` (canary=10, 신규) + 기존 3개 무수정 통과(canary=20 케이스 이미 존재) — `if config.pool_d_min_slots > 0:` 게이트 diff 0 (git diff 확인, 해당 라인 무편집 영역) |
| AC-096-009 | PASS | `pytest tests/test_spec_ai_096.py::TestBridgeCanaryActivationNoCodeChange tests/test_spec_ai_092.py::TestBridgeCandidateGeneration -q` | `1 passed` (flag False→True만 변경, 신규) + 기존 4개 무수정 통과. `generate_scan_universe_bridge_candidates` 함수 본문(현재 :5034~) — `git diff` 결과 hunk가 전부 :1830~2200 범위에 국한되어 있어 함수 본문 diff 0 확인 |
| AC-096-010 | PASS | `pytest tests/ -q -m "not slow"` | `2276 passed, 4 skipped, 3 xpassed` (전체 스위트) — cap=150 고정 테스트(`test_spec_ai_065/086/094.py`의 explicit override 케이스, `test_golden_0708_replay_scenario_unchanged_at_fixed_cap_150`) 포함 전부 통과 |

### PRESERVE 목록 무회귀 확인 (plan.md §A.5, 8개 항목)

| # | 대상 | 확인 방법 | 결과 |
|---|------|-----------|------|
| 1 | quota 배분 로직(reserved_b/c/d) | 코드 무편집(diff 없음) | PASS |
| 2 | `_clamp_scan_universe_cap`/`_resolve_scan_universe_cap` | 코드 무편집 + `test_spec_ai_086.py::TestMaxScanUniverseClamp` 24 tests 무수정 통과 | PASS |
| 3 | `pool_d_min_slots`(0)/`scan_universe_bridge_candidates_enabled`(False) 실제 값 | `grep` 확인 — 값 여전히 0/False | PASS |
| 4 | `existing_codes` 병합 필터 | 코드 무편집 | PASS |
| 5 | `generate_scan_universe_bridge_candidates()` 내부 로직 | `git diff` hunk 범위 확인(:5034 함수 밖) | PASS |
| 6 | 7개 핵심 탐지기 | 코드 무편집 | PASS |
| 7 | `_pre_score()` 가중합 산출식 | 함수 위치만 모듈 레벨로 이동(Extract Method), 산출식 리터럴 완전 동일 | PASS |
| 8 | `evaluate_surge_predictions()`의 pool_counts 소비 로직 | 코드 무편집 | PASS |

### 예상된 회귀 테스트 업데이트 (REQ-AI096-001의 직접 결과, 5건)

`max_scan_universe` 기본값 150→250 변경으로 아래 5개 기존 테스트가 "기본값=150" 가정을 명시적으로 단언하고 있어 실패했고, REQ-AI096-001의 의도된 효과이므로 값을 갱신했다(코드 로직은 무편집, assertion 값만 조정):

1. `test_spec_ai_065.py::TestInvariantConstantLiteralsUnchanged::test_max_scan_universe_default_unchanged` → `test_max_scan_universe_default_updated_by_spec_ai_096`(150→250, 리네임 + 독스트링 갱신)
2. `test_spec_ai_086.py::TestGoldenUniverseBaseline::test_golden_order_and_pool_counts_default_config` — assertion만 150→250(후보 수 10 << 두 값 모두라 실제 골든 순서는 무영향)
3. `test_spec_ai_086.py::TestGoldenUniverseBaseline::test_golden_0708_replay_scenario_unchanged_at_default_config` → `..._unchanged_at_fixed_cap_150`(리네임, cap=150 explicit override 추가 — AC-096-010 검증 방법 그대로 적용, 캐릭터라이제이션 가치 보존)
4. `test_spec_ai_086.py::TestDynamicScanUniverseCap::test_dynamic_cap_unset_falls_back_to_flat_cap` — 후보 수 200→300, assertion 150→250
5. `test_spec_ai_086.py::TestDynamicScanUniverseCap::test_dynamic_cap_current_bin_key_absent_falls_back_to_flat_cap` — 후보 수 200→300, assertion 150→250

추가로 `test_surge_universe_pool_bugfix.py::TestPoolCountsPersistenceRoundTrip::test_round_trip`의 정확 dict-equality 단언에 `"pool_d": 0` 항목을 추가(REQ-AI096-002가 요구하는 `get_pool_counts_for_date()` 반환 dict 확장의 직접 결과).

### CHANGELOG.md (REQ-AI096-006) — sync-phase 이관

REQ-AI096-006 원문이 명시적으로 "sync-phase CHANGELOG 항목"이라고 기술하고 있고, manager-develop-prompt-template.md §B12 및 spec-frontmatter-schema.md의 소유권 경계상 CHANGELOG.md는 manager-docs(sync-phase) 전속 소유이므로, 이 SPEC의 run-phase에서는 CHANGELOG.md를 생성/수정하지 않았다(참고로 이 프로젝트에는 현재 CHANGELOG.md 파일 자체가 존재하지 않는다). sync-phase에서 REQ-AI096-006 필수 조건 (a)(b)(c) 3항목을 manager-docs가 작성해야 한다.

## §E.3 Run-phase Audit-Ready Signal

```yaml
run_complete_at: 2026-08-03
run_commit_sha: f3914f9439ab55993329e5035d6ee39da5399afa
run_status: PASS
ac_pass_count: 10
ac_fail_count: 0
preserve_list_post_run_count: 8
l44_pre_commit_fetch: n/a (Route A Hybrid Trunk main-direct, no PR — pre-spawn git fetch/rev-list divergence check not re-run within this delegation; HEAD confirmed at 63de7f662c35913a6f04d49a0af9193d983c2307 pre-flight)
l44_post_push_fetch: confirmed — `git push origin main` succeeded (63de7f6..f3914f9 main -> main), no rejection/divergence
new_warnings_or_lints_introduced: 0 (ruff check . — "All checks passed!" both pre- and post-change baselines)
cross_platform_build:
  applicable: false
  reason: "Python interpreted project — no GOOS-style cross-compile step exists. Import sanity (`from app.main import app`) and full pytest/ruff verified on Windows local dev only (single-platform)."
total_run_phase_files: 11 (1 new migration, 1 new test file, 7 modified source files, 2 modified pre-existing test files + progress.md/spec.md frontmatter)
m1_to_mN_commit_strategy: "Single milestone-grouped commits: M1(migration+persistence wiring), M2(cap 150→250), M3(price-fetch truncation exemption), M4(activation-criteria doc comments), M5(new + fixed tests). Actual commit boundaries recorded at push time below."
```

### Residual Gaps (미검증)

- **Migration NOT applied against a live DB**: `alembic upgrade head` / `alembic current` could not be executed — no local Postgres server reachable in this sandbox (`connection to server at "localhost" ... Connection refused`). Verified instead via static revision-chain checks (`alembic heads`, `alembic history -r 070:heads`, and a dedicated `ScriptDirectory`-based pytest test). The migration file mirrors the exact column-definition pattern of the original `064_surge_universe_pool_history.py` migration (same `server_default=sa.text("0")` + `comment=` style) that created this same table, so structural risk is low, but end-to-end DB application remains unverified in this session.
- **mypy unavailable**: `uv run mypy app/` failed with `Failed to spawn: mypy` (program not found) in this environment — a pre-existing environment limitation, not a regression introduced by this SPEC. Not verified this session.

## §E.4 Sync-phase Audit-Ready Signal

_<pending sync-phase>_
