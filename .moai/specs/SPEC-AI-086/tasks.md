## Task Decomposition
SPEC: SPEC-AI-086

| Task ID | Description | Requirement | Dependencies | Planned Files | Status |
|---------|-------------|-------------|--------------|---------------|--------|
| TASK-001 | PRESERVE 특성화 골든 베이스라인 (현재 build_scan_universe 150-cap 출력 + quota 배분 바이트 고정 C1/C3/C4) + non_scannable 진단 결손 RED 재현 C2 | (선행 게이트; AC-086-003/004 기반) | - | backend/tests/test_spec_ai_086.py | completed |
| TASK-002 | REQ-001 상한 설정 유연화 + 경계 clamp | REQ-AI086-001 | TASK-001 | backend/app/surge_config/surge_settings.py, backend/app/services/surge_detector.py, backend/app/surge_config/surge_detection.yaml, backend/tests/test_spec_ai_086.py | completed |
| TASK-003 | REQ-002 non_scannable 원인 진단 truncated vs absent | REQ-AI086-002 | TASK-001 | backend/app/services/surge_evaluation_service.py, backend/app/services/scheduler.py, backend/app/routers/surge_trading.py, backend/tests/test_spec_ai_086.py | completed |
| TASK-004 | REQ-003 Pool D 신규 소스 풀 + pool_d_min_slots quota 통합, 기본 OFF | REQ-AI086-003 | TASK-001 | backend/app/surge_config/surge_settings.py, backend/app/services/surge_detector.py, backend/app/surge_config/surge_detection.yaml, backend/tests/test_spec_ai_086.py | completed |
| TASK-005 | REQ-004 장중 시간대별 동적 상한(기본 OFF) | REQ-AI086-004 | TASK-002 | backend/app/surge_config/surge_settings.py, backend/app/services/surge_detector.py, backend/app/surge_config/surge_detection.yaml, backend/tests/test_spec_ai_086.py | completed |
| TASK-006 | REQ-005 측정 전용 비용 경계 회귀 assert [HARD] | REQ-AI086-005 | TASK-002, TASK-004 | backend/tests/test_spec_ai_086.py | completed |
| TASK-007 | REQ-006 지표 정합성 명명 토큰 scannable_denominator_expanded [HARD] | REQ-AI086-006 | TASK-003 | backend/app/services/surge_evaluation_service.py, backend/app/services/scheduler.py, backend/app/routers/surge_trading.py, backend/tests/test_spec_ai_086.py | completed |
| TASK-008 | REQ-007 백워드 호환 바이트 동등 게이트 [HARD] | REQ-AI086-007 | TASK-002, TASK-004, TASK-005 | backend/tests/test_spec_ai_086.py | completed |
| TASK-009 | REQ-008 관측성 단일 로그 라인 | REQ-AI086-008 | TASK-002, TASK-003, TASK-004 | backend/app/services/surge_detector.py, backend/app/services/surge_evaluation_service.py, backend/tests/test_spec_ai_086.py | completed |

## Follow-up round (TRUST5 WARNING 보완, iteration 2)

- Pool D fail-open 예외 경로 테스트 추가 (surge_detector.py:4682-4687)
- 3-풀 비례 clamp 분기(pool_d 초과) 테스트 추가 (surge_detector.py:4735-4739)
- REQ-002/REQ-006 프로덕션 배선: scheduler.py `_run_surge_verify_predictions`(18:30 KST) + surge_trading.py `re_evaluate_surge_predictions`에 `prior_scannable_metrics` 전달 + `diagnose_non_scannable_causes` 호출 추가 (fail-open, Exclusion 1 불가침 확인)
- 결과: 24 tests passed (was 22), 전체 스위트 2094 passed 무회귀, ruff clean

This file is git-tracked. Update task status as implementation progresses.
The planned_files column is used by the Drift Guard (Phase 2A/2B) to detect scope drift.
