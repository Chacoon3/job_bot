from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import httpx

from job_bot.db.greenhouse_models import GreenhouseBoard
from job_bot.db.job_models import Job
from job_bot.greenhouse.jobs import (
    GreenhouseBoardSyncPolicy,
    GreenhouseJobSyncService,
    _parse_datetime,
)
from job_bot.job_providers.greenhouse_job_provider import GREENHOUSE_SOURCE


def _board() -> GreenhouseBoard:
    return GreenhouseBoard(
        id=1,
        token="example",
        company_name="Example Corp",
        board_url="https://job-boards.greenhouse.io/example",
        api_url="https://boards-api.greenhouse.io/v1/boards/example/jobs",
        active_job_count=1,
        sample_job_titles=[],
        discovered_urls=[],
        crawl_indexes=[],
        verified_at=datetime(2026, 7, 25, tzinfo=UTC),
        created_at=datetime(2026, 7, 25, tzinfo=UTC),
        updated_at=datetime(2026, 7, 25, tzinfo=UTC),
    )


def test_sync_fetches_and_upserts_greenhouse_jobs() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "title": "Software Engineer",
                        "absolute_url": "https://job-boards.greenhouse.io/example/jobs/123",
                        "location": {"name": "Remote"},
                        "content": "<p>Build reliable systems.</p>",
                        "updated_at": datetime.now(UTC).isoformat(),
                    }
                ]
            },
        )

    session = AsyncMock()
    session.execute.return_value = Mock()
    session.execute.return_value.scalars.return_value.all.return_value = [_board()]
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = asyncio.run(GreenhouseJobSyncService(session, client=client).sync())

    assert result.boards_queried == 1
    assert result.boards_failed == 0
    assert result.jobs_found == 1
    assert result.jobs_stored == 1
    assert requests[0].url.params["content"] == "true"
    insert_statement = session.execute.call_args_list[1].args[0]
    assert "ON CONFLICT (url) DO UPDATE" in str(insert_statement)
    assert "greenhouse" in insert_statement.compile().params.values()


def test_sync_applies_board_policy_and_limit() -> None:
    session = AsyncMock()
    session.execute.return_value = Mock()
    session.execute.return_value.scalars.return_value.all.return_value = []

    asyncio.run(
        GreenhouseJobSyncService(session, client=Mock()).sync(
            policy=GreenhouseBoardSyncPolicy.MOST_JOBS,
            board_limit=5,
        )
    )

    select_statement = session.execute.call_args.args[0]
    compiled = str(select_statement.compile(compile_kwargs={"literal_binds": True}))
    assert "active_job_count DESC" in compiled
    assert "LIMIT 5" in compiled


def test_sync_rejects_non_positive_board_limit() -> None:
    session = AsyncMock()

    try:
        asyncio.run(GreenhouseJobSyncService(session, client=Mock()).sync(board_limit=0))
    except ValueError as exc:
        assert str(exc) == "board_limit must be at least 1"
    else:
        raise AssertionError("Expected a non-positive board limit to be rejected")


def test_sync_filters_old_undated_and_keyword_mismatched_jobs() -> None:
    now = datetime.now(UTC)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "title": "Senior Python Engineer",
                        "absolute_url": "https://example.com/jobs/recent",
                        "content": "<p>Build APIs. No staffing agencies.</p>",
                        "updated_at": (now - timedelta(days=5)).isoformat(),
                    },
                    {
                        "title": "Senior Python Engineer",
                        "absolute_url": "https://example.com/jobs/old",
                        "updated_at": (now - timedelta(days=31)).isoformat(),
                    },
                    {
                        "title": "Senior Python Engineer",
                        "absolute_url": "https://example.com/jobs/undated",
                    },
                    {
                        "title": "Java Engineer",
                        "absolute_url": "https://example.com/jobs/java",
                        "updated_at": now.isoformat(),
                    },
                ]
            },
        )

    session = AsyncMock()
    session.execute.return_value = Mock()
    session.execute.return_value.scalars.return_value.all.return_value = [_board()]
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = asyncio.run(
            GreenhouseJobSyncService(session, client=client).sync(
                include_keywords=["PYTHON"],
                exclude_keywords=["staffing"],
            )
        )

    assert result.jobs_found == 0
    assert result.jobs_stored == 0
    assert session.execute.call_count == 1


def test_keyword_filter_matches_any_include_and_prioritizes_exclusions() -> None:
    job = Job(
        source=GREENHOUSE_SOURCE,
        job_title="Senior Python Engineer",
        url="https://example.com/jobs/1",
        company_name="Example Corp",
        job_location="Remote",
        jd_summary="Build distributed APIs.",
    )

    assert GreenhouseJobSyncService._matches_keywords(
        job,
        include_keywords=["rust", "PYTHON"],
        exclude_keywords=[],
    )
    assert not GreenhouseJobSyncService._matches_keywords(
        job,
        include_keywords=["python"],
        exclude_keywords=["distributed"],
    )


def test_positive_keywords_only_match_job_title() -> None:
    job = Job(
        source=GREENHOUSE_SOURCE,
        job_title="Product Manager",
        url="https://example.com/jobs/2",
        company_name="Software Industries",
        job_location="Remote",
        jd_summary="Partner with engineers and developers.",
    )

    assert not GreenhouseJobSyncService._matches_keywords(
        job,
        include_keywords=["software", "engineer", "developer"],
        exclude_keywords=[],
    )

    job.job_title = "Software Product Manager"
    assert GreenhouseJobSyncService._matches_keywords(
        job,
        include_keywords=["software", "engineer", "developer"],
        exclude_keywords=[],
    )


def test_upsert_jobs_batches_large_syncs() -> None:
    session = AsyncMock()
    batch_size = 5_000
    jobs = [
        Job(
            source=GREENHOUSE_SOURCE,
            job_title=f"Engineer {index}",
            url=f"https://example.com/jobs/{index}",
            company_name="Example Corp",
            job_location="Remote",
            jd_summary="Build systems.",
        )
        for index in range(batch_size + 1)
    ]

    jobs_stored = asyncio.run(GreenhouseJobSyncService(session, client=Mock())._upsert_jobs(jobs))

    assert jobs_stored == len(jobs)
    assert session.execute.call_count == 2
    batch_sizes = [
        # The seven explicit values plus Job.job_id's generated UUID bind.
        len(call.args[0].compile().params) // 8
        for call in session.execute.call_args_list
    ]
    assert batch_sizes == [batch_size, 1]


def test_parse_datetime_accepts_iso8601_and_epochs() -> None:
    assert _parse_datetime("2026-07-24T12:30:00Z") == datetime(2026, 7, 24, 12, 30, tzinfo=UTC)
    assert _parse_datetime(1753360200) == datetime(2025, 7, 24, 12, 30, tzinfo=UTC)
    assert _parse_datetime("1753360200000") == datetime(2025, 7, 24, 12, 30, tzinfo=UTC)


def test_parse_datetime_returns_none_for_invalid_values() -> None:
    assert _parse_datetime(None) is None
    assert _parse_datetime("") is None
    assert _parse_datetime("not-a-datetime") is None
