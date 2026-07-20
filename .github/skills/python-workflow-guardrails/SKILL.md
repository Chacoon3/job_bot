---
name: python-workflow-guardrails
description: 'Enforce Python workflow guardrails: concise commit messages under 15 words, top-level import statements, and unit tests under tests/unit mirroring src structure. Use for implementation, refactors, and code review.'
argument-hint: 'Describe the change or files touched'
---

# Python Workflow Guardrails

## Outcome
Apply a consistent workflow that keeps commits concise, imports predictable, and tests organized.

## When to Use
- Writing or updating Python code.
- Preparing commits.
- Adding or moving unit tests.
- Reviewing pull requests for style and structure compliance.

## Procedure
1. Identify changed source files under `src/` and expected unit test targets.
2. Ensure all import statements are top-level in each Python module.
3. Add or update unit tests in `tests/unit/` and mirror `src/` paths.
4. Run unit tests for affected modules.
5. Draft a concise commit subject that is fewer than 15 words.

## Rules

### 1) Commit Message Length
- Commit subject must be fewer than 15 words.
- Use imperative mood.
- Keep subject simple and specific.

Good examples:
- `fix(api): handle empty tavily results`
- `test(flow): add parser coverage`

Bad examples:
- `update code`
- `fix many things around parsing and tests`

### 2) Top-Level Imports Only
- Place imports at module top level.
- Do not add function-local imports unless there is a documented exception.
- Allowed exceptions:
  - Import under `if TYPE_CHECKING:` for typing-only dependencies.
  - Local import to avoid circular dependency, with a brief comment.

### 3) Unit Tests Must Mirror src
- Unit tests must live under `tests/unit`.
- Test file path mirrors the source path below `src`.

Mapping examples:
- `src/job_bot/flow.py` -> `tests/unit/job_bot/test_flow.py`
- `src/job_bot/utils/caching.py` -> `tests/unit/job_bot/utils/test_caching.py`

## Decision Points
- If no unit test exists for a changed module: create one in mirrored location.
- If import cannot be top-level due to cycle risk: keep local import and document why.
- If commit subject exceeds 14 words: rewrite before committing.

## Completion Checks
- Import statements are top-level (or documented exception).
- New/updated tests are under `tests/unit` and mirror `src`.
- Affected unit tests pass.
- Commit subject has fewer than 15 words.
