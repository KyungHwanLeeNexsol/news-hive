# SPEC-AI-115 Acceptance Criteria

Status: implemented

### AC-115-001

Given candidates dropped by each major gate, when detection/evaluation runs, then a drop observation
exists with stock code, date, score or metric, gate name, and reason metadata.

Status: implemented. Covered by `tests/test_spec_ai_115.py` detection/evaluation observation tests.

### AC-115-002

Given observation persistence fails, when candidate generation runs, then official signal generation
continues and the failure is logged.

Status: implemented. Covered by fail-open persistence test.

### AC-115-003

Given drop observation wiring is enabled, when the same fixture is run before and after the change,
then official qualified candidate code sets are identical.

Status: implemented. Official output fixture remains `["115101"]` with observation enabled.

### AC-115-004

Given shadow relaxed gate mode is enabled, when detection runs, then shadow-added candidates are
reported but no `surge_candidate` `FundSignal` rows are emitted from shadow output.

Status: implemented. Shadow candidates are persisted only as `SurgeGateDropObservation` rows.

### AC-115-005

Given at least 10 eligible evaluation days, when the shadow report runs, then it ranks relaxed
profiles by recall gain and added false positives.

Status: implemented. Covered by `generate_gate_drop_shadow_report()` GO ranking test.

### AC-115-006

Given a relaxed profile doubles candidate count without sufficient precision evidence, then the
guardrail report returns NO-GO.

Status: implemented. Covered by candidate inflation NO-GO test.
