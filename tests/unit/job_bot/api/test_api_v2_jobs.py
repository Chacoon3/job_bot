from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient

from job_bot.api import dependencies, job_api
from job_bot.app_def import app
from job_bot.db.job_models import Job


class DummySession:
    def __init__(self, boards: list[SimpleNamespace] | None = None) -> None:
        self.boards = boards or []

    async def execute(self, statement):
        self.statement = statement
        return SimpleNamespace(
            scalars=lambda: SimpleNamespace(all=lambda: self.boards),
        )

    def close(self) -> None:
        return


def _board(token: str) -> SimpleNamespace:
    return SimpleNamespace(token=token, company_name=token.title())


def _job(title: str, posted_at: datetime) -> Job:
    return Job(
        job_title=title,
        url=f"https://example.com/{title}",
        company_name="Acme",
        job_location="Remote",
        jd_summary="Example job",
        date_posted=posted_at,
    )


def test_get_company_jobs_fetches_named_boards_filters_and_sorts(monkeypatch) -> None:
    session = DummySession()
    now = datetime.now(UTC)
    captured: dict[str, object] = {}

    async def fake_list_boards(_session, **kwargs):
        captured.setdefault("names", []).append(kwargs["company_name"])
        return [_board(kwargs["company_name"])], 1

    class FakeService:
        def __init__(self, _session) -> None:
            return

        def pull_company_job_entries(self, token, **_kwargs):
            return [
                _job(f"{token}-old", now - timedelta(days=31)),
                _job(f"{token}-new", now - timedelta(days=2)),
            ]

    app.dependency_overrides[dependencies.get_session] = lambda: session
    monkeypatch.setattr(job_api, "list_boards", fake_list_boards)
    monkeypatch.setattr(job_api, "GreenhouseJobSyncService", FakeService)
    try:
        response = TestClient(app).get(
            "/api/job/",
            params={"company_names": "Acme, Beta", "limit": 10},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert captured["names"] == ["Acme", "Beta"]
    assert [job["job_title"] for job in response.json()] == ["Acme-new", "Beta-new"]


def test_get_company_jobs_uses_three_random_boards_without_company_names(monkeypatch) -> None:
    session = DummySession([_board("one"), _board("two"), _board("three")])
    now = datetime.now(UTC)
    fetched_tokens: list[str] = []

    class FakeService:
        def __init__(self, _session) -> None:
            return

        def pull_company_job_entries(self, token, **_kwargs):
            fetched_tokens.append(token)
            return [_job(token, now)]

    app.dependency_overrides[dependencies.get_session] = lambda: session
    monkeypatch.setattr(job_api, "GreenhouseJobSyncService", FakeService)
    try:
        response = TestClient(app).get("/api/job/", params={"posted_after": "2026-01-01"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert fetched_tokens == ["one", "two", "three"]
    assert "random()" in str(session.statement)


def test_get_company_jobs_falls_back_to_company_slug_when_board_is_missing(monkeypatch) -> None:
    session = DummySession()
    fetched_tokens: list[str] = []

    async def fake_list_boards(_session, **kwargs):
        if kwargs["company_name"] == "Known Company":
            return [_board("stored-token")], 1
        return [], 0

    class FakeService:
        def __init__(self, _session) -> None:
            return

        def pull_company_job_entries(self, token, **_kwargs):
            fetched_tokens.append(token)
            return []

    app.dependency_overrides[dependencies.get_session] = lambda: session
    monkeypatch.setattr(job_api, "list_boards", fake_list_boards)
    monkeypatch.setattr(job_api, "GreenhouseJobSyncService", FakeService)
    try:
        response = TestClient(app).get(
            "/api/job/",
            params={"company_names": "Known Company, Acme & Co."},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert fetched_tokens == ["stored-token", "acmeco"]


def test_get_company_jobs_rejects_an_empty_company_names_filter() -> None:
    app.dependency_overrides[dependencies.get_session] = lambda: DummySession()
    try:
        response = TestClient(app).get("/api/job/", params={"company_names": " , "})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["detail"] == "company_names is empty"
