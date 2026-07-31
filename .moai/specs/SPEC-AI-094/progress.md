# SPEC-AI-094 Progress

## §E.1 Plan-phase Audit-Ready Signal

- plan_status: audit-ready
- plan_complete_at: 2026-07-30
- plan-auditor 독립 재감사(standalone): PASS, score 0.87 (6개 AC 전수 토큰 레벨 파싱 — 재실행 불필요, `.claude/rules/moai/workflow/spec-workflow.md` Plan Audit Gate skip policy 4조건 미충족 세부는 orchestrator §A Context 참조)
- Implementation Kickoff Approval: 사용자 승인 완료 (오케스트레이터 위임 프롬프트에 명시)

## §F Phase 4 Mode Selection

**Input parameters**:
- tier: S
- scope (file count): 3 (`backend/app/services/surge_detector.py`, `backend/app/surge_config/surge_settings.py` 수정 + `backend/tests/test_spec_ai_094.py` 신규)
- domain count: 1 (backend surge-detection 서비스 계층, 단일 도메인)
- file language mix: 100% Python
- concurrency benefit: LOW (DDD ANALYZE-PRESERVE-IMPROVE 순차 사이클, 리스트 컴프리헨션 1줄 교정 + 설정 필드 1개 — coding-heavy)

**Mode evaluation**:

| Mode | Selected? | Rationale |
|------|-----------|-----------|
| 1 trivial | No | 판정 기준 교정 + 신규 config 필드 + 로그 라인 확장 + 신규 테스트 5종 — 단순 오타/포맷 아님 |
| 2 background | No | Write 작업이며 결과를 즉시 검증(전체 회귀)해야 함 |
| 3 agent-team | No | RETIRED |
| 4 parallel | No | coding-heavy 단일 도메인 — Anthropic coding-task parallelism caveat |
| 5 sub-agent | **Yes** | 단일 서비스 파일 국소 수정, 순차 DDD 사이클에 적합 (Anthropic coding-task 기본값) |
| 6 workflow | No | 파일 수 3개, 기계적 반복 변환 아님(≥30파일 기준 미충족) |

**Decision: sub-agent**

**Justification**: SPEC-AI-094는 `build_scan_universe()` 내부 판정 기준 교정(entry_pool_map 등재
여부 → 풀 소속 여부) + config 필드 1개 + 로그 라인 확장에 국한된 Tier S 변경으로, 병렬화로
얻을 이득이 없는 coding-heavy 작업이다. quality.yaml의 `development_mode: ddd` 설정에 따라
manager-develop을 cycle_type=ddd로 순차 위임한다. Implementation Kickoff Approval 통과 확인.

## §E.2 Run-phase Evidence

Route A (Hybrid Trunk main-direct, Tier S) — manager-develop cycle_type=ddd.

### 변경 파일 (3개, plan.md §A.5 PRESERVE 범위 준수)

| 파일 | 성격 |
|------|------|
| `backend/app/surge_config/surge_settings.py` | EXTEND — `scan_universe_include_existing: bool = False` 신규 필드 (TASK-001) |
| `backend/app/services/surge_detector.py` | EXTEND — `build_scan_universe()` 병합 필터 판정 기준 교정 + 로그 라인 확장 (TASK-002, TASK-003) |
| `backend/tests/test_spec_ai_094.py` | 신규 — 플래그 ON 신규 동작 5종 (TASK-004) |

`backend/tests/test_spec_ai_065.py`는 **무수정**이다 — AC-076-004 characterization 단언
(`assert not (final_set & existing_codes)`)을 그대로 보존(TASK-005, REQ-AI094-005).

### AC PASS/FAIL 매트릭스

| AC ID | Status | Verification Command | Actual Output |
|-------|--------|----------------------|----------------|
| AC-094-001 | PASS | `pytest tests/test_spec_ai_094.py::TestFlagOnNoTruncationPressure -q` | `2 passed` — existing 5개 전부 포함, `len(final_universe)==35`, `entry_pool_map=="existing"` |
| AC-094-002 | PASS | `pytest tests/test_spec_ai_065.py tests/test_spec_ai_086.py -q` (무수정 파일) | `142 passed` — 골든 순서(`test_golden_order_and_pool_counts_default_config`) + `test_spec_ai_086.py` 골든 유니버스 무회귀 |
| AC-094-003 | PASS | `pytest tests/test_spec_ai_092.py tests/test_spec_ai_089.py tests/test_spec_ai_070.py -q` + `git diff --name-only \| grep -E 'surge_evaluation_service\|surge_universe_gap_service\|surge_auto_improver\|scheduler'` | 테스트 전부 통과 + grep 0 매치(exit=1) |
| AC-094-004 | PASS | `pytest tests/test_spec_ai_094.py::TestFlagOnTruncationPressure -q` | `1 passed` — A=232/C=52/cap=150, existing 대표 0개, `len==150`, Pool C quota 대표성(`>=30`) 유지 |
| AC-094-005 | PASS | `pytest tests/test_spec_ai_094.py::TestExistingMetricShiftLogging -q` | `2 passed` — `existing_only=5`(ON/OFF 공통) + `existing_included=5`(ON) / `existing_included=0`(OFF) 로그 필드 확인 |
| AC-094-006 | PASS | `grep -c "assert not (final_set & existing_codes)" backend/tests/test_spec_ai_065.py` | `1` (>=1 충족, 파일 무수정) |

### TASK 이행

- TASK-001: `SurgeDetectionConfig.scan_universe_include_existing: bool = False` — `dynamic_scan_universe_caps` 필드 뒤에 배치, 활성화 시 지표 분모 이동 경고 주석 포함
- TASK-002: `_pool_member_codes`(A/B/C/D 풀 소속 집합) 캡처 + `_existing_only`(플래그 무관 상시 계산, `sorted()`로 결정론적 순서 고정) + `_existing_tail`(플래그 조건부) 도입. `universe_ordered`의 마지막 항을 `_existing_tail`로 교체. `:4832-4846`의 existing 등재 루프 자체(`entry_pool_map[code] = "existing"`)는 **바이트 단위로 무수정**. Exclusion 10 주석을 SPEC-AI-094 교정 취지로 갱신(주석 삭제 아님)
- TASK-003: 최종 유니버스 로그 라인에 `existing_only=%d existing_included=%d` 필드 추가. `pool_counts`(REQ-AI094-002 바이트 동등 대상) 반환값에는 신규 키를 넣지 않고 로그 라인에만 확장(지역 변수 `_existing_only` + `scanned_tally.get("existing", 0)` 재사용)
- TASK-004: `backend/tests/test_spec_ai_094.py` 신규 — AC-094-001/004/005 케이스 5종. SPEC-AI-076 픽스처 헬퍼(`_make_pool_a_disclosures`/`_make_pool_c_outcomes`/`_make_pool_b_codes`/`_pool_b_patches`)를 `test_spec_ai_065`에서 import 재사용(plan.md §B TASK-004 결정)
- TASK-005: `test_spec_ai_065.py`/`test_spec_ai_086.py`/`test_spec_ai_074.py`/`test_spec_ai_089.py`/`test_spec_ai_092.py`/`test_spec_ai_070.py` 무수정 통과(142개) 확인 — 어느 하나도 수정 불필요, REQ-AI094-002 위반 신호 없음

## §E.3 Run-phase Audit-Ready Signal

- run_status: audit-ready
- run_complete_at: 2026-07-31
- 타깃 테스트: `pytest tests/test_spec_ai_094.py -q` → `5 passed`
- 회귀(TASK-005 지정 6개 파일): `pytest tests/test_spec_ai_065.py tests/test_spec_ai_086.py tests/test_spec_ai_074.py tests/test_spec_ai_089.py tests/test_spec_ai_092.py tests/test_spec_ai_070.py -q` → `142 passed`
- 전체 회귀: `pytest tests/ -q -m "not slow"` → `2249 passed, 4 skipped, 3 xpassed`
- xdist 레이스 확인(`-n 4`): `pytest tests/ -q -m "not slow" -n 4` → `2249 passed, 4 skipped, 3 xpassed` (2026-07-03 CI xdist 레이스 재발 없음)
- 커버리지(수정 파일 대상, 전체 스위트 기준): `surge_detector.py` 81%(전체 파일 기준, 신규 라인 4832-4919/4943-4964는 missing 목록에 없음 — 완전 커버), `surge_settings.py` 99%
- 정적 검사: `ruff check .` → `All checks passed!` / `mypy` 미검증 — venv에 mypy 미설치(`uv run mypy` 시도 시 `program not found`), SPEC-AI-093과 동일한 기존 환경 Gap 승계
- 범위 규율 grep(AC-094-003): `git diff --name-only | grep -E 'surge_evaluation_service|surge_universe_gap_service|surge_auto_improver|scheduler'` → 0 매치(exit=1)
- run_commit_sha: (M1 커밋에서 backfill 예정 — pending-backfill-m1)

### Gap (미검증)

- `mypy` 정적 타입 검사는 환경에 미설치되어 미실행(기존 Gap, SPEC-AI-093에서도 동일하게 관측)
- `scan_universe_include_existing=True` 활성화 시 실제 운영 `scannable_recall`/`coverage` 지표
  이동 폭은 배포 후 로깅(`existing_only`/`existing_included`) 관측이 필요(spec.md Open
  Question 2 — 본 SPEC 범위는 배선까지이며 활성화는 별도 결정)
