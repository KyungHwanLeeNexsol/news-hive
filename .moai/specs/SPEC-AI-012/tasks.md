## Task Decomposition
SPEC: SPEC-AI-012

| Task ID | Description | Requirement | Dependencies | Planned Files | Status |
|---------|-------------|-------------|--------------|---------------|--------|
| T-001 | surge_detection.yaml 설정 파일 작성 | REQ-SURGE-007 | - | backend/app/config/surge_detection.yaml | pending |
| T-002 | Pydantic Settings 로더 + 검증 | REQ-SURGE-007 | T-001 | backend/app/config/__init__.py, backend/app/config/surge_settings.py | pending |
| T-003 | 테마 뉴스 클러스터 탐지기 | REQ-SURGE-001 | T-002 | backend/app/services/surge_detector.py, backend/tests/test_surge_detector.py | pending |
| T-004 | 거래량 z-score + 뉴스 복합 신호 탐지기 | REQ-SURGE-002 | T-002 | backend/app/services/surge_detector.py, backend/tests/test_surge_detector.py | pending |
| T-005 | 공시 유형별 역사적 급등률 집계 함수 | REQ-SURGE-003 | T-002 | backend/app/services/surge_detector.py, backend/tests/test_surge_detector.py | pending |
| T-006 | 공시 유형 패턴 탐지기 | REQ-SURGE-003 | T-005 | backend/app/services/surge_detector.py, backend/tests/test_surge_detector.py | pending |
| T-007 | 앙상블 스코어 계산 (legacy_score = triggered/4) | REQ-SURGE-004 | T-003, T-004, T-006 | backend/app/services/surge_detector.py, backend/tests/test_surge_detector.py | pending |
| T-008 | FundSignal 마이그레이션 (surge_metadata 컬럼 추가) | REQ-SURGE-005 | T-007 | backend/alembic/versions/051_spec_ai_012_surge_signal.py, backend/app/models/fund_signal.py | pending |
| T-009 | fund_manager 통합 + 브리핑 주입 | REQ-SURGE-005 | T-008 | backend/app/services/fund_manager.py | pending |
| T-010 | 백테스트 모듈 | REQ-SURGE-006 | T-009 | backend/app/services/surge_backtest.py, backend/tests/test_surge_backtest.py | pending |
| T-011 | API 엔드포인트 GET /fund/surge-backtest | REQ-SURGE-006 | T-010 | backend/app/routers/fund_manager.py | pending |
| T-012 | magic number 검증 + conftest fixture + 전체 통합 테스트 | REQ-SURGE-007 | T-001~T-011 | backend/tests/conftest.py | pending |

## Architecture Decisions
- FundSignal.surge_metadata: JSONB nullable 신규 컬럼 (마이그레이션 051)
- legacy_score = min(1.0, num_legacy_detectors_triggered / 4)
- 라우터: backend/app/routers/fund_manager.py (SPEC의 api/fund.py 정정)
- signal_type: String(30) — ALTER TYPE 불필요
- 캐싱: in-memory dict + TTL 24h (Redis 불필요)
