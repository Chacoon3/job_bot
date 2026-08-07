from __future__ import annotations

from unittest.mock import Mock

import httpx

from job_bot.greenhouse.jobs import GreenhouseJobSyncService


def test_pull_company_job_entries_uses_greenhouse_api_and_generic_transform() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "title": "Software Engineer",
                        "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/123",
                    },
                    {
                        "title": "Data Engineer",
                        "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/456",
                    },
                ]
            },
        )

    session = Mock()
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        titles = GreenhouseJobSyncService(session, client=client).pull_company_job_entries(
            "acme",
            client=client,
            transform=lambda raw_job: raw_job["title"],
        )

    assert titles == ["Software Engineer", "Data Engineer"]
    assert requests[0].url.path.endswith("/v1/boards/acme/jobs")
    assert requests[0].url.params["content"] == "true"
