---
name: python-workflow-guardrails
description: 'Write and maintain Python unit tests that mirror src structure, and triage failures between source defects and outdated tests. Use when writing tests, fixing pytest failures, or validating refactors.'
argument-hint: 'Describe the source file or failing test'
---

# Python Workflow Guardrails

## Outcome
Produce reliable unit tests that mirror the source layout and resolve failures by fixing the correct side: source code or test code.

## When to Use
- Writing new unit tests.
- Updating tests after refactors or behavior changes.
- Investigating pytest failures.
- Reviewing whether tests still align with current source behavior.

## Procedure
0. For Python usage, default to use the ./.venv virtual environment unless otherwise necessary.
1. Identify the target source module under `src/`.
2. Map it to a mirrored unit test path under `tests/unit/`.
3. Create or update the test module for the mapped path.
4. Run affected tests first, then broader unit tests as needed.
5. If tests fail, triage whether the source behavior is wrong or the test expectation is outdated.
6. Apply the fix on the correct side (source or test), then rerun tests.

## Rules

### 1) Unit Tests Must Mirror src
- Unit tests must live under `tests/unit`.
- Directory path must mirror the source path below `src`.
- Use pytest-style test module names with a `test_` prefix.

Mapping examples:
- `src/app/mod.py` -> `tests/unit/app/test_mod.py`
- `src/job_bot/utils/caching.py` -> `tests/unit/job_bot/utils/test_caching.py`

### 2) Failure Triage Must Choose the Correct Fix
- If the source implementation violates intended behavior: fix source code.
- If the source behavior is correct and intentional but test expectations are stale: update tests.
- Do not force source changes just to satisfy outdated tests.
- Do not update tests to codify incorrect source behavior.

## Decision Points
- If no unit test exists for a changed module: create one at the mirrored test path.
- If a failure reproduces a real bug or contract violation: fix source first, then verify tests.
- If a failure reflects an intentional source change: align the test with current behavior.
- If root cause is unclear: reproduce with a minimal targeted test and inspect implementation before editing expectations.

## Completion Checks
- New or updated tests are under `tests/unit`, mirror source directories, and use `test_*.py` filenames.
- The chosen fix matches root cause (source defect vs outdated test).
- Affected unit tests pass locally.
- No failing assertion remains that conflicts with intended source behavior.
