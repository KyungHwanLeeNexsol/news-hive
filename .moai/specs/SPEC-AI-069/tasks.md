## Task Decomposition
SPEC: SPEC-AI-069

| Task ID | Description | Requirement | Dependencies | Planned Files | Status |
|---------|-------------|-------------|--------------|---------------|--------|
| T-001 | 자동개선 중단 flag(`auto_improve_enabled`, 기본 false) 추가 + `analyze_and_improve` 게이팅 | REQ-002 | - | backend/app/surge_config/surge_settings.py, backend/app/surge_config/surge_detection.yaml, backend/app/services/surge_auto_improver.py | completed |
| T-002 | auto.yaml 기본값 리셋 메커니즘(`reset_auto_yaml_to_base` — 파일 전체 비우기, 하드코딩 없음, startup 1회 idempotent) | REQ-002 (D4) | T-001 | backend/app/services/surge_auto_improver.py 또는 surge_settings.py, backend/app/main.py(startup 훅) | completed |
| T-003 | z-score 회귀 flag 격리(`relative_scoring.zscore_enabled` 기본 false) — surge_detector.py:2011-2016 setattr 게이팅 | REQ-004 (D3) | T-002 | backend/app/services/surge_detector.py, backend/app/surge_config/surge_settings.py, backend/app/surge_config/surge_detection.yaml | completed |
| T-004 | backtest 판정·영속화 로직(`run_backtest_gate` — pass/fail/insufficient verdict) | REQ-001 | - | backend/app/services/surge_backtest.py, backend/app/surge_config/surge_detection.yaml(backtest.gate 서브섹션) | completed |
| T-005 | Alembic 마이그레이션 066(surge_backtest_result 테이블) + 모델 | REQ-001 | T-004 | backend/app/models/surge_backtest_result.py(신규), backend/alembic/versions/066_surge_backtest_result.py(신규), backend/app/models/__init__.py | completed |
| T-006 | 스케줄러 backtest cron 잡 편입(18:45 KST, mon-fri, distinct id) | REQ-001 | T-004, T-005 | backend/app/services/scheduler.py | completed |
| T-007 | `analyze_and_improve`가 today_eval.scannable_recall(SPEC-AI-068)을 명시적으로 참조하도록 재타겟팅, null이면 조정 스킵 | REQ-003 | T-001 | backend/app/services/surge_auto_improver.py | completed |
| T-008 | backtest verdict != pass 시 모든 `_write_auto_yaml` 호출 스킵하는 가드 삽입 | REQ-003 | T-004, T-005, T-006, T-001 | backend/app/services/surge_auto_improver.py | completed |
| T-009 | calibrator 무효 상태(identity fallback) 표면화 — 로그/리포트 명시, (b) 명시적 해제+문서화 | REQ-005 | - | backend/app/services/surge_calibrator.py, backend/app/services/surge_auto_improver.py(리포트), backend/app/services/fund_manager.py(1385행 주변) | completed |
| T-010 | 회귀·품질 게이트 (전체 스위트, ruff/mypy, 예측기록 모드 불변, DoD 체크) | DoD 전체 | T-001~T-009 | 검증 전용(코드 수정 없음) | completed |

Dependency graph: T-001 → T-002 → T-003 (M1, 순차); T-004 → T-005 → T-006 (M2, 독립 시작 가능); T-007(← T-001), T-008(← T-004,005,006,001) (M3, SPEC-AI-068 완료로 unblocked); T-009 (M4, 독립 병렬 가능); T-010 (M5, 전체 의존)

Decisions confirmed by user (2026-07-02, 2차 재개):
- Plan approved as-is (M1→M2→M3→M4→M5 order).
- Backtest cron slot: 18:45 KST (between 18:30 eval jobs and 19:00 auto-improve job).
- Calibrator direction: (b) explicit disconnect + documentation (not (a) add training job).
- auto.yaml reset mechanism: empty the override file entirely (base yaml authoritative, no per-key hardcoding).

Corrections found by manager-strategy during ANALYZE (must respect in IMPROVE):
- base `surge_detection.yaml` legacy_detectors weight is already 0.00 — "restore" means confirming it stays 0.00, not restoring to a nonzero value.
- SPEC-AI-068 already transitions `recall` column to `scannable_recall` when universe exists — REQ-003's real change is auto_improver reading `today_eval.scannable_recall` explicitly (not the generic `.recall`).
- Migration number is 066 (065 was consumed by SPEC-AI-068), down_revision=065_surge_universe_members.
