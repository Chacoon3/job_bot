---
name: concise-commit-message
description: 'Generate concise Git commit messages. Use when drafting, reviewing, or suggesting a commit message, including Conventional Commit types, commit subjects, and commit bodies.'
argument-hint: 'Describe the change being committed'
---

# Concise Commit Message

## Outcome
Produce a clear commit message whose items use the required bracketed type format and whose complete text has at most 30 words.

## When to Use
- Drafting a Git commit message.
- Reviewing or rewriting a proposed commit message.
- Summarizing staged or completed changes for a commit.

## Procedure
1. Identify the primary change and any separate, non-obvious supporting changes.
2. Choose a conventional type that describes each change: `feat`, `fix`, `test`, `docs`, `refactor`, `perf`, `build`, `ci`, `chore`, `devops`, or `revert`.
3. Write every commit-message item in this exact form:

	```text
	[<type>]: <imperative, specific summary>
	```

4. Use one item for a focused change. Add a separate item only when it communicates a distinct, necessary change.
5. Count all words in the complete message. Rewrite until it contains 30 words or fewer.
6. Check the repository commit instructions: keep the subject under 30 characters, do not end it with a period, and include a body only for non-obvious changes.

## Rules
- Every item starts with a bracketed type followed by a colon and a space.
- Use imperative mood and concrete language.
- Keep the complete commit message to 30 words or fewer.
- Do not use vague summaries such as `update code` or `fix stuff`.
- Prefer a standard conventional type. Use `devops` for infrastructure, deployment, or operational changes when no more specific type fits.
- The first item is the subject and must also satisfy the repository's under-30-character subject limit.

## Examples

Good:

```text
[feat]: add job search endpoint
```

```text
[test]: cover empty job results
```

```text
[devops]: update container healthcheck
```

Bad:

```text
feat: add job search endpoint
```

```text
[fix] handle errors
```

```text
[chore]: update code
```

## Completion Checks
- Every item matches `[<type>]: <message>`.
- Each type accurately describes its change.
- The complete message contains 30 words or fewer.
- The subject is imperative, specific, has no trailing period, and is under 30 characters.
