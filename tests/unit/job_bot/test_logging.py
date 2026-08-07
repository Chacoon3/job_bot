from __future__ import annotations

import json
import logging

import structlog
from opentelemetry.sdk.trace import TracerProvider

from job_bot.app_logging import configure_logging


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
    monkeypatch.setenv("APP_ENV", "production")
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


def test_configure_logging_adds_active_trace_context(monkeypatch, capsys) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    configure_logging()
    tracer = TracerProvider().get_tracer("test")

    with tracer.start_as_current_span("test-span") as span:
        structlog.get_logger("test").info("inside_span")
        expected_trace_id = format(span.get_span_context().trace_id, "032x")
        expected_span_id = format(span.get_span_context().span_id, "016x")

    log_record = json.loads(capsys.readouterr().out)
    assert log_record["trace_id"] == expected_trace_id
    assert log_record["span_id"] == expected_span_id
