from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from job_bot.db.job_models import Job
from job_bot.job_providers.greenhouse_job_provider import GreenHouseJobProvider
from job_bot.job_providers.job_provider import JobProvider
from job_bot.schemas import JobEntrySchema


def _record() -> Job:
    return Job(
        source="greenhouse",
        job_title="Software Engineer",
        url="https://job-boards.greenhouse.io/example/jobs/123",
        company_name="Example Corp",
        job_location="Remote",
        jd_summary="Build reliable systems.",
        date_posted=datetime(2026, 7, 24, 12, 30, tzinfo=UTC),
    )


def test_job_provider_is_abstract() -> None:
    with pytest.raises(TypeError):
        JobProvider()


def test_greenhouse_provider_queries_persisted_greenhouse_jobs() -> None:
    session = Mock()
    session.execute.return_value.scalars.return_value.all.return_value = [_record()]

    jobs = GreenHouseJobProvider(session).provide()

    assert len(jobs) == 1
    assert isinstance(jobs[0], JobEntrySchema)
    assert jobs[0].job_title == "Software Engineer"
    assert jobs[0].company_name == "Example Corp"
    statement = session.execute.call_args.args[0]
    assert "jobs.source =" in str(statement)
