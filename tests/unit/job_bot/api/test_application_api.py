from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from job_bot.api import api_v2, dependencies
from job_bot.applications import ApplicationRunResult
from job_bot.main import app
from job_bot.schemas import User


def _user() -> User:
    return User(
        first_name="Alex",
        last_name="Doe",
        email="alex@example.com",
        phone_country="United States",
        phone="555-0100",
        education=[],
        resume_text="Software engineer",
        summary="Backend engineer",
    )


def test_apply_returns_prior_success_without_running_browser(monkeypatch) -> None:
    session = SimpleNamespace()
    user_id = uuid4()
    attempt = SimpleNamespace(
        attempt_id=uuid4(),
        status="succeeded",
        attempt_number=1,
        job_url="https://example.com/jobs/1",
    )
    calls: dict[str, object] = {}

    async def fake_run(received_session, **kwargs):
        calls.update(session=received_session, **kwargs)
        return ApplicationRunResult(attempt, False, "already_succeeded")

    monkeypatch.setattr(api_v2, "get_user", lambda *_args: SimpleNamespace(id=user_id))
    monkeypatch.setattr(api_v2, "user_from_record", lambda _record: _user())
    monkeypatch.setattr(api_v2, "run_application_once", fake_run)
    monkeypatch.setattr(
        api_v2,
        "async_playwright",
        lambda: (_ for _ in ()).throw(AssertionError("browser must not start")),
    )
    app.dependency_overrides[dependencies.get_session] = lambda: session
    app.dependency_overrides[dependencies.require_browser_automation] = lambda: None
    try:
        response = TestClient(app).post(
            "/apiv2/apply",
            data={
                "email": "alex@example.com",
                "job_url": "https://example.com/jobs/1",
            },
            files={"resume": ("resume.pdf", b"resume", "application/pdf")},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "attempt_id": str(attempt.attempt_id),
        "status": "succeeded",
        "attempt_number": 1,
        "job_url": "https://example.com/jobs/1",
        "executed": False,
    }
    assert calls["session"] is session
    assert calls["user_id"] == user_id


def test_apply_reports_an_attempt_already_in_progress(monkeypatch) -> None:
    session = SimpleNamespace()
    attempt = SimpleNamespace(
        attempt_id=uuid4(),
        status="in_progress",
        attempt_number=1,
        job_url="https://example.com/jobs/1",
    )

    async def fake_run(*_args, **_kwargs):
        return ApplicationRunResult(attempt, False, "in_progress")

    monkeypatch.setattr(api_v2, "get_user", lambda *_args: SimpleNamespace(id=uuid4()))
    monkeypatch.setattr(api_v2, "user_from_record", lambda _record: _user())
    monkeypatch.setattr(api_v2, "run_application_once", fake_run)
    app.dependency_overrides[dependencies.get_session] = lambda: session
    app.dependency_overrides[dependencies.require_browser_automation] = lambda: None
    try:
        response = TestClient(app).post(
            "/apiv2/apply",
            data={
                "email": "alex@example.com",
                "job_url": "https://example.com/jobs/1",
            },
            files={"resume": ("resume.pdf", b"resume", "application/pdf")},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json()["detail"]["attempt_id"] == str(attempt.attempt_id)
