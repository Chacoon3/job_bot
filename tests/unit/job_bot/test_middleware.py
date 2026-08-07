from unittest.mock import Mock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from job_bot import middleware


def _test_app() -> FastAPI:
    app = FastAPI()
    middleware.register_middleware(app)

    @app.get("/ok")
    async def ok() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/missing")
    async def missing() -> None:
        raise HTTPException(status_code=404, detail="missing")

    @app.get("/error")
    async def error() -> None:
        raise RuntimeError("boom")

    return app


def test_request_logging_records_request_and_response(monkeypatch) -> None:
    mock_logger = Mock()
    monkeypatch.setattr(middleware, "logger", mock_logger)
    monkeypatch.setattr(
        middleware, "settings", lambda: type("Settings", (), {"APP_ENV": "production"})()
    )
    client = TestClient(_test_app())

    response = client.get("/ok", headers={"X-Request-ID": "request-123"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "request-123"
    assert mock_logger.info.call_count == 2

    started = mock_logger.info.call_args_list[0]
    assert started.args == ("http_request_started",)
    assert started.kwargs["method"] == "GET"
    assert started.kwargs["path"] == "/ok"

    completed = mock_logger.info.call_args_list[1]
    assert completed.args == ("http_request_completed",)
    assert completed.kwargs["status_code"] == 200
    assert completed.kwargs["duration_ms"] >= 0


def test_request_logging_generates_request_id(monkeypatch) -> None:
    mock_logger = Mock()
    monkeypatch.setattr(middleware, "logger", mock_logger)
    monkeypatch.setattr(
        middleware, "settings", lambda: type("Settings", (), {"APP_ENV": "production"})()
    )
    client = TestClient(_test_app())

    response = client.get("/ok")

    assert response.headers["X-Request-ID"]


def test_request_logging_records_unhandled_exception(monkeypatch) -> None:
    mock_logger = Mock()
    monkeypatch.setattr(middleware, "logger", mock_logger)
    monkeypatch.setattr(
        middleware, "settings", lambda: type("Settings", (), {"APP_ENV": "production"})()
    )
    client = TestClient(_test_app(), raise_server_exceptions=False)

    response = client.get("/error")

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal Server Error"}
    mock_logger.exception.assert_called_once()
    failed = mock_logger.exception.call_args
    assert failed.args == ("http_request_failed",)
    assert failed.kwargs["method"] == "GET"
    assert failed.kwargs["path"] == "/error"
    assert failed.kwargs["duration_ms"] >= 0


def test_request_logging_renders_server_error_details_locally(monkeypatch) -> None:
    mock_logger = Mock()
    monkeypatch.setattr(middleware, "logger", mock_logger)
    monkeypatch.setattr(
        middleware, "settings", lambda: type("Settings", (), {"APP_ENV": "local"})()
    )
    client = TestClient(_test_app(), raise_server_exceptions=False)

    response = client.get("/error")

    assert response.status_code == 500
    assert response.json() == {
        "detail": "boom",
        "error": "RuntimeError",
    }
