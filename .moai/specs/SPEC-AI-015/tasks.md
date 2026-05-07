# SPEC-AI-015 Task Decomposition

SPEC: SPEC-AI-015 Market Regime Adaptive Strategy
Created: 2026-05-07
Methodology: DDD ANALYZE-PRESERVE-IMPROVE
Harness: Standard

| Task | Description | Req | Dependencies | Planned Files | Status |
|---|---|---|---|---|---|
| T-001 | MarketRegime SQLAlchemy 모델 + MarketRegimeEnum 생성 | REQ-AI-015-001 | — | backend/app/models/market_regime.py (NEW) | pending |
| T-002 | models/__init__.py에 MarketRegime 등록 | REQ-AI-015-001 | T-001 | backend/app/models/__init__.py (MODIFY) | pending |
| T-003 | Alembic migration 053_spec_ai_015_market_regime (down_revision=052) | REQ-AI-015-001 | T-001 | backend/alembic/versions/053_spec_ai_015_market_regime.py (NEW) | pending |
| T-004 | market_regime_service.py 공개 API 전체 구현 (classify, get_or_create, get_params, get_recent) | REQ-AI-015-002,-003,-004,-005,-040,-041 | T-001,T-003 | backend/app/services/market_regime_service.py (NEW) | pending |
| T-005 | market_regime_service 단위 테스트 (경계값 9케이스 + fallback + idempotency) | REQ-AI-015-040,-041 | T-004 | backend/tests/services/test_market_regime_service.py (NEW) | pending |
| T-006 | [PRESERVE] paper_trading 특성 테스트 스냅샷 작성 (변경 전 동작 고정) | REQ-AI-015-042 | — | backend/tests/services/test_paper_trading_regime.py (NEW) | pending |
| T-007 | [IMPROVE] _position_pct_by_confidence(conf, db=None) 레짐 통합 | REQ-AI-015-020 | T-004,T-006 | backend/app/services/paper_trading.py (MODIFY) | pending |
| T-008 | [IMPROVE] execute_signal_trade() 일일 거래 한도 + 기본 TP/SL 레짐화 | REQ-AI-015-021,-022 | T-004 | backend/app/services/paper_trading.py (MODIFY) | pending |
| T-009 | [PRESERVE] fund_manager 특성 테스트 스냅샷 작성 (변경 전 동작 고정) | REQ-AI-015-042 | — | backend/tests/services/test_fund_manager_regime.py (NEW) | pending |
| T-010 | [IMPROVE] analyze_stock() 레짐 동적 confidence floor 교체 | REQ-AI-015-010 | T-004,T-009 | backend/app/services/fund_manager.py (MODIFY) | pending |
| T-011 | [IMPROVE] generate_daily_briefing() 하드코딩 제거 → 서비스 호출 | REQ-AI-015-011 | T-004,T-009 | backend/app/services/fund_manager.py (MODIFY) | pending |
| T-012 | 스케줄러 09:00 KST 레짐 갱신 잡 등록 (briefing 이전) | REQ-AI-015-030 | T-004 | backend/app/services/scheduler.py (MODIFY) | pending |
| T-013 | GET /api/fund/market-regime 엔드포인트 신설 | REQ-AI-015-031 | T-004 | backend/app/routers/fund_manager.py (MODIFY) | pending |
| T-014 | Pydantic 스키마 MarketRegimeResponse, RegimeParamsResponse 신설 | REQ-AI-015-031 | T-001 | backend/app/schemas/fund_manager.py (MODIFY) | pending |
| T-015 | API 통합 테스트 (200 OK, 빈 DB → SIDEWAYS, 7일 history desc) | REQ-AI-015-031 | T-013,T-014 | backend/tests/api/test_fund_market_regime.py (NEW) | pending |
| T-016 | [VERIFY] 전체 회귀: pytest + ruff + mypy 100% 통과 | REQ-AI-015-042,TRUST5 | ALL | All test files | pending |

## Dependency Graph

T-001 → T-002
T-001 → T-003
T-001, T-003 → T-004
T-004 → T-005
T-006 → T-007 (PRESERVE before IMPROVE)
T-004, T-006 → T-007
T-004 → T-008
T-009 → T-010 (PRESERVE before IMPROVE)
T-009 → T-011 (PRESERVE before IMPROVE)
T-004, T-009 → T-010
T-004, T-009 → T-011
T-004 → T-012
T-004 → T-013
T-001 → T-014
T-013, T-014 → T-015
T-007, T-008, T-010, T-011, T-013 → T-016

## Notes

- T-006 and T-009 are CHARACTERIZATION TESTS (DDD PRESERVE step) — they stay permanently after IMPROVE
- migration down_revision: 052_spec_ai_013_surge_portfolio
- KOSPI 20d MA source: benchmark._load_kospi_closes() — reuse existing, no new naver_finance function needed
- _position_pct_by_confidence: use db: Session | None = None to preserve backward compat
- Router path: /api/fund/market-regime (NOT /fund/market-regime — existing prefix is /api/fund)
- Async: fund_manager.py is async; market_regime_service DB ops are sync Session; KOSPI fetch uses asyncio.run() in sync scheduler context
