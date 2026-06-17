## Task Decomposition
SPEC: SPEC-AI-051

| Task ID | Description | Requirement | Dependencies | Planned Files | Status |
|---------|-------------|-------------|--------------|---------------|--------|
| T-001 | SurgeCandidate에 squeeze_score 필드 추가 | REQ-AI051-001 | - | backend/app/services/surge_detector.py | pending |
| T-002 | calculate_bollinger_bandwidth_squeeze() 헬퍼 신규 | REQ-AI051-002 | T-001 | backend/app/services/technical_indicators.py | pending |
| T-003 | detect_bollinger_squeeze_signals() 탐지기 신규 | REQ-AI051-002 | T-001, T-002 | backend/app/services/surge_detector.py | pending |
| T-004 | 15:10 KST 스케줄러 잡 추가 | REQ-AI051-003 | T-003 | backend/app/services/scheduler.py | pending |
| T-005 | Tier 1/2/3 키워드 사전 정의 | REQ-AI051-004 | - | backend/app/services/disclosure_impact_scorer.py | pending |
| T-006 | score_disclosure_impact() Tier 배수 적용 | REQ-AI051-005, REQ-AI051-006 | T-005 | backend/app/services/disclosure_impact_scorer.py | pending |
| T-007 | detect_gap_up_runners() 탐지기 신규 | REQ-AI051-007, REQ-AI051-008, REQ-AI051-009 | - | backend/app/services/surge_detector.py | pending |
| T-008 | early_entry_check() signal_type 필터 확장 | REQ-AI051-010 | T-007 | backend/app/services/preday_signal_service.py | pending |
| T-009 | 14:30 KST 스케줄러 잡 추가 | REQ-AI051-010 | T-007 | backend/app/services/scheduler.py | pending |
| T-010 | 단위 테스트 작성 | All REQ | T-001~T-009 | backend/tests/services/test_spec_ai_051.py | pending |
