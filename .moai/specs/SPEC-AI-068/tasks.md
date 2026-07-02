## Task Decomposition
SPEC: SPEC-AI-068

| Task ID | Description | Requirement | Dependencies | Planned Files | Status |
|---------|-------------|-------------|--------------|---------------|--------|
| T-001 | 마이그레이션 065 + 모델 3종 스키마 확장(surge_universe_members 신규, SurgePredictionEvaluation 컬럼 4종, SurgeActualOutcome.surge_type) | REQ-001/002/003/005 | - | backend/app/models/surge_universe_member.py, backend/app/models/surge_prediction_evaluation.py, backend/app/models/surge_actual_outcome.py, backend/app/models/__init__.py, backend/alembic/versions/065_surge_universe_members.py | completed |
| T-002 | 유니버스 멤버 영속화 서비스(persist_universe_members/get_universe_members_for_date, 일자당 replace) | REQ-001 | T-001 | backend/app/services/surge_universe_pool_service.py, backend/tests/test_surge_universe_members.py | completed |
| T-003 | gather_surge_candidates 기록 훅 (surge_detector.py:1918 persist_pool_counts 블록에 추가, build_scan_universe 자체 불변) | REQ-001 | T-002 | backend/app/services/surge_detector.py | completed |
| T-004 | evaluate_surge_predictions 특성화 테스트 (재작성 전 현행 동작 고정 — PRESERVE) | REQ-002/003/004 선행조건 | - | backend/tests/test_surge_evaluation_service.py | completed |
| T-005 | 평가로직 재작성 — Scannable Recall/Coverage 산출 + 531-535 거짓전제 제거 | REQ-002/003/004 | T-001, T-004 | backend/app/services/surge_evaluation_service.py, backend/tests/test_surge_evaluation_service.py | completed |
| T-006 | 급등 유형 라벨링(surge_type scannable/non_scannable) + 트랙 경계 @MX:NOTE | REQ-005 | T-001, T-005 | backend/app/services/surge_evaluation_service.py, backend/tests/test_surge_evaluation_service.py | completed |
| T-007 | 회귀·품질 게이트 (전체 스위트, ruff/mypy, 예측기록 모드 불변 확인, 손계산 대조 로그) | DoD 전체 | T-001~T-006 | 검증 전용(코드 수정 없음) | completed |

Dependency graph: T-001 → {T-002 → T-003}, {T-004 (parallel)} → T-005 → T-006 → T-007

Decisions confirmed by user (2026-07-02):
- Universe persistence: (B) new child table `surge_universe_members`, composite PK (trading_date, stock_code), daily replace semantics.
- Legacy `recall` column: transitions to scannable_recall value when T-1 universe exists; retains legacy market-wide value when absent (past dates). `false_negative` stays market-wide (unchanged).
