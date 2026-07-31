from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects.postgresql import Range

from job_bot.db.greenhouse_models import GreenhouseBoard
from job_bot.db.job_models import JobEntry
from job_bot.schemas import CandidateProfile, GreenhouseBoardSchema, JobEntrySchema


def test_job_entry_schema_round_trips_orm_ranges() -> None:
    orm_job = JobEntry(
        id=1,
        source="greenhouse",
        job_title="Software Engineer",
        url="https://example.com/jobs/123",
        year_of_experience=Range(2, 5, bounds="[]"),
        company_name="Example Corp",
        job_location="Remote",
        jd_summary="Build systems",
        pay_range=Range(120_000, 160_000, bounds="[]"),
        date_posted=datetime(2026, 7, 25, tzinfo=UTC),
    )

    schema = JobEntrySchema.from_orm_model(orm_job)
    restored = schema.to_orm_model()

    assert schema.year_of_experience_minimum == 2
    assert schema.year_of_experience_maximum == 5
    assert schema.pay_range_minimum == 120_000
    assert schema.pay_range_maximum == 160_000
    assert restored.year_of_experience == Range(2, 5, bounds="[]")
    assert restored.pay_range == Range(120_000, 160_000, bounds="[]")


def test_greenhouse_board_schema_reads_orm_attributes() -> None:
    timestamp = datetime(2026, 7, 25, tzinfo=UTC)
    board = GreenhouseBoard(
        id=1,
        token="example",
        company_name="Example Corp",
        board_url="https://job-boards.greenhouse.io/example",
        api_url="https://boards-api.greenhouse.io/v1/boards/example/jobs",
        active_job_count=2,
        sample_job_titles=["Software Engineer"],
        discovered_urls=["https://example.com"],
        crawl_indexes=["CC-MAIN-2026-30"],
        verified_at=timestamp,
        created_at=timestamp,
        updated_at=timestamp,
    )

    schema = GreenhouseBoardSchema.from_orm_model(board)

    assert schema.token == "example"
    assert schema.active_job_count == 2
    assert schema.model_dump(mode="json")["verified_at"] == timestamp.isoformat().replace(
        "+00:00", "Z"
    )


def test_candidate_profile_uses_canonical_dropdown_options() -> None:
    profile = CandidateProfile(
        first_name="Alex",
        last_name="Doe",
        email="alex@example.com",
        phone_country="+1",
        phone="555-0100",
        gender="nonbinary",
        education=[],
        resume_text="Software engineer",
        summary="Backend engineer",
    )

    assert profile.authorized_to_work == "yes"
    assert profile.is_hispanic_or_latino == "no"
    assert profile.race == "asian"
    assert profile.disability_status == "no"
    assert profile.veteran_status == "no"


def test_candidate_profile_rejects_noncanonical_dropdown_option() -> None:
    with pytest.raises(ValidationError):
        CandidateProfile(
            first_name="Alex",
            last_name="Doe",
            email="alex@example.com",
            phone_country="+1",
            phone="555-0100",
            race="Asian",
            education=[],
            resume_text="Software engineer",
            summary="Backend engineer",
        )
