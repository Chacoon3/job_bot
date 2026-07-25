from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock

import httpx
import pytest

from job_bot.db.greenhouse_models import GreenhouseBoard
from job_bot.job_provider import GreenHouseJobProvider, JobProvider


def _board() -> GreenhouseBoard:
    return GreenhouseBoard(
        id=1,
        token="example",
        company_name="Example Corp",
        board_url="https://job-boards.greenhouse.io/example",
        api_url="https://boards-api.greenhouse.io/v1/boards/example/jobs",
        active_job_count=2,
        sample_job_titles=[],
        discovered_urls=[],
        crawl_indexes=[],
        verified_at=datetime(2026, 7, 25, tzinfo=UTC),
        created_at=datetime(2026, 7, 25, tzinfo=UTC),
        updated_at=datetime(2026, 7, 25, tzinfo=UTC),
    )


def _session_with_boards(*boards: GreenhouseBoard) -> Mock:
    session = Mock()
    session.execute.return_value.scalars.return_value.all.return_value = list(boards)
    return session


def test_job_provider_is_abstract() -> None:
    with pytest.raises(TypeError):
        JobProvider()


def test_greenhouse_provider_queries_active_boards_and_maps_jobs() -> None:
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

    session = _session_with_boards(_board())
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        jobs = GreenHouseJobProvider(session, client=client).provide()

    assert len(jobs) == 1
    assert jobs[0].job_title == "Software Engineer"
    assert jobs[0].company_name == "Example Corp"
    assert jobs[0].job_location == "Remote"
    assert jobs[0].jd_summary == "Build reliable systems."
    assert jobs[0].date_posted == datetime(2026, 7, 24, 12, 30, tzinfo=UTC)
    assert jobs[0].year_of_experience.minimum == 0
    assert jobs[0].pay_range.minimum == 0
    assert requests[0].url.params["content"] == "true"

    statement = session.execute.call_args.args[0]
    assert "greenhouse_boards.active_job_count >" in str(statement)


def test_greenhouse_provider_skips_failed_board_requests() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        jobs = GreenHouseJobProvider(
            _session_with_boards(_board()),
            client=client,
        ).provide()

    assert jobs == []
