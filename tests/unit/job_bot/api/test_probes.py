from types import SimpleNamespace

from fastapi.testclient import TestClient

from job_bot.api import dependencies, probes
from job_bot.main import app


def test_health_reports_component_statuses(monkeypatch) -> None:
    session = SimpleNamespace()
    app.dependency_overrides[dependencies.get_session] = lambda: session
    monkeypatch.setattr(probes, "_check_database", lambda received_session: {"status": "healthy"})
    monkeypatch.setattr(probes, "_check_redis", lambda: {"status": "healthy"})
    try:
        response = TestClient(app).get("/api/health")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "components": {
            "db": {"status": "healthy"},
            "redis": {"status": "healthy"},
        },
    }


def test_health_returns_503_when_a_component_is_unhealthy(monkeypatch) -> None:
    session = SimpleNamespace()
    app.dependency_overrides[dependencies.get_session] = lambda: session
    monkeypatch.setattr(probes, "_check_database", lambda received_session: {"status": "healthy"})
    monkeypatch.setattr(
        probes,
        "_check_redis",
        lambda: {"status": "unhealthy", "detail": "redis check failed: timeout"},
    )
    try:
        response = TestClient(app).get("/api/health")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {
        "status": "unhealthy",
        "components": {
            "db": {"status": "healthy"},
            "redis": {"status": "unhealthy", "detail": "redis check failed: timeout"},
        },
    }
