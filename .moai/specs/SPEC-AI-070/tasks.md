## Task Decomposition
SPEC: SPEC-AI-070

| Task ID | Description | Requirement | Dependencies | Planned Files | Status |
|---------|-------------|-------------|--------------|---------------|--------|
| T-001 | 모델 SurgeDetectorContribution + 마이그레이션 067(down_revision=066_surge_backtest_result) | REQ-001/002 | - | backend/app/models/surge_detector_contribution.py, backend/alembic/versions/067_surge_detector_contribution.py, backend/app/models/__init__.py | done |
| T-002 | 기여도 5지표 집계 서비스(surge_basis 파싱 × scannable attribution, 순수 Python) | REQ-001/002 | T-001 | backend/app/services/surge_contribution_service.py | done |
| T-003 | 탐지기 3분류(weighted_sum/standalone/0-가중치) + dead-weight/consensus 리포트 | REQ-002 | T-002 | backend/app/services/surge_contribution_service.py | done |
| T-004 | backtest 검증 은퇴 제안(compute_surge_backtest fresh 호출, before/after directional accuracy) + retire_candidate 플래그 | REQ-003 | T-002, T-003 | backend/app/services/surge_contribution_service.py | done |
| T-005 | auto-removal 금지 가드 + 잔여 가중치 재정규화 경고 | REQ-004 | T-004 | backend/app/services/surge_contribution_service.py | done |
| T-006 | 학습형 앙상블 타당성 평가 리포트(오프라인 로지스틱, 모델 미배포) | REQ-005 | T-002 | backend/app/services/surge_contribution_service.py | done |
| T-007 | 스케줄러 잡(19:05 KST) + 텔레그램 리포트 배선 + 선택적 조회 엔드포인트 | REQ-001~004 통합 | T-002~T-006 | backend/app/services/scheduler.py, backend/app/routers/surge_trading.py(선택) | done (선택 엔드포인트는 시간 제약으로 생략, P0 우선) |
| T-008 | 068/069 무회귀 격리 증명 + 엣지케이스(EC-1~EC-7) 전체 커버 | 횡단 | T-001~T-007 | backend/tests/test_spec_ai_070.py | done |

Dependency graph: T-001 → T-002 → {T-003 → T-004 → T-005}, {T-006 (parallel from T-002)} → T-007 → T-008

Confirmed technical decisions (2026-07-02, manager-strategy verified against code):
- Migration: 067_surge_detector_contribution, down_revision=066_surge_backtest_result (066 is current alembic head, confirmed via `alembic heads`).
- Architecture: fully separate job (NOT a hook inside evaluate_surge_predictions) — evaluate_surge_predictions doesn't load per-signal surge_basis, and separation guarantees zero diff to SPEC-AI-068/069 characterization tests.
- Scheduler slot: 19:05 KST mon-fri, id="surge_detector_contribution", after 18:30 verify + 18:45 backtest_gate, before 19:00 auto_improve (avoid collision).
- Correction found: 5 ensemble component scores (theme_cluster_score/combo_score/pattern_score/immediate_disclosure_score/legacy_score) ARE actually persisted in surge_metadata (surge_detector.py:2291-2306) — contradicts spec.md's blanket "component score not persisted" claim. Standalone/bypass detector scores remain unpersisted. Approach unchanged (membership attribution for all detectors uniformly), but report footnote (EC-6) corrected to reflect partial persistence.
