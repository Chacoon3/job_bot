from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from job_bot.data.schemas import GreenhouseBoardSchema, JobEntrySchema, User
from job_bot.db.greenhouse_models import GreenhouseBoard
from job_bot.db.job_models import Job


def test_job_entry_schema_round_trips_job() -> None:
    orm_job = Job(
        source="greenhouse",
        job_title="Software Engineer",
        url="https://example.com/jobs/123",
        company_name="Example Corp",
        job_location="Remote",
        jd_summary="Build systems",
        date_posted=datetime(2026, 7, 25, tzinfo=UTC),
    )

    schema = JobEntrySchema.from_orm_model(orm_job)
    restored = schema.to_orm_model()

    assert restored.job_title == "Software Engineer"
    assert restored.url == "https://example.com/jobs/123"


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


def test_user_uses_canonical_dropdown_options() -> None:
    profile = User(
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


def test_user_rejects_noncanonical_dropdown_option() -> None:
    with pytest.raises(ValidationError):
        User(
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


def test_user_validates_and_normalizes_email() -> None:
    profile = User(
        first_name="Alex",
        last_name="Doe",
        email="  Alex.Doe@EXAMPLE.COM ",
        phone_country="+1",
        phone="555-0100",
        education=[],
        resume_text="Software engineer",
        summary="Backend engineer",
    )

    assert profile.email == "alex.doe@example.com"


@pytest.mark.parametrize(
    ("phone_country", "country", "expected_phone_country", "expected_country"),
    [
        ("+1", "u.s.a.", "United States", "United States"),
        ("UK (+44)", "bosnia AND herzegovina", "United Kingdom", "Bosnia and Herzegovina"),
        ("+971", "u a e", "United Arab Emirates", "United Arab Emirates"),
    ],
)
def test_user_normalizes_country_fields(
    phone_country: str,
    country: str,
    expected_phone_country: str,
    expected_country: str,
) -> None:
    profile = User(
        first_name="Alex",
        last_name="Doe",
        email="alex@example.com",
        phone_country=phone_country,
        phone="555-0100",
        country=country,
        education=[],
        resume_text="Software engineer",
        summary="Backend engineer",
    )

    assert profile.phone_country == expected_phone_country
    assert profile.country == expected_country


def test_user_rejects_unknown_phone_calling_code() -> None:
    with pytest.raises(ValidationError, match="phone_country must identify a country"):
        User(
            first_name="Alex",
            last_name="Doe",
            email="alex@example.com",
            phone_country="+999",
            phone="555-0100",
            education=[],
            resume_text="Software engineer",
            summary="Backend engineer",
        )


def test_user_rejects_invalid_email() -> None:
    with pytest.raises(ValidationError):
        User(
            first_name="Alex",
            last_name="Doe",
            email="not-an-email",
            phone_country="+1",
            phone="555-0100",
            education=[],
            resume_text="Software engineer",
            summary="Backend engineer",
        )
