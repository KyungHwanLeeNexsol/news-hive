## Task Decomposition
SPEC: SPEC-FOLLOW-002

| Task ID | Description | Requirement | Dependencies | Planned Files | Status |
|---------|-------------|-------------|--------------|---------------|--------|
| T-001 | SecuritiesReport 모델 및 마이그레이션 041 생성 | REQ-FOLLOW-002-U1, U2, U3 | - | backend/app/models/securities_report.py, backend/alembic/versions/041_spec_follow_002_securities_reports.py | pending |
| T-002 | 증권사 리포트 크롤러 구현 (네이버 리서치) | REQ-FOLLOW-002-E1, E4, S1, N1, N3, O1 | T-001 | backend/app/services/securities_report_crawler.py | pending |
| T-003 | 키워드 매처 report 루프 + type_label 3원화 | REQ-FOLLOW-002-E2, E3, S2, N2 | T-001 | backend/app/services/keyword_matcher.py | pending |
| T-004 | 스케줄러에 _run_securities_report_crawl 잡 등록 | REQ-FOLLOW-002-E1, S1 | T-002 | backend/app/services/scheduler.py | pending |
| T-005 | 단위/통합 테스트 2종 작성 | AC-1~AC-6 전체 | T-001, T-002, T-003 | backend/tests/services/test_securities_report_crawler.py, backend/tests/services/test_keyword_matcher_report.py | pending |
