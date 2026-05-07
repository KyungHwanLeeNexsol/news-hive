# SPEC-AI-015 Progress

- Started: 2026-05-07
- Phase 0.9 complete: Python project detected (pyproject.toml) → moai-lang-python
- Phase 0.95 complete: 10 files, 1 domain → Standard Mode selected
- Phase 1 complete: manager-strategy execution plan approved by user
- Phase 1.5 complete: 16 tasks decomposed with dependency graph → tasks.md
- Phase 1.6 complete: 10 acceptance criteria registered as pending tasks
- Phase 1.7: stub files pending

## Key Technical Decisions

- Migration: 053_spec_ai_015_market_regime (down_revision=052)
- KOSPI 20d MA: reuse benchmark._load_kospi_closes() — no new naver_finance function
- Signature change: _position_pct_by_confidence(conf, db: Session | None = None) — optional db param for backward compat
- Sync/async: market_regime_service DB ops = sync Session; KOSPI fetch = async via asyncio.run() in scheduler
- Router path: /api/fund/market-regime (matches existing /api/fund/* prefix)
- No lru_cache in M1 (YAGNI — UNIQUE index query is sub-ms)
