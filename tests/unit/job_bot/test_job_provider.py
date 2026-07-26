from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from sqlalchemy.dialects.postgresql import Range

from job_bot.db.job_models import JobEntryRecord
from job_bot.job_provider import GreenHouseJobProvider, JobProvider


def _record() -> JobEntryRecord:
    return JobEntryRecord(
        id=1,
        source="greenhouse",
        job_title="Software Engineer",
        url="https://job-boards.greenhouse.io/example/jobs/123",
        year_of_experience=Range(0, 1, bounds="[)"),
        company_name="Example Corp",
        job_location="Remote",
        jd_summary="Build reliable systems.",
        pay_range=Range(0, 1, bounds="[)"),
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
    assert jobs[0].job_title == "Software Engineer"
    assert jobs[0].company_name == "Example Corp"
    assert jobs[0].year_of_experience == Range(0, 1, bounds="[)")
    assert jobs[0].pay_range == Range(0, 1, bounds="[)")
    statement = session.execute.call_args.args[0]
    assert "job_entries.source =" in str(statement)
