# SPEC-AI-109 Acceptance

| AC ID | Requirement | Check |
| --- | --- | --- |
| AC-109-001 | REQ-AI109-001 | `test_repair_collects_missing_actual_then_evaluates` |
| AC-109-002 | REQ-AI109-001 | `test_repair_skips_evaluation_when_actual_collection_still_empty` |
| AC-109-003 | REQ-AI109-001 | `test_repair_skips_historical_actual_collection_by_default` |
| AC-109-004 | REQ-AI109-001 | `test_repair_noops_when_records_already_complete` |
| AC-109-005 | REQ-AI109-002 | `test_scheduler_missing_monitor_attempts_repair` |
| AC-109-006 | REQ-AI109-003 | `TestEvaluationBackfill::test_requires_admin` |
| AC-109-007 | REQ-AI109-003 | `TestEvaluationBackfill::test_runs_backfill_for_business_date_range` |
