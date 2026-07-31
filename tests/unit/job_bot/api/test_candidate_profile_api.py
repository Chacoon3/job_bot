from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

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

    app.dependency_overrides[dependencies.get_session] = lambda: session
    monkeypatch.setattr(candidate_profile, "_extract_candidate_profile", lambda *_args: _profile())
    monkeypatch.setattr(candidate_profile, "create_profile_version", fake_create)

    response = TestClient(app).put(
        f"/apiv1/candidate_profile/{candidate_id}",
        data={
            "authorized_to_work": "yes",
            "requires_sponsorship": "no",
            "willing_to_relocate": "no",
            "race": "decline",
        },
        files={"resume": ("../resume.pdf", b"resume bytes", "application/pdf")},
    )

    app.dependency_overrides.clear()

    assert response.status_code == 201
    payload = response.json()
    assert payload["profile"]["requires_sponsorship"] == "no"
    assert payload["profile"]["willing_to_relocate"] == "no"
    assert payload["profile"]["gender"] == "decline"
    assert payload["resume_filename"] == "resume.pdf"
    assert captured["candidate_id"] == candidate_id
    assert len(captured["resume_sha256"]) == 64
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
