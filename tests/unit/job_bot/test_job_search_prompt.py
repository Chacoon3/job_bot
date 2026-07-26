from __future__ import annotations

from datetime import UTC, datetime

from job_bot.flow import JobQuery, _build_job_search_prompt


def job_query(extra_criteria: list[str] | None = None) -> JobQuery:
    return JobQuery(
        job_title="Senior Python Engineer",
        year_of_experience_minimum=4,
        year_of_experience_maximum=8,
        job_location="Remote, United States",
        pay_range_minimum=150_000,
        pay_range_maximum=210_000,
        key_words=["Python", "PostgreSQL"],
        posted_since=datetime(2026, 7, 1, tzinfo=UTC),
        extra_criteria=extra_criteria,
        num_limit=12,
    )


def test_prompt_contains_query_constraints_and_field_requirements() -> None:
    prompt = _build_job_search_prompt(job_query())

    assert "Return up to 12 verified jobs" in prompt
    assert "Senior Python Engineer" in prompt
    assert "4 to 8 years" in prompt
    assert "150000 to 210000" in prompt
    assert "2026-07-01T00:00:00+00:00" in prompt
    assert "Copy the canonical official posting URL" in prompt
    assert "<extra_criteria>\n- None\n</extra_criteria>" in prompt


def test_prompt_preserves_each_extra_criterion() -> None:
    prompt = _build_job_search_prompt(
        job_query(["No on-call rotation", "Individual contributor role"])
    )

    assert "<extra_criteria>" in prompt
    assert "- No on-call rotation" in prompt
    assert "- Individual contributor role" in prompt
    assert "<field_requirements>" in prompt
