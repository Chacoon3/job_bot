from __future__ import annotations

import json
import logging

import structlog

from job_bot.logging import configure_logging


def test_configure_logging_uses_json_outside_local_environment(monkeypatch, capsys) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    configure_logging()

    structlog.get_logger("test").info("job_found", job_id="123", company="Example")

    log_record = json.loads(capsys.readouterr().out)

    assert list(log_record)[:2] == ["level", "event"]
    assert log_record["level"] == "info"
    assert log_record["event"] == "job_found"
    assert log_record["job_id"] == "123"
    assert log_record["company"] == "Example"


def test_configure_logging_uses_console_renderer_locally(monkeypatch, capsys) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    configure_logging()

    structlog.get_logger("test").info("job_found", job_id="123")

    output = capsys.readouterr().out
    assert "job_found" in output
    assert "job_id" in output
    assert "123" in output
    assert not output.lstrip().startswith("{")


def test_configure_logging_routes_standard_library_logs_through_renderer(
    monkeypatch, capsys
) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    configure_logging()

    logging.getLogger("dependency").warning("dependency_warning")

    log_record = json.loads(capsys.readouterr().out)
    assert log_record["level"] == "warning"
    assert log_record["event"] == "dependency_warning"
    assert log_record["logger"] == "dependency"


def test_configure_logging_replaces_uvicorn_handlers(monkeypatch, capsys) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    uvicorn_logger = logging.getLogger("uvicorn.access")
    uvicorn_logger.addHandler(logging.StreamHandler())
    uvicorn_logger.propagate = False

    configure_logging()
    uvicorn_logger.info("server_started")

    log_record = json.loads(capsys.readouterr().out)
    assert log_record["event"] == "server_started"
    assert log_record["logger"] == "uvicorn.access"
