## Task Decomposition
SPEC: SPEC-AI-041

| Task ID | Description | Requirement | Dependencies | Planned Files | Status |
|---------|-------------|-------------|--------------|---------------|--------|
| T-001 | SurgeActualOutcome 모델 + __init__ 등록 | R1.3, R1.4 | - | backend/app/models/surge_actual_outcome.py, backend/app/models/__init__.py | pending |
| T-002 | SurgePredictionEvaluation 모델 + __init__ 등록 | R2.4 | - | backend/app/models/surge_prediction_evaluation.py | pending |
| T-003 | SurgeAutoImprovementLog 모델 + __init__ 등록 | R7.1 | - | backend/app/models/surge_auto_improvement_log.py | pending |
| T-004 | Migration 058_surge_actual_outcome.py | §3.4 | T-001 | backend/alembic/versions/058_surge_actual_outcome.py | pending |
| T-005 | Migration 059_surge_prediction_evaluation.py | §3.4 | T-002, T-004 | backend/alembic/versions/059_surge_prediction_evaluation.py | pending |
| T-006 | Migration 060_surge_auto_improvement_log.py | §3.4 | T-003, T-005 | backend/alembic/versions/060_surge_auto_improvement_log.py | pending |
| T-007 | reload_surge_config() 추가 | R8.1, R8.2 | - | backend/app/surge_config/surge_settings.py | pending |
| T-008 | surge_actual_outcome_service.py — collect_daily_surge_outcomes | R1.1~R1.5 | T-001 | backend/app/services/surge_actual_outcome_service.py | pending |
| T-009 | surge_evaluation_service.py — evaluate_surge_predictions + T-1 역산 | R2.1~R2.4 | T-001, T-002 | backend/app/services/surge_evaluation_service.py | pending |
| T-010 | surge_evaluation_service.py — analyze_misses_with_llm (Gemini+fallback) | R3.1~R3.3 | T-009 | backend/app/services/surge_evaluation_service.py | pending |
| T-011 | surge_auto_improver.py — analyze_and_improve + YAML targeted_update + R11/R12 | R4~R8, R11, R12 | T-007, T-009, T-010 | backend/app/services/surge_auto_improver.py | pending |
| T-012 | format_telegram_report() + TELEGRAM_ADMIN_CHAT_ID env | R9.1, R9.2 | T-011 | backend/app/services/surge_auto_improver.py | pending |
| T-013 | scheduler.py — 4개 잡 래퍼 + 등록 (16:10/16:30/16:50/17:05 KST) | R1.1, R2.1, R9.1, R10 | T-008, T-009, T-011, T-012 | backend/app/services/scheduler.py | pending |
| T-014 | surge_trading.py — 3개 GET 엔드포인트 | §3.3 | T-002, T-003 | backend/app/routers/surge_trading.py | pending |
| T-015 | 테스트: 정규화/클램프/R10/R11/R12/T-1 역산/YAML 주석 보존 | SC-3, SC-5 | T-001~T-014 | backend/tests/test_surge_*.py (4개) | pending |
