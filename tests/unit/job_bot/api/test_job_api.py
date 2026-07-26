from __future__ import annotations

from datetime import UTC, datetime

from job_bot.api import job
from job_bot.schemas import JobEntrySchema


class DummySession:
    def __init__(self) -> None:
        self.committed = False

    def commit(self) -> None:
        self.committed = True


def _sample_job() -> JobEntrySchema:
    return JobEntrySchema(
        source="untrusted-source",
        job_title="Software Engineer",
        url="https://careers.example.com/jobs/123",
        year_of_experience_minimum=2,
        year_of_experience_maximum=4,
        company_name="Example",
        job_location="Remote",
        jd_summary="Build reliable systems.",
        pay_range_minimum=120_000,
        pay_range_maximum=160_000,
        date_posted=datetime(2026, 7, 25, tzinfo=UTC),
    )


def test_load_jobs_converts_upserts_and_commits(monkeypatch) -> None:
    captured: dict[str, object] = {}
    session = DummySession()

    class FakeProvider:
        def __init__(self, **kwargs: object) -> None:
            captured["provider_kwargs"] = kwargs

        def provide(self) -> list[JobEntrySchema]:
            return [_sample_job()]

    def fake_batched_upsert(
        received_session: object,
        model: object,
        rows: object,
        **kwargs: object,
    ) -> int:
        captured["session"] = received_session
        captured["model"] = model
        captured["rows"] = list(rows)  # type: ignore[arg-type]
        captured["upsert_kwargs"] = kwargs
        return 1

    monkeypatch.setattr(job, "LLMJobProvider", FakeProvider)
    monkeypatch.setattr(job, "batched_upsert", fake_batched_upsert)

    result = job.load_jobs(
        job.LoadJobQuery(
            company_names=["Example"],
            earliest_post_date=datetime(2026, 7, 1, tzinfo=UTC),
        ),
        session,  # type: ignore[arg-type]
    )

    assert result[0].source == "llm"
    assert captured["session"] is session
    assert captured["model"] is job.JobEntry
    rows = captured["rows"]
    assert len(rows) == 1  # type: ignore[arg-type]
    assert rows[0]["source"] == "llm"  # type: ignore[index]
    assert rows[0]["url"] == "https://careers.example.com/jobs/123"  # type: ignore[index]
    assert "id" not in rows[0]  # type: ignore[operator]
    kwargs = captured["upsert_kwargs"]
    assert kwargs["conflict_columns"] == [job.JobEntry.url]  # type: ignore[index]
    assert session.committed is True
