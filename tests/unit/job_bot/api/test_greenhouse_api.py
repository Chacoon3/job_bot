from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from job_bot.api import dependencies, greenhouse_api
from job_bot.greenhouse.jobs import GreenhouseJobSyncResult
from job_bot.greenhouse.models import DiscoveryReport, DiscoveryStats
from job_bot.main import app


class DummySession:
    committed = False

    def close(self) -> None:
        return

    def commit(self) -> None:
        self.committed = True


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

    app.dependency_overrides[dependencies.get_session] = lambda: iter([DummySession()])
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

    app.dependency_overrides[dependencies.get_session] = lambda: iter([DummySession()])
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


def test_discover_boards_runs_discovery_and_persists_results(monkeypatch) -> None:
    session = DummySession()
    captured: dict[str, object] = {}
    report = DiscoveryReport(boards=[], stats=DiscoveryStats(unique_candidates=7))

    class FakeDiscoverer:
        def __init__(self, config) -> None:
            captured["config"] = config

        async def discover(self) -> DiscoveryReport:
            return report

    def fake_upsert_boards(received_session, boards) -> int:
        captured["session"] = received_session
        captured["boards"] = boards
        return len(boards)

    app.dependency_overrides[dependencies.get_session] = lambda: session
    monkeypatch.setattr(greenhouse_api, "GreenhouseGlobalDiscoverer", FakeDiscoverer)
    monkeypatch.setattr(greenhouse_api, "upsert_boards", fake_upsert_boards)

    client = TestClient(app)
    response = client.post(
        "/api/boards/discover",
        json={
            "limit": 25,
            "max_candidates": 500,
            "crawl_count": 3,
            "max_pages_per_query": 20,
            "include_empty_boards": True,
            "enrich_company_names": False,
            "verification_concurrency": 12,
            "enrichment_concurrency": 6,
            "request_timeout_seconds": 15.5,
        },
    )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["stats"]["unique_candidates"] == 7
    config = captured["config"]
    assert config.limit == 25
    assert config.max_candidates == 500
    assert config.crawl_count == 3
    assert config.max_pages_per_query == 20
    assert config.include_empty_boards is True
    assert config.enrich_company_names is False
    assert config.verification_concurrency == 12
    assert config.enrichment_concurrency == 6
    assert config.request_timeout_seconds == 15.5
    assert captured["session"] is session
    assert captured["boards"] == []
    assert session.committed is True


def test_discover_boards_by_company_uses_llm_provider(monkeypatch) -> None:
    session = DummySession()
    provider = object()
    captured: dict[str, object] = {}
    report = DiscoveryReport(boards=[], stats=DiscoveryStats(unique_candidates=1))

    class FakeCompanyDiscoverer:
        def __init__(self, company_names, llm_provider, config) -> None:
            captured["company_names"] = company_names
            captured["llm_provider"] = llm_provider
            captured["config"] = config

        async def discover(self) -> DiscoveryReport:
            return report

    app.dependency_overrides[dependencies.get_session] = lambda: session
    monkeypatch.setattr(greenhouse_api, "OpenAILLMProvider", lambda: provider)
    monkeypatch.setattr(
        greenhouse_api,
        "GreenhouseCompanyDiscoverer",
        FakeCompanyDiscoverer,
    )
    monkeypatch.setattr(greenhouse_api, "upsert_boards", lambda *_args: 0)

    client = TestClient(app)
    response = client.post(
        "/api/boards/discover",
        json={
            "approach": "company",
            "company_names": [" Acme ", "Acme", "Example Corp"],
            "limit": 5,
        },
    )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert captured["company_names"] == ["Acme", "Example Corp"]
    assert captured["llm_provider"] is provider
    assert captured["config"].approach == "company"
    assert session.committed is True


def test_company_discovery_requires_company_names() -> None:
    app.dependency_overrides[dependencies.get_session] = lambda: DummySession()

    client = TestClient(app)
    response = client.post(
        "/api/boards/discover",
        json={"approach": "company"},
    )

    app.dependency_overrides.clear()

    assert response.status_code == 422
    assert "company_names must contain at least one name" in response.text


def test_sync_greenhouse_jobs_fetches_persists_and_commits(monkeypatch) -> None:
    session = DummySession()
    captured: dict[str, object] = {}

    class FakeSyncService:
        def __init__(self, received_session) -> None:
            captured["session"] = received_session

        def sync(self, **kwargs) -> GreenhouseJobSyncResult:
            captured.update(kwargs)
            return GreenhouseJobSyncResult(
                boards_queried=4,
                boards_failed=1,
                jobs_found=12,
                jobs_stored=12,
            )

    app.dependency_overrides[dependencies.get_session] = lambda: session
    monkeypatch.setattr(greenhouse_api, "GreenhouseJobSyncService", FakeSyncService)

    client = TestClient(app)
    response = client.post(
        "/api/greenhouse/jobs/sync",
        params=[
            ("policy", "most_jobs"),
            ("board_limit", "2"),
            ("include_keywords", "python"),
            ("include_keywords", "backend"),
            ("exclude_keywords", "staffing"),
        ],
    )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "boards_queried": 4,
        "boards_failed": 1,
        "jobs_found": 12,
        "jobs_stored": 12,
    }
    assert captured["session"] is session
    assert captured["policy"] == "most_jobs"
    assert captured["board_limit"] == 2
    assert captured["include_keywords"] == ["python", "backend"]
    assert captured["exclude_keywords"] == ["staffing"]
    assert session.committed is True
