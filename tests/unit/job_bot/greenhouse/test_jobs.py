from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock

import httpx

from job_bot.db.greenhouse_models import GreenhouseBoard
from job_bot.greenhouse.jobs import GreenhouseJobSyncService, _parse_datetime


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
                        "updated_at": "2026-07-24T12:30:00Z",
                    }
                ]
            },
        )

    session = Mock()
    session.execute.return_value.scalars.return_value.all.return_value = [_board()]
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = GreenhouseJobSyncService(session, client=client).sync()

    assert result.boards_queried == 1
    assert result.boards_failed == 0
    assert result.jobs_found == 1
    assert result.jobs_stored == 1
    assert requests[0].url.params["content"] == "true"
    insert_statement = session.execute.call_args_list[1].args[0]
    assert "ON CONFLICT (url) DO UPDATE" in str(insert_statement)
    assert "greenhouse" in insert_statement.compile().params.values()


def test_parse_datetime_accepts_iso8601_and_epochs() -> None:
    assert _parse_datetime("2026-07-24T12:30:00Z") == datetime(2026, 7, 24, 12, 30, tzinfo=UTC)
    assert _parse_datetime(1753360200) == datetime(2025, 7, 24, 12, 30, tzinfo=UTC)
    assert _parse_datetime("1753360200000") == datetime(2025, 7, 24, 12, 30, tzinfo=UTC)


def test_parse_datetime_returns_none_for_invalid_values() -> None:
    assert _parse_datetime(None) is None
    assert _parse_datetime("") is None
    assert _parse_datetime("not-a-datetime") is None
