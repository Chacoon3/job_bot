from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from job_bot.api import greenhouse_api
from job_bot.main import app


class DummySession:
    def close(self) -> None:
        return


def _sample_board() -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=1,
        token="acme",
        company_name="Acme",
        board_url="https://job-boards.greenhouse.io/acme",
        api_url="https://boards-api.greenhouse.io/v1/boards/acme/jobs",
        active_job_count=3,
        sample_job_titles=["Software Engineer"],
        discovered_urls=["https://example.com"],
        crawl_indexes=["CC-MAIN-2026-30"],
        verified_at=now,
        created_at=now,
        updated_at=now,
    )


def test_get_boards_returns_paginated_payload(monkeypatch) -> None:
    def fake_list_boards(*args, **kwargs):
        return [_sample_board()], 1

    app.dependency_overrides[greenhouse_api.get_session] = lambda: iter([DummySession()])
    monkeypatch.setattr(greenhouse_api, "list_boards", fake_list_boards)

    client = TestClient(app)
    response = client.get("/api/boards")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["limit"] == 50
    assert payload["offset"] == 0
    assert len(payload["boards"]) == 1
    assert payload["boards"][0]["token"] == "acme"


def test_get_boards_passes_filters(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_list_boards(*args, **kwargs):
        captured.update(kwargs)
        return [], 0

    app.dependency_overrides[greenhouse_api.get_session] = lambda: iter([DummySession()])
    monkeypatch.setattr(greenhouse_api, "list_boards", fake_list_boards)

    client = TestClient(app)
    response = client.get(
        "/api/boards",
        params={
            "token": "ac",
            "company_name": "Acme",
            "crawl_index": "CC-MAIN-2026-30",
            "has_open_jobs": "true",
            "min_active_job_count": 1,
            "max_active_job_count": 9,
            "sort_by": "active_job_count",
            "sort_desc": "false",
            "limit": 20,
            "offset": 5,
        },
    )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert captured["token"] == "ac"
    assert captured["company_name"] == "Acme"
    assert captured["crawl_index"] == "CC-MAIN-2026-30"
    assert captured["has_open_jobs"] is True
    assert captured["min_active_job_count"] == 1
    assert captured["max_active_job_count"] == 9
    assert captured["sort_by"] == "active_job_count"
    assert captured["sort_desc"] is False
    assert captured["limit"] == 20
    assert captured["offset"] == 5
