from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from job_bot.api import dependencies, user
from job_bot.main import app
from job_bot.schemas import User


class DummySession:
    def __init__(self) -> None:
        self.committed = False

    def commit(self) -> None:
        self.committed = True

    def refresh(self, _record: object) -> None:
        return


def _user() -> User:
    return User(
        first_name="Alex",
        last_name="Doe",
        email="alex@example.com",
        phone_country="+1",
        phone="555-0100",
        education=[],
        resume_text="Software engineer",
        summary="Backend engineer",
    )


def _record(
    user_id: UUID,
    *,
    deleted_at: datetime | None = None,
) -> SimpleNamespace:
    timestamp = datetime(2026, 7, 30, tzinfo=UTC)
    return SimpleNamespace(
        **_user().model_dump(mode="json"),
        id=user_id,
        resume_filename="resume.pdf",
        resume_sha256="0" * 64,
        created_at=timestamp,
        updated_at=timestamp,
        deleted_at=deleted_at,
    )


def _supplement() -> user.UserSupplement:
    return user.UserSupplement(
        phone_country="+1",
        address_line_1="123 Main St",
        city="New York",
        state="NY",
        postal_code="10001",
        country="United States",
        authorized_to_work="yes",
        requires_sponsorship="no",
        willing_to_relocate="no",
        race="decline",
    )


def test_extract_user_uploads_resume_and_merges_authoritative_answers(monkeypatch) -> None:
    client = Mock()
    client.files.create = AsyncMock(return_value=SimpleNamespace(id="file-resume"))
    client.files.delete = AsyncMock()
    resume_user = _user().model_copy(
        update={
            "address_line_1": "Address from resume",
            "city": "Resume City",
            "requires_sponsorship": "yes",
        }
    )
    client.responses.parse = AsyncMock(return_value=SimpleNamespace(output_parsed=resume_user))
    monkeypatch.setenv("JOB_BOT_LLM_MODEL", "test-model")
    monkeypatch.setattr(user, "get_async_openai_client", lambda: client)

    result = asyncio.run(
        user._extract_user.__wrapped__(
            b"resume bytes",
            "resume.pdf",
            _supplement(),
        )
    )

    assert result.requires_sponsorship == "no"
    assert result.address_line_1 == "123 Main St"
    assert result.city == "New York"
    request = client.responses.parse.await_args.kwargs
    assert request["text_format"] is User
    assert '"address_line_1": "123 Main St"' in request["input"][0]["content"][1]["text"]
    client.files.delete.assert_awaited_once_with("file-resume")


def test_extract_user_deletes_upload_when_parsing_fails(monkeypatch) -> None:
    client = Mock()
    client.files.create = AsyncMock(return_value=SimpleNamespace(id="file-resume"))
    client.files.delete = AsyncMock()
    client.responses.parse = AsyncMock(return_value=SimpleNamespace(output_parsed=None))
    monkeypatch.setenv("JOB_BOT_LLM_MODEL", "test-model")
    monkeypatch.setattr(user, "get_async_openai_client", lambda: client)

    with pytest.raises(RuntimeError, match="did not return a parsed User"):
        asyncio.run(
            user._extract_user.__wrapped__(
                b"resume bytes",
                "resume.pdf",
                _supplement(),
            )
        )

    client.files.delete.assert_awaited_once_with("file-resume")


def test_user_cache_key_covers_every_extraction_input(monkeypatch) -> None:
    monkeypatch.setenv("JOB_BOT_LLM_MODEL", "model-a")
    function = user._extract_user.__wrapped__
    supplement = _supplement()

    base = user._user_cache_key(function, (b"resume bytes", "resume.pdf", supplement), {})
    changed_resume = user._user_cache_key(
        function,
        (b"different resume", "resume.pdf", supplement),
        {},
    )
    changed_supplement = user._user_cache_key(
        function,
        (
            b"resume bytes",
            "resume.pdf",
            supplement.model_copy(update={"visa_status": "H-1B"}),
        ),
        {},
    )

    assert len({base, changed_resume, changed_supplement}) == 3


def test_get_user_returns_the_current_user(monkeypatch) -> None:
    user_id = uuid4()
    session = DummySession()
    app.dependency_overrides[dependencies.get_session] = lambda: session
    monkeypatch.setattr(user, "get_user", lambda *_args: _record(user_id))

    response = TestClient(app).get(f"/apiv1/user/{user_id}")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["user_id"] == str(user_id)
    assert response.json()["user"]["email"] == "alex@example.com"
    assert "version" not in response.json()


def test_get_user_returns_not_found(monkeypatch) -> None:
    user_id = uuid4()
    app.dependency_overrides[dependencies.get_session] = lambda: DummySession()
    monkeypatch.setattr(user, "get_user", lambda *_args: None)

    response = TestClient(app).get(f"/apiv1/user/{user_id}")

    app.dependency_overrides.clear()

    assert response.status_code == 404


def test_update_user_replaces_current_data(monkeypatch) -> None:
    user_id = uuid4()
    session = DummySession()
    captured: dict[str, object] = {}
    extracted = _user().model_copy(
        update={
            "address_line_1": "123 Main St",
            "requires_sponsorship": "no",
            "race": "decline",
        }
    )

    def fake_upsert(received_session, **kwargs):
        captured.update(session=received_session, **kwargs)
        record = _record(user_id)
        for field_name, value in kwargs["user"].model_dump(mode="json").items():
            setattr(record, field_name, value)
        record.resume_filename = kwargs["resume_filename"]
        return record

    app.dependency_overrides[dependencies.get_session] = lambda: session
    monkeypatch.setattr(user, "_extract_user", AsyncMock(return_value=extracted))
    monkeypatch.setattr(user, "upsert_user", fake_upsert)

    response = TestClient(app).put(
        f"/apiv1/user/{user_id}",
        data={
            "authorized_to_work": "yes",
            "requires_sponsorship": "no",
            "willing_to_relocate": "no",
        },
        files={"resume": ("../resume.pdf", b"resume bytes", "application/pdf")},
    )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["user"]["requires_sponsorship"] == "no"
    assert captured["user_id"] == user_id
    assert len(captured["resume_sha256"]) == 64
    assert session.committed is True


def test_create_user_assigns_user_id(monkeypatch) -> None:
    generated_user_id = uuid4()
    session = DummySession()
    captured: dict[str, object] = {}

    def fake_upsert(received_session, **kwargs):
        captured.update(session=received_session, **kwargs)
        return _record(kwargs["user_id"])

    app.dependency_overrides[dependencies.get_session] = lambda: session
    monkeypatch.setattr(user, "uuid4", lambda: generated_user_id)
    monkeypatch.setattr(user, "_extract_user", AsyncMock(return_value=_user()))
    monkeypatch.setattr(user, "upsert_user", fake_upsert)

    response = TestClient(app).post(
        "/apiv1/user",
        data={
            "authorized_to_work": "yes",
            "requires_sponsorship": "no",
            "willing_to_relocate": "yes",
        },
        files={"resume": ("resume.pdf", b"resume bytes", "application/pdf")},
    )

    app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["user_id"] == str(generated_user_id)
    assert captured["user_id"] == generated_user_id


def test_delete_user_soft_deletes_user(monkeypatch) -> None:
    user_id = uuid4()
    session = DummySession()
    deleted_at = datetime(2026, 7, 30, tzinfo=UTC)
    app.dependency_overrides[dependencies.get_session] = lambda: session
    monkeypatch.setattr(
        user,
        "delete_user",
        lambda *_args: _record(user_id, deleted_at=deleted_at),
    )

    response = TestClient(app).delete(f"/apiv1/user/{user_id}")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["deleted_at"] == "2026-07-30T00:00:00Z"
    assert session.committed is True
