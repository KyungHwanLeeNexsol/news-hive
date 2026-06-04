## Task Decomposition
SPEC: SPEC-AI-037

| Task ID | Description | Requirement | Dependencies | Planned Files | Status |
|---------|-------------|-------------|--------------|---------------|--------|
| T-001 | surge_detection.yaml keywords 13→20 + sector_theme_map 확장 | REQ-037-001 | - | surge_detection.yaml | pending |
| T-002 | sector_theme_map 전체 섹터명 KRX _SNAPSHOT 정본 대조/수정 | REQ-037-004 | T-001 | surge_detection.yaml | pending |
| T-003 | combo_zero_theme_floor 0.7→0.55 | REQ-037-002 | - | surge_detection.yaml | pending |
| T-004 | min_market_cap_krw 1000억→500억 (옵션 a) | REQ-037-003 | - | surge_detection.yaml | pending |
| T-005 | is_combo_theme_gate_passed 조건부 floor (volume_z_score >= 3.0 시 0.7 유지) | REQ-037-002 | T-003 | surge_threshold_service.py | pending |
| T-006 | 비테마 fast path (disclosure >= 0.70 OR volume >= 0.80 & 비과열) | REQ-037-005 | T-003 | surge_threshold_service.py | pending |
| T-007 | 신규 테스트 + 회귀 검증 (AC-037-001~006) | REQ-037-006 | T-001~T-006 | tests/test_surge_ai037.py | pending |
