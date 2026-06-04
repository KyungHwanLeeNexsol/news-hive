## Task Decomposition
SPEC: SPEC-AI-036

| Task ID | Description | Requirement | Dependencies | Planned Files | Status |
|---------|-------------|-------------|--------------|---------------|--------|
| T-001 | `build_surge_factor_scores(candidate, config) -> tuple[str, float]` 추가 | REQ-036-001, 007 | - | factor_scoring.py | pending |
| T-002 | 모든 surge_candidate 생성 지점 composite_score + factor_scores 설정 | REQ-036-001, 005 | T-001 | surge_detector.py | pending |
| T-003 | `surge_calibrator.py` 신규 생성 (PAV 알고리즘 + 영속화) | REQ-036-002, 006 | - | surge_calibrator.py | pending |
| T-004 | 주 1회 재학습 + 앱 시작 시 로드 훅 연결 | REQ-036-002 | T-003 | surge_calibrator.py, surge_detector.py (or scheduler) | pending |
| T-005 | 품질 floor 게이트 + YAML 설정 키 추가 | REQ-036-003 | T-001, T-002, T-003 | surge_detector.py, config | pending |
| T-006 | `signal_quality.py` 신규 (Brier, ECE, 분포 집계) | REQ-036-004 | T-001 | signal_quality.py | pending |
| T-007 | `GET /api/fund/signal-quality` 엔드포인트 추가 | REQ-036-004 | T-006 | routers/fund_manager.py | pending |
| T-008 | `test_surge_calibrator.py` 신규 작성 | test strategy | T-003 | tests/test_surge_calibrator.py | pending |
| T-009 | `test_surge_detector.py` 확장 (composite_score/floor 검증) | test strategy | T-001, T-002, T-005 | tests/test_surge_detector.py | pending |
