## Task Decomposition
SPEC: SPEC-AI-080

| Task ID | Description | Requirement | Dependencies | Planned Files | Status |
|---------|-------------|-------------|---------------|--------|--------|
| T0 | 결정 확정: OQ-1 타임존 검증(SSH date/Postgres SHOW TimeZone), OQ-2 컷오프=15:20, DP-1=마커인지형 스킵, DP-2=파생계산, OQ-5 마커 형태. 신테카바이오 07-09 16:41 케이스를 테스트 픽스처로 확보 | M0 | - | - | done |
| T1 | `surge_detection.yaml`에 `immediate_surge` 블록(enabled:false 기본) 추가 + `surge_settings.py`에 Pydantic 서브모델 추가 | REQ-001/002/003 | T0 | surge_detection.yaml, surge_settings.py | done |
| T2 | 특성화 테스트(PRESERVE): process_disclosure_impact 기존 3분기, evaluate_surge_predictions predicted_set, fund_manager.py 두 덮어쓰기 사이트의 비-즉시발화 행 거동 고정 | - | T0 | test files | done |
| T3 | 즉시발화 발신 헬퍼(`_create_immediate_surge_signal`) 구현 — OQ-5 마커, 이벤트클래스+impact_score 게이팅, execute_signal_trade 미호출, 네이티브 키 정합 업서트 | REQ-001/002/003/005 | T1, T2 | disclosure_impact_scorer.py | done |
| T4 | `process_disclosure_impact`에 즉시발화 분기 연결, 15:20 컷오프로 horizon(next_day/same_day) 태깅 | REQ-001/004 | T3 | disclosure_impact_scorer.py | done |
| T5 | `evaluate_surge_predictions`에 recall 편입(next_day) + 당일 서브지표 분리(same_day, 파생계산) | REQ-004 | T3 | surge_evaluation_service.py | done |
| T6 | 재탐지 업서트(fund_manager.py:1437-1464) 마커인지형 스킵 — `_is_immediate_disclosure_signal` 헬퍼, R-7 무회귀 확인 | REQ-006/REQ-004불변식 | T3 | fund_manager.py | done |
| T7 | 캐리오버(fund_manager.py:1531-1597) 마커인지형 스킵 + Scenario 7 종단 재현 테스트 | REQ-006/REQ-004불변식 | T6 | fund_manager.py | done |
| T8 | 타임존 야간 경계 검증/보정(OQ-1/R-5/EC-3) | REQ-004 | T4 | (검증 후 필요 시) | done (검증만, 코드 수정 불필요 확정) |
| T9 | 전체 회귀 + 품질 게이트(pytest -m "not slow", -n 4, ruff, mypy, 커버리지 85%+) | M4 | T4,T5,T6,T7,T8 | - | done (mypy 프로젝트 미설치로 스킵) |
| T10 | (P2 선택) 관측성 로그/서브지표 집계 | REQ-007 | T9 | - | done (evaluate_surge_predictions 내 로그 라인으로 충족, 별도 모듈 불필요) |

This file is git-tracked. Update task status as implementation progresses.
The planned_files column is used by the Drift Guard (Phase 2A/2B) to detect scope drift.
