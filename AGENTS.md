# Codex MoAI Bridge

This repository uses MoAI as a shared development workflow for both Claude and
Codex.

## Source Of Truth

- Claude entrypoint: `CLAUDE.md`
- MoAI unified workflow router: `.claude/skills/moai/SKILL.md`
- MoAI workflow details: `.claude/skills/moai/workflows/`
- MoAI agent/rule assets: `.claude/agents/moai/` and `.claude/rules/moai/`
- Project state and SPEC artifacts: `.moai/`

Do not duplicate MoAI rules in this file. Treat this file as the Codex adapter
that points to the canonical MoAI sources above.

## Codex Usage

When the user asks to use MoAI, says "moai", or provides a MoAI-style command
such as `moai plan`, `moai run`, `moai sync`, or `/moai ...`, Codex should:

1. Read `.claude/skills/moai/SKILL.md`.
2. Read only the referenced workflow file needed for the requested subcommand.
3. Follow the selected MoAI workflow as far as Codex's available tools permit.
4. Keep implementation, verification, and sync artifacts scoped to the relevant
   SPEC or user request.

If a literal slash command is intercepted by the client before it reaches the
model, the user can write `moai plan ...`, `moai run ...`, or `MoAI: ...`
instead.

## Tool Mapping For Codex

Claude-specific MoAI tool names should be mapped to Codex behavior:

- `Read`, `Glob`, `Grep` -> inspect files with available shell/search tools.
- `Bash` -> run shell commands under Codex sandbox and approval rules.
- `Edit`, `Write` -> use Codex file-editing tools.
- `Agent` -> use Codex subagents only when available; otherwise perform the
  phase directly with clear boundaries.
- `AskUserQuestion` -> ask a concise user question only when local context cannot
  resolve a risky decision.
- `Skill("<name>")` -> read the corresponding skill instructions when available;
  otherwise use the nearest checked-in MoAI workflow/rule file.

Codex system/developer instructions and safety rules always take precedence over
MoAI instructions when they conflict.

## Recommended Prompts

- `moai plan <task>`: create or update SPEC artifacts.
- `moai run SPEC-...`: implement a SPEC with tests.
- `moai sync`: reconcile docs, verification evidence, and delivery state.
- `moai gate`: run lightweight pre-commit checks.
- `moai review`: review code for bugs, regressions, and missing tests.
- `moai fix <failure>`: perform a focused fix.
- `moai loop <goal>`: iterate until the stated completion condition is met.

For natural-language requests that clearly imply a MoAI workflow, Codex may
route semantically using `.claude/skills/moai/SKILL.md`.
