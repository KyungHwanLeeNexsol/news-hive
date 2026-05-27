## SPEC-AI-019 Progress

- Started: 2026-05-27 (UTC)
- Phase 1 (Strategy): complete — task decomposition created (9 atomic tasks T-001 ~ T-009)
- Phase 2 (DDD Implementation): complete — 2026-05-27

### Phase 1 Deliverables

- backend/.claude/specs/SPEC-AI-019/tasks.md (task decomposition, 9 tasks)
- backend/.claude/specs/SPEC-AI-019/progress.md (this file)
- Strategy summary returned in agent response (plan, coverage, invariants, characterization plan)

### Phase 2 PRESERVE complete

CT-1/CT-2/CT-3/CT-4 captured.
Baseline test counts: 84 passed (test_surge_ai018 35 + test_surge_detector + test_surge_scoring).
Characterization tests: 15 passed (test_surge_ai019_characterization.py).
LSP baseline: py_compile N/A (Python not in bash PATH). No syntax errors observed.
CT-4 schema findings: per/pbr keys are "per"/"pbr" in KIS API response (kis_data.per, kis_data.pbr).
_fetch_price_change_sync returns only change_rate/current_price (no per/pbr).
per/pbr extraction uses KIS in-memory cache read (no additional HTTP calls).

### Phase 2 IMPROVE complete

- T-001 completed: SurgeCandidate에 per/pbr 필드 추가 (float | None = None, line 74-75)
- T-002 completed: _extract_valuation(stock_code, market_data) 헬퍼 함수 추가 (line 330-383)
- T-003 completed: detect_theme_news_cluster 탐지기에 per/pbr piggy-back 수집 추가
- T-004 completed: detect_volume_surge_news_combo 탐지기에 per/pbr piggy-back 수집 추가
- T-005 completed: detect_disclosure_surge_pattern 탐지기에 per/pbr piggy-back 수집 추가
- T-006 completed: gather_surge_candidates에 밸류에이션 필터 단일 지점 배치 (@MX:ANCHOR)
- T-007 completed: fund_manager.py:1707-1724 중복 필터 제거 (SPEC-AI-019 REQ-006 마커로 대체)
- T-008 completed: test_surge_ai019_path_b.py 신규 테스트 17건 작성, 전부 통과
- T-009 completed: MX 태그 검증, 전체 회귀 슈트 실행

### Final Verification

Timestamp: 2026-05-27 (UTC)
Test count: 116 passed (surge-related tests), 0 failed
- test_surge_ai018.py: 36 passed (pre-existing CWD issue 1건 포함)
- test_surge_detector.py: passes
- test_surge_scoring.py: passes
- test_surge_ai019_characterization.py: 15 passed (NEW)
- test_surge_ai019_path_b.py: 17 passed (NEW)
Full suite: 1112 passed + pre-existing 5 failed + 62 errors (all `jose` module missing, pre-existing)

Files modified:
- backend/app/services/surge_detector.py (+110 lines: fields, helper, piggy-back, filter)
- backend/app/services/fund_manager.py (-19 lines: duplicate filter removed)

Files created:
- backend/tests/test_surge_ai019_path_b.py (17 new tests)
- backend/tests/test_surge_ai019_characterization.py (15 characterization tests)
- backend/.claude/specs/SPEC-AI-019/baseline-ai018.txt

Drift: 2/2 planned files modified + 2 new test files. No unplanned file modifications. Drift within scope.

INV Verification:
- INV-1 (SurgeCandidate per/pbr added): PASS — per/pbr fields at lines 74-75
- INV-2 (piggy-back no extra API calls): PASS — KIS cache read only
- INV-3 (single filter point): PASS — single @MX:ANCHOR block in gather_surge_candidates
- INV-4 (strict greater-than boundary): PASS — per > vd.max_per (not >=)
- INV-5 (API call count unchanged): PASS — _extract_valuation reads KIS cache only
- INV-6 (None/0 passes): PASS — filter condition: per > 0 AND per > max_per
- INV-7 (max_per/max_pbr single location): PASS — surge_detector 1 block, fund_manager 0 blocks
- INV-8 (SPEC-AI-018 regression): PASS — all 36 test_surge_ai018.py tests pass
