## Task Decomposition
SPEC: SPEC-AI-082

| Task ID | Description | Requirement | Dependencies | Planned Files | Status |
|---------|-------------|-------------|--------------|---------------|--------|
| T-001 | RED: `_gather_surge_candidates` 타임아웃 오폐기 특성화 테스트 작성 (소형 주입 타임아웃 + 블로킹 mock) 및 실패 확인 | REQ-AI082-004, REQ-AI082-005 | - | backend/tests/test_surge_ai082_gather_timeout.py | pending |
| T-002 | `_GATHER_TIMEOUT_S`를 함수-로컬 리터럴에서 모듈 상수로 승격 + 300→1200 상향, MX 태그 부여 | REQ-AI082-001, REQ-AI082-004 | T-001 | backend/app/services/fund_manager.py | pending |
| T-003 | GREEN: RED 테스트가 통과함을 확인 (적용 타임아웃 이내 완료 시 실제 후보 반환) | REQ-AI082-002 | T-002 | backend/tests/test_surge_ai082_gather_timeout.py | pending |
| T-004 | 안전망 거동 보존 테스트: 상향된 타임아웃마저 초과 시 경고 로그 + 빈 리스트 반환 확인 | REQ-AI082-003, REQ-AI082-007 | T-002 | backend/tests/test_surge_ai082_gather_timeout.py | pending |
| T-005 | 값 회귀 가드 테스트: 프로덕션 상수 >= 1200s 단언 | REQ-AI082-008 (AC-082-001) | T-002 | backend/tests/test_surge_ai082_gather_timeout.py | pending |
| T-006 | 범위 회귀 확인: 기존 test_surge_ai080_fund_manager.py 무회귀 + 전체 백엔드 스위트(기본 + -n 4) + ruff/mypy | REQ-AI082-006 | T-002..T-005 | (검증만, 파일 변경 없음) | pending |

Planned new files: `backend/tests/test_surge_ai082_gather_timeout.py`
Planned modified files: `backend/app/services/fund_manager.py`
