## Task Decomposition
SPEC: SPEC-AI-083

| Task ID | Description | Requirement | Dependencies | Planned Files | Status |
|---------|-------------|-------------|--------------|---------------|--------|
| T-001 | ANALYZE: 재스캔 잡 등록 지점(scheduler.py start_scheduler 급등 블록), run_surge_signal_generation 후보 생성·메타데이터 경로, SPEC-AI-080 horizon 태깅/평가 경로, 이벤트 재스캔 가드 경로 정독 및 특성화 대상 식별 | REQ-AI083-001, REQ-AI083-005 | - | (분석만) | pending |
| T-002 | PRESERVE(RED): 현행 단일 10:00 잡 + same-day 귀속 부재 시 표준 T-1→T 버킷 처리 특성화 테스트 작성 및 기준선 확인 | REQ-AI083-002, REQ-AI083-005 | T-001 | backend/tests/test_surge_ai083_intraday_rescan.py | pending |
| T-003 | IMPROVE: 09:05~BUY_CUTOFF 구간 재스캔 cron 다중 잡 등록(조기 09:10 포함, ~20분 간격, distinct id, max_instances=1/coalesce=True), 콜백은 후보 생성만 호출 | REQ-AI083-001, REQ-AI083-002, REQ-AI083-003, REQ-AI083-004 | T-002 | backend/app/services/scheduler.py | pending |
| T-004 | IMPROVE: 장중 재스캔 당일 후보에 same-day 지평(horizon="same_day") 귀속 배선 — SPEC-AI-080 메타데이터+평가 경로 재사용(스키마 0). GREEN 확인 | REQ-AI083-005 | T-003 | backend/app/services/fund_manager.py (run_surge_signal_generation 경로) | pending |
| T-005 | 방향 B(회귀 보호): immediate_surge 활성 상태 + same_day 평가 경로 diff 0 확인, 기존 SPEC-AI-080 테스트 무회귀 | REQ-AI083-007 | T-003, T-004 | backend/tests/test_surge_ai083_intraday_rescan.py | pending |
| T-006 | 방향 B(활성화): catalyst_conviction.event_rescan_enabled false→true + 가드(쿨다운 30분/일일 20회) 준수 검증, 가드 값 불변 | REQ-AI083-008, REQ-AI083-009 | T-001 | backend/app/surge_config/surge_detection.yaml, backend/tests/test_surge_ai083_intraday_rescan.py | pending |
| T-007 | 공통 불변 회귀 가드: 탐지 본체/앙상블/유니버스/15:20 배치 크론/평가 지평/BUY_CUTOFF/매매 diff 0, 비활성 매수·청산 잡 미복구, execute_signal_trade 미호출 | REQ-AI083-006, REQ-AI083-010, REQ-AI083-011, REQ-AI083-012 | T-003..T-006 | backend/tests/test_surge_ai083_intraday_rescan.py | pending |
| T-008 | 관측성·근거 문서화: 재스캔 간격/시각 근거(gather 소요·크롤 부하) 확정, 잡 등록 지점 @MX:NOTE(+@MX:SPEC) 기록 | REQ-AI083-013 | T-003 | backend/app/services/scheduler.py | pending |
| T-009 | 전체 회귀: SPEC-AI-080/082 인접 테스트 + 전체 스위트(기본 + -n 4) + ruff/mypy 무회귀 | REQ-AI083-006 (전 REQ) | T-002..T-008 | (검증만, 파일 변경 없음) | pending |

Planned new files: `backend/tests/test_surge_ai083_intraday_rescan.py`
Planned modified files: `backend/app/services/scheduler.py`, `backend/app/services/fund_manager.py`, `backend/app/surge_config/surge_detection.yaml`

Notes:
- DDD ANALYZE-PRESERVE-IMPROVE + Reproduction-First(Rule 4): T-002(RED) → T-003/T-004(GREEN) 순서 준수.
- 신규 테이블/마이그레이션 없음. same-day 귀속은 기존 surge_metadata(JSON) + SPEC-AI-080 평가 경로 재사용.
- [HARD] 전제 정정(immediate_surge 이미 활성 / surge_check_exits 비활성)과 방향 B 재범위화 → 사용자 확인 완료(2026-07-21): REQ-AI083-008(뉴스 재스캔 활성화) 포함(권장안) 승인. 방향 B 범위 확정, Run 착수 가능.
- T-006이 REQ-AI083-008(event_rescan_enabled false→true) + REQ-AI083-009(가드 준수)를 커버하며, 확정 범위이므로 조건부가 아닌 정식 Run 대상이다. 뉴스 트리거 정밀도 미검증 리스크(spec.md [R-3])는 활성화 후 관측으로 사후 검증.
