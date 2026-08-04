# SPEC-AI-100 Progress

## §E.1 Plan-phase Audit-Ready Signal

```yaml
plan_status: audit-ready
plan_complete_at: 2026-08-03
plan_auditor_verdict: PASS
plan_auditor_score: 0.92
plan_auditor_iteration: 2
plan_auditor_report: .moai/reports/plan-audit/SPEC-AI-100-review-2.md
```

(백필: 감사 결과가 plan-phase 당시 이 섹션에 기록되지 않았던 부기 누락을 run-phase 세션에서
발견해 사후 기록. `SPEC-AI-100-review-2.md`의 실제 verdict/score를 그대로 반영.)

## §E.2 Run-phase Evidence

Cycle: DDD (ANALYZE-PRESERVE-IMPROVE), quality.yaml `development_mode: ddd`.

### PRESERVE-list grep 검증 (plan.md §A.6 대상)

| 대상 | 검증 방법 | 결과 |
|------|-----------|------|
| `compute_ensemble_score()` 가중합·컨센서스 배율 본체 | `git diff` — 함수 본문 라인 무변경 | PASS (본문 라인 diff 0) |
| 3개 bypass 루프(즉각공시/강한단일신호/거래량폭발) | `git diff` — 해당 구간 라인 무변경 | PASS |
| `combo_chase_guard` Gate 4 판정 로직 | `git diff` — 판정 조건 라인 무변경(주석만 확장) | PASS |
| `sector_contagion` 게이트 | `git diff` — 라인 무변경 | PASS |
| `surge_threshold_service.py` 전체 | `git diff --name-only` | PASS (0 매치) |
| `_is_same_day_event_horizon_signal()`(평가 계층) | 함수 라인범위 기준 diff overlap 검사(pytest) | PASS |
| `_maybe_trigger_event_rescan()`(SPEC-AI-066 재스캔) | `git diff --name-only` (scheduler.py 무변경) | PASS |
| `detect_weekend_gap_up_signals`/`detect_bollinger_squeeze_signals` | `git diff --name-only`(fund_manager.py 무변경) | PASS |

`git diff backend/app/services/surge_detector.py`의 유일한 두 삭제 라인은
(1) Gate 4 주석 확장으로 대체된 `@MX:SPEC` 서브라인, (2) REQ-AI100-003이 명시적으로
요구하는 `if score >= effective_threshold:` → 플래그 조건부 분기 교체 — 둘 다 계획된
변경 지점이며 PRESERVE 대상과 무관하다.

### AC PASS/FAIL 매트릭스

| AC | Status | Verification Command | Actual Output |
|----|--------|----------------------|----------------|
| AC-100-001 | PASS | `pytest tests/test_spec_ai_100.py::TestHorizonLabelSafeDefault -q` | 1 passed |
| AC-100-002 | PASS | `pytest tests/test_spec_ai_100.py::TestHorizonSignatureComputation -q` | 4 passed |
| AC-100-003 | PASS | `pytest tests/test_spec_ai_100.py::TestThresholdSelection -q` | 4 passed |
| AC-100-004 | PASS | `pytest tests/test_spec_ai_100.py::TestThresholdSelection::test_none_signature_uses_existing_single_regime_path -q` | 1 passed |
| AC-100-005a | PASS | `pytest tests/test_spec_ai_100.py::TestGate4OrderPreserved::test_gate4_still_removes_combo_only_candidate -q` | 1 passed |
| AC-100-005b | PASS | `pytest tests/test_spec_ai_100.py::TestGate4OrderPreserved::test_gate4_removal_executes_before_horizon_signature_computation -q` | 1 passed |
| AC-100-006 | PASS | `pytest tests/test_spec_ai_100.py::TestShadowModeComparison::test_shadow_mode_logs_diff_when_paths_differ -q` | 1 passed |
| AC-100-007 | PASS | `pytest tests/test_spec_ai_100.py::TestShadowModeComparison::test_shadow_mode_exception_does_not_propagate -q` | 1 passed |
| AC-100-008 | PASS | `pytest tests/test_spec_ai_100.py::TestPreserveListUnchanged::test_orphan_detector_call_sites_unchanged -q` | 1 passed |
| AC-100-009 | PASS | `pytest tests/test_spec_ai_100.py::TestPreserveListUnchanged -k event_horizon_signal_or_event_rescan -q` | 2 passed |
| AC-100-010 | PASS | `pytest tests/test_spec_ai_100.py::TestPreserveListUnchanged::test_buy_execution_gate_unchanged tests/test_spec_ai_100.py::TestPreserveListUnchanged::test_compute_ensemble_score_body_unchanged -q` | 2 passed |
| AC-100-011 | PASS | `pytest tests/test_spec_ai_100.py::TestTransitionGateChecklistDocumented -q` | 1 passed |

### 신규 검증 (test_spec_ai_100.py, 20 tests)

```
$ cd backend && uv run pytest tests/test_spec_ai_100.py -q
20 passed in 0.55s
```

### 전체 회귀

```
$ cd backend && uv run pytest tests/ --tb=short -q -m "not slow"
2296 passed, 4 skipped, 3 xpassed, 259 warnings in 177.91s
```

### 정적 검사

```
$ cd backend && uv run ruff check .
All checks passed!

$ cd backend && uv run python -m mypy app/services/surge_detector.py app/surge_config/surge_settings.py
ModuleNotFoundError: No module named mypy  ← 이 venv에 mypy 미설치(SPEC-AI-100 이전부터의
                                              환경 갭, 본 SPEC이 야기하지 않음). Residual risk로 기록.
```

### Import sanity

```
$ cd backend && uv run python -c "from app.main import app; print('OK')"
OK
```

## §E.3 Run-phase Audit-Ready Signal

```yaml
run_status: audit-ready
run_complete_at: 2026-08-03
run_commit_sha: f64ecdccb1baba613049cb0f17d1cd4bb37f3f0e
ac_pass_count: 12
ac_fail_count: 0
preserve_list_post_run_count: 8
new_warnings_or_lints_introduced: 0
total_run_phase_files: 4
files_modified:
  - backend/app/services/surge_detector.py
  - backend/app/surge_config/surge_settings.py
  - backend/app/surge_config/surge_detection.yaml
files_added:
  - backend/tests/test_spec_ai_100.py
m1_to_mN_commit_strategy: single-commit (Tier L, DDD, 순수 추가/플래그 조건부 변경 —
  Milestone별 분리 커밋 없이 TASK-001~008을 한 커밋으로 통합. 근거: 모든 변경이
  horizon_aware_thresholds.enabled=false 상태에서 무해하며(plan.md §D), 별도 커밋으로
  나눠도 각 커밋이 독립적으로 완결된 상태가 아니므로(설정 스키마만 있고 소비 코드가
  없는 중간 커밋은 무의미) 단일 커밋이 더 명확한 이력을 남긴다.
mypy_skipped_reason: venv에 mypy 모듈 미설치 (SPEC-AI-100 이전부터의 환경 갭)
```

## §E.4 Sync-phase Audit-Ready Signal

```yaml
sync_status: audit-ready
sync_complete_at: 2026-08-04
sync_commit_sha: 2ad722e
b12_self_test_a_dup_grep: "grep -c 'SPEC-AI-100' CHANGELOG.md → 0 (pre-emission, no duplicate) → 1 (post-emission, single entry confirmed)"
b12_self_test_b_ac_count_match: "acceptance.md SSOT AC rows = 12 (AC-100-001~004, 005a, 005b, 006~011) — CHANGELOG entry states '12개 PASS', 일치"
b12_self_test_c_file_path_verification: "ls backend/app/services/surge_detector.py backend/app/surge_config/surge_settings.py backend/app/surge_config/surge_detection.yaml backend/tests/test_spec_ai_100.py → 전체 존재 확인"
changelog_entry_position: "CHANGELOG.md [Unreleased] 최상단(SPEC-AI-096 entry 바로 위) — 시간순 최신 배치"
frontmatter_status_transitions:
  spec_md: "in-progress → completed (updated: 2026-08-03 → 2026-08-04)"
  plan_md: "no independent frontmatter — status not tracked at file level, body untouched"
  acceptance_md: "no independent frontmatter — status not tracked at file level, body untouched (DoD checkboxes left as-is, body content out of manager-docs scope)"
canary_compliance_check:
  applicable: true
  reason: "REQ-AI100-009/AC-100-011이 섀도우→프로덕션 전환 게이트 구조적 최소 요건 3가지를 계획 단계에서 확정 — 이 SPEC 자신의 후속 sync가 테스트할 forward-looking policy"
  status: "not-yet-observed — shadow_mode_enabled: false(기본값), 섀도우 관측 미시작. 전환 게이트 3요건(관측 거래일≥10, 3개 레짐 전량 관측, qualified 집합 변화폭 ±30% 이내) 충족 여부는 관측 시작 이후 별도 확인 대상 — progress.md §G 런북 참고. 본 sync-phase는 게이트 구조(3요건 존재)가 §G에 문서화되어 있음만 확인했다(코드 리뷰, AC-100-011 검증 방법과 동일)."
```

### Sync verification evidence

- **CHANGELOG.md**: `[Unreleased]` 섹션에 SPEC-AI-100 feature entry 추가 (핵심 변경
  6항목, REQ-AI100-001~009 전체 커버, 변경 파일 목록 + 회귀 테스트 결과 인용).
- **spec.md frontmatter**: `status: in-progress → completed`, `updated: 2026-08-03 → 2026-08-04`.
  body content(REQ/Decisions/Open Questions)는 무수정 — frontmatter 2개 필드만 편집.
- **plan.md / acceptance.md**: 개별 frontmatter 없음(파일 최상단이 `# SPEC-AI-100 Plan`
  / `# SPEC-AI-100 Acceptance Criteria`로 시작, YAML 블록 없음) — 확인 후 무편집.
  body content(§A~§E, AC 매트릭스, DoD 체크박스) 전부 무수정.
- **B12 CHANGELOG 발행 규율 3-self-test**: 위 YAML 블록 참고, 전부 통과.

## §G 전환 게이트 체크리스트 (REQ-AI100-009 / AC-100-011)

`horizon_aware_thresholds.enabled: false → true` 전환 전 확인 절차. plan.md §D
"전환 게이트"의 구조적 최소 요건 3가지를 run-phase 완료 시점에 재확인한 런북.
수치(10 거래일, ±30%)는 잠정값(Open Question 2/3) — 섀도우 모드 관측 데이터
축적 후 조정 가능. 구조(3요건 체크 자체) 생략 불가.

- [ ] 요건 1 — 섀도우 모드 관측 거래일 수 ≥ 10 거래일 (잠정값)
- [ ] 요건 2 — 관측 기간 동안 BULL/SIDEWAYS/BEAR 3개 시장 레짐 각 1회 이상 관측
- [ ] 요건 3 — 신규 지평 인식 임계값 경로 qualified 후보 집합이 기존 경로 대비
      ±30%(잠정값) 이내 유지
- [ ] 3요건 중 하나라도 미충족 시 전환 보류, 추가 관측 또는 재검토

관측 시작 절차: `ensemble.horizon_aware_thresholds.shadow_mode_enabled: true`로
전환(`enabled`는 `false` 유지) → `[SPEC-AI-100 섀도우]` 로그 라인을 관측 기간
동안 수집 → 위 3요건 충족 확인 후에만 `enabled: true`로 전환 검토.

현재 상태: 섀도우 관측 미시작(`shadow_mode_enabled: false`, 기본값) — 관측 시작
및 3요건 충족 판단은 본 SPEC의 run-phase 범위 밖(acceptance.md §E DoD 명시).
