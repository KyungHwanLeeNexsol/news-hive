---
name: project-surge-spec-conventions
description: House style for SPEC-AI-### documents in news-hive surge-trading domain (structure, EARS bilingual mix, fact-checking discipline)
metadata:
  type: project
---

SPEC-AI-### documents in news-hive follow a consistent house style established by SPEC-AI-029 and continued in SPEC-AI-034. Match it when writing new surge-trading SPECs.

**Why:** The user maintains a tight, fact-grounded SPEC format. Drifting from it (e.g. inventing field names, omitting fact-check callouts) produces SPECs that don't match the codebase and waste the Run phase.

**How to apply:**
- Section order: frontmatter → `# SPEC-AI-NNN: 한글제목 (English Title)` → `## HISTORY` → `## 선행 SPEC (전제 조건 / Assumptions)` → `## Overview` → `## 설계 원칙 (Design Principles)` → `## EARS Requirements` (REQ-AINNN-NNN ids) → data model / migration spec if any → `## Implementation Scope` (table) → `## Acceptance Criteria` (AC-NNN-NN table, pytest verification column) → `## Non-Goals (What NOT to Build)` → `## References` (코드 위치 + 데이터 모델 사실 확인 + 선행 SPEC).
- Body text is Korean; code identifiers, EARS keywords (shall/when/where/if/while), and the actual REQ requirement sentences are English. Frontmatter `author: MoAI`, `version` starts `0.1.0`, `status: draft`.
- Embed `[HARD] 사실 확인` callouts in the Assumptions section for anything verified against code (exact field names, enum value ranges, file/line locations). The user values these — they prevent the Run phase from coding against wrong assumptions (e.g. SPEC-AI-029 flagged that MarketRegimeEnum has no VOLATILE value).
- Acceptance criteria always end with a "기존 회귀 테스트 전체 통과: `cd backend && uv run pytest tests/ -m "not slow"`" row.
- Non-Goals must be explicit and plural; the user scopes SPECs tightly (read-only vs. write, no ML, no migrations unless stated).
- Output path is the directory form `.moai/specs/SPEC-AI-NNN/spec.md` (never a flat file). When the user asks only for spec.md, produce just that file.

Related: [[project-surge-data-model]]