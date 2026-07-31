from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from job_bot.api import candidate_profile, dependencies
from job_bot.main import app
from job_bot.schemas import CandidateProfile


class DummySession:
    def __init__(self) -> None:
        self.committed = False

    def commit(self) -> None:
        self.committed = True

    def refresh(self, _record: object) -> None:
        return


def _profile() -> CandidateProfile:
    return CandidateProfile(
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
    candidate_id: UUID,
    *,
    version: int = 1,
    deleted_at: datetime | None = None,
) -> SimpleNamespace:
    profile = _profile().model_dump(mode="json")
    return SimpleNamespace(
        **profile,
        candidate_id=candidate_id,
        version=version,
        resume_filename="resume.pdf",
        created_at=datetime(2026, 7, 30, tzinfo=UTC),
        deleted_at=deleted_at,
    )


def _supplement() -> candidate_profile.CandidateProfileSupplement:
    return candidate_profile.CandidateProfileSupplement(
        phone_country="+1",
        address_line_1="123 Main St",
        address_line_2="Apt 4B",
        city="New York",
        state="NY",
        postal_code="10001",
        country="United States",
        authorized_to_work="yes",
        requires_sponsorship="no",
        willing_to_relocate="no",
        race="decline",
    )


def test_extract_candidate_profile_uploads_resume_and_parses_structured_output(
    monkeypatch,
) -> None:
    client = Mock()
    client.files.create = AsyncMock(return_value=SimpleNamespace(id="file-resume"))
    client.files.delete = AsyncMock()
    resume_profile = _profile().model_copy(
        update={
            "address_line_1": "Address from resume",
            "address_line_2": None,
            "city": "Resume City",
            "state": "CA",
            "postal_code": "90210",
            "country": "Resume Country",
        }
    )
    client.responses.parse = AsyncMock(return_value=SimpleNamespace(output_parsed=resume_profile))
    monkeypatch.setenv("JOB_BOT_LLM_MODEL", "test-model")
    monkeypatch.setattr(candidate_profile, "get_async_openai_client", lambda: client)

    result = asyncio.run(
        candidate_profile._extract_candidate_profile.__wrapped__(
            b"resume bytes",
            "resume.pdf",
            _supplement(),
        )
    )

    assert result.requires_sponsorship == "no"
    assert result.willing_to_relocate == "no"
    assert result.address_line_1 == "123 Main St"
    assert result.address_line_2 == "Apt 4B"
    assert result.city == "New York"
    assert result.state == "NY"
    assert result.postal_code == "10001"
    assert result.country == "United States"
    client.files.create.assert_awaited_once_with(
        file=("resume.pdf", b"resume bytes"),
        purpose="user_data",
        expires_after={"anchor": "created_at", "seconds": 3600},
    )
    request = client.responses.parse.await_args.kwargs
    assert request["model"] == "test-model"
    assert request["text_format"] is CandidateProfile
    assert request["input"][0]["content"][0] == {
        "type": "input_file",
        "file_id": "file-resume",
    }
    assert '"requires_sponsorship": "no"' in request["input"][0]["content"][1]["text"]
    assert '"address_line_1": "123 Main St"' in request["input"][0]["content"][1]["text"]
    client.files.delete.assert_awaited_once_with("file-resume")


def test_extract_candidate_profile_deletes_upload_when_parsing_fails(
    monkeypatch,
) -> None:
    client = Mock()
    client.files.create = AsyncMock(return_value=SimpleNamespace(id="file-resume"))
    client.files.delete = AsyncMock()
    client.responses.parse = AsyncMock(return_value=SimpleNamespace(output_parsed=None))
    monkeypatch.setenv("JOB_BOT_LLM_MODEL", "test-model")
    monkeypatch.setattr(candidate_profile, "get_async_openai_client", lambda: client)

    with pytest.raises(RuntimeError, match="did not return a parsed CandidateProfile"):
        asyncio.run(
            candidate_profile._extract_candidate_profile.__wrapped__(
                b"resume bytes",
                "resume.pdf",
                _supplement(),
            )
        )

    client.files.delete.assert_awaited_once_with("file-resume")


def test_candidate_profile_cache_key_covers_every_extraction_input(monkeypatch) -> None:
    monkeypatch.setenv("JOB_BOT_LLM_MODEL", "model-a")
    function = candidate_profile._extract_candidate_profile.__wrapped__
    supplement = _supplement()

    base = candidate_profile._candidate_profile_cache_key(
        function,
        (b"resume bytes", "resume.pdf", supplement),
        {},
    )
    equivalent = candidate_profile._candidate_profile_cache_key(
        function,
        (),
        {
            "resume_content": b"resume bytes",
            "filename": "../resume.pdf",
            "profile_supplement": supplement.model_copy(),
        },
    )
    changed_resume = candidate_profile._candidate_profile_cache_key(
        function,
        (b"different resume", "resume.pdf", supplement),
        {},
    )
    changed_filename = candidate_profile._candidate_profile_cache_key(
        function,
        (b"resume bytes", "resume.docx", supplement),
        {},
    )
    changed_supplement = candidate_profile._candidate_profile_cache_key(
        function,
        (
            b"resume bytes",
            "resume.pdf",
            supplement.model_copy(update={"visa_status": "H-1B"}),
        ),
        {},
    )
    monkeypatch.setenv("JOB_BOT_LLM_MODEL", "model-b")
    changed_model = candidate_profile._candidate_profile_cache_key(
        function,
        (b"resume bytes", "resume.pdf", supplement),
        {},
    )

    assert equivalent == base
    assert (
        len(
            {
                base,
                changed_resume,
                changed_filename,
                changed_supplement,
                changed_model,
            }
        )
        == 5
    )


def test_get_candidate_profile_returns_requested_version(monkeypatch) -> None:
    candidate_id = uuid4()
    captured: dict[str, object] = {}

    def fake_get(session, received_id, version):
        captured.update(session=session, candidate_id=received_id, version=version)
        return _record(candidate_id, version=2)

    session = DummySession()
    app.dependency_overrides[dependencies.get_session] = lambda: session
    monkeypatch.setattr(candidate_profile, "get_profile_version", fake_get)

    response = TestClient(app).get(
        f"/apiv1/candidate_profile/{candidate_id}",
        params={"version": 2},
    )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["candidate_id"] == str(candidate_id)
    assert response.json()["version"] == 2
    assert captured == {
        "session": session,
        "candidate_id": candidate_id,
        "version": 2,
    }


def test_get_candidate_profile_returns_not_found(monkeypatch) -> None:
    candidate_id = uuid4()
    app.dependency_overrides[dependencies.get_session] = lambda: DummySession()
    monkeypatch.setattr(candidate_profile, "get_profile_version", lambda *_args: None)

    response = TestClient(app).get(f"/apiv1/candidate_profile/{candidate_id}")

    app.dependency_overrides.clear()

    assert response.status_code == 404


def test_upload_candidate_profile_merges_form_answers_and_creates_version(
    monkeypatch,
) -> None:
    candidate_id = uuid4()
    session = DummySession()
    captured: dict[str, object] = {}

    def fake_create(received_session, **kwargs):
        captured.update(session=received_session, **kwargs)
        record = _record(candidate_id)
        for field_name, value in kwargs["profile"].model_dump(mode="json").items():
            setattr(record, field_name, value)
        record.resume_filename = kwargs["resume_filename"]
        return record

    extract_profile = AsyncMock(
        return_value=_profile().model_copy(
            update={
                "address_line_1": "123 Main St",
                "city": "New York",
                "state": "NY",
                "postal_code": "10001",
                "country": "United States",
                "requires_sponsorship": "no",
                "willing_to_relocate": "no",
                "gender": "decline",
                "race": "decline",
            }
        )
    )
    app.dependency_overrides[dependencies.get_session] = lambda: session
    monkeypatch.setattr(candidate_profile, "_extract_candidate_profile", extract_profile)
    monkeypatch.setattr(candidate_profile, "create_profile_version", fake_create)

    response = TestClient(app).put(
        f"/apiv1/candidate_profile/{candidate_id}",
        data={
            "authorized_to_work": "yes",
            "requires_sponsorship": "no",
            "willing_to_relocate": "no",
            "race": "decline",
            "address_line_1": "123 Main St",
            "city": "New York",
            "state": "NY",
            "postal_code": "10001",
            "country": "United States",
        },
        files={"resume": ("../resume.pdf", b"resume bytes", "application/pdf")},
    )

    app.dependency_overrides.clear()

    assert response.status_code == 201
    payload = response.json()
    assert payload["profile"]["requires_sponsorship"] == "no"
    assert payload["profile"]["willing_to_relocate"] == "no"
    assert payload["profile"]["gender"] == "decline"
    assert payload["profile"]["address_line_1"] == "123 Main St"
    assert payload["profile"]["city"] == "New York"
    assert payload["resume_filename"] == "resume.pdf"
    supplement = extract_profile.await_args.args[2]
    assert supplement.address_line_1 == "123 Main St"
    assert supplement.city == "New York"
    assert supplement.country == "United States"
    assert captured["candidate_id"] == candidate_id
    assert len(captured["resume_sha256"]) == 64
    assert session.committed is True


def test_upload_new_candidate_profile_assigns_candidate_id(monkeypatch) -> None:
    generated_candidate_id = uuid4()
    session = DummySession()
    captured: dict[str, object] = {}

    def fake_create(received_session, **kwargs):
        captured.update(session=received_session, **kwargs)
        record = _record(kwargs["candidate_id"])
        for field_name, value in kwargs["profile"].model_dump(mode="json").items():
            setattr(record, field_name, value)
        record.resume_filename = kwargs["resume_filename"]
        return record

    app.dependency_overrides[dependencies.get_session] = lambda: session
    monkeypatch.setattr(candidate_profile, "uuid4", lambda: generated_candidate_id)
    monkeypatch.setattr(
        candidate_profile,
        "_extract_candidate_profile",
        AsyncMock(
            return_value=_profile().model_copy(
                update={
                    "requires_sponsorship": "no",
                    "willing_to_relocate": "yes",
                }
            )
        ),
    )
    monkeypatch.setattr(candidate_profile, "create_profile_version", fake_create)

    response = TestClient(app).post(
        "/apiv1/candidate_profile",
        data={
            "authorized_to_work": "yes",
            "requires_sponsorship": "no",
            "willing_to_relocate": "yes",
        },
        files={"resume": ("resume.pdf", b"resume bytes", "application/pdf")},
    )

    app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["candidate_id"] == str(generated_candidate_id)
    assert response.json()["version"] == 1
    assert captured["candidate_id"] == generated_candidate_id
    assert session.committed is True


def test_upload_candidate_profile_rejects_unsupported_file() -> None:
    candidate_id = uuid4()
    app.dependency_overrides[dependencies.get_session] = lambda: DummySession()

    response = TestClient(app).put(
        f"/apiv1/candidate_profile/{candidate_id}",
        data={
            "authorized_to_work": "yes",
            "requires_sponsorship": "no",
            "willing_to_relocate": "yes",
        },
        files={"resume": ("resume.txt", b"resume", "text/plain")},
    )

    app.dependency_overrides.clear()

    assert response.status_code == 415


def test_delete_candidate_profile_soft_deletes_requested_version(monkeypatch) -> None:
    candidate_id = uuid4()
    session = DummySession()
    deleted_at = datetime(2026, 7, 30, tzinfo=UTC)
    captured: dict[str, object] = {}

    def fake_delete(received_session, received_id, version):
        captured.update(
            session=received_session,
            candidate_id=received_id,
            version=version,
        )
        return _record(candidate_id, version=3, deleted_at=deleted_at)

    app.dependency_overrides[dependencies.get_session] = lambda: session
    monkeypatch.setattr(candidate_profile, "delete_profile_version", fake_delete)

    response = TestClient(app).delete(
        f"/apiv1/candidate_profile/{candidate_id}",
        params={"version": 3},
    )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["version"] == 3
    assert response.json()["deleted_at"] == "2026-07-30T00:00:00Z"
    assert captured["version"] == 3
    assert session.committed is True
