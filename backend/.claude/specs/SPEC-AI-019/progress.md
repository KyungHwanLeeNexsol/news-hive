## SPEC-AI-019 Progress

- Started: 2026-05-27 (UTC)
- Phase 1 (Strategy): complete — task decomposition created (9 atomic tasks T-001 ~ T-009)
- Phase 2 (DDD Implementation): pending — awaiting user approval before manager-ddd handoff
- LSP baseline: <to be captured by Phase 2 agent>
- Test baseline: 1147 tests passing (SPEC-AI-018 baseline, to be reconfirmed by Phase 2)

### Phase 1 Deliverables

- backend/.claude/specs/SPEC-AI-019/tasks.md (task decomposition, 9 tasks)
- backend/.claude/specs/SPEC-AI-019/progress.md (this file)
- Strategy summary returned in agent response (plan, coverage, invariants, characterization plan)

### Next Steps (Phase 2 Handoff Contract)

When user approves:

1. manager-ddd loads tasks.md and executes T-001 ~ T-009 sequentially per `Dependencies` column.
2. ANALYZE step: read current SPEC-AI-018 implementation in surge_detector.py + fund_manager.py.
3. PRESERVE step: write characterization tests for Path A current behavior + SurgeCandidate dataclass serialization + `_gather_leading_candidates` post-filter logic BEFORE removing the duplicated filter (T-007 prerequisite).
4. IMPROVE step: implement T-001 through T-009 with TRUST 5 gates per task.
5. Each task update progress.md with completion timestamp.
