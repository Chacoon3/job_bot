# Current status (for human read only)

## Current goal

- complete llm infer application result
- implement job finder to find more jobs to apply

## Current stopping point

- implement the filler logic

## Next action


## Blockers / decisions


## Code Review

Critical: one User model serves persistence, LLM input, and API output.
UserResponse nests the full User, including resume_text, address, demographics, work authorization, and phone data ([schemas.py (line 202)](C:/Users/zizh3/source/repos/job_bot/src/job_bot/data/schemas.py:202), [schemas.py (line 287)](C:/Users/zizh3/source/repos/job_bot/src/job_bot/data/schemas.py:287)). Split it into UserProfileInput, UserProfileStored, and a deliberately minimal UserResponse; never return resume text by default.

High: unsafe semantic defaults can cause incorrect job applications.
The core User defaults work authorization, sponsorship, relocation, race, disability, and veteran status to substantive values such as "yes" and "asian" ([schemas.py (line 248)](C:/Users/zizh3/source/repos/job_bot/src/job_bot/data/schemas.py:248)). Missing data must mean null/"decline"/"unknown", not an affirmative answer.

High: versioning is inconsistent and legacy endpoints remain public.
Routes coexist under /api, /apiv1, and /apiv2 ([api_v1.py (line 75)](C:/Users/zizh3/source/repos/job_bot/src/job_bot/api/api_v1.py:75), [api_v2.py (line 22)](C:/Users/zizh3/source/repos/job_bot/src/job_bot/api/api_v2.py:22), [user_api.py (line 32)](C:/Users/zizh3/source/repos/job_bot/src/job_bot/api/user_api.py:32)). Standardize on /api/v1/..., deprecate legacy handlers, and avoid both old and new contracts appearing in one OpenAPI document.

High: documented response shapes do not match runtime behavior.
The legacy apply endpoints declare ApplicationStatus but return {"error": ...} on validation paths, which cannot satisfy the declared schema and can become a 500 response ([api_v1.py (line 160)](C:/Users/zizh3/source/repos/job_bot/src/job_bot/api/api_v1.py:160)). The legacy profile endpoint similarly documents an arbitrary string map and calls a nonexistent User.from_document method ([api_v1.py (line 138)](C:/Users/zizh3/source/repos/job_bot/src/job_bot/api/api_v1.py:138)). Remove or repair these routes before clients adopt them.

High: error contract is absent from OpenAPI.
For example, /apiv2/job/apply can return 400, 404, 409, and 503, but the generated spec only advertises 200 and 422 ([api_v2.py (line 135)](C:/Users/zizh3/source/repos/job_bot/src/job_bot/api/api_v2.py:135)). Define a shared ProblemDetail schema and explicitly register expected responses.

Medium: resource identifiers and method semantics should improve.
User read/update/delete uses email in the URL ([user_api.py (line 227)](C:/Users/zizh3/source/repos/job_bot/src/job_bot/api/user_api.py:227)). Use the immutable UUID already returned as user_id; email in paths leaks into logs, caches, and telemetry. Also, POST /apiv1/user silently upserts, despite returning 201; either make it a true create with 409, or document it as an idempotent PUT.

Medium: domain types are too permissive.
Job and board URLs, provider/source, strings, and counts are largely unconstrained ([schemas.py (line 30)](C:/Users/zizh3/source/repos/job_bot/src/job_bot/data/schemas.py:30), [schemas.py (line 74)](C:/Users/zizh3/source/repos/job_bot/src/job_bot/data/schemas.py:74)). Use HttpUrl/validated URL types, bounded strings, an enum for known sources, non-negative counts, and explicit timezone-aware timestamp requirements.

Medium: discovery config exposes operational controls as public request fields.
/api/boards/discover accepts concurrency, host lists, crawl counts, and up to 100,000 results ([greenhouse_api.py (line 97)](C:/Users/zizh3/source/repos/job_bot/src/job_bot/api/greenhouse_api.py:97), [models.py (line 57)](C:/Users/zizh3/source/repos/job_bot/src/job_bot/greenhouse/models.py:57)). Separate a small client-facing DiscoveryRequest from internal worker configuration; return an asynchronous job/resource rather than holding an HTTP request open.