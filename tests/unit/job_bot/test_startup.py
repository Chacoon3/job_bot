from __future__ import annotations

import os
import subprocess
import sys
from unittest.mock import Mock

import job_bot.app_def


def test_main_import_defers_optional_runtime_dependencies() -> None:
    code = """
import os
import sys

import job_bot.main

deferred = (
    "langchain_anthropic",
    "langchain_google_genai",
    "langchain_huggingface",
    "langchain_ollama",
    "langchain_openai",
    "openai",
    "playwright.async_api",
    "opentelemetry.exporter.otlp.proto.http.trace_exporter",
)
loaded = [name for name in deferred if name in sys.modules]
print(",".join(loaded), flush=True)
os._exit(0)
"""
    environment = os.environ.copy()
    environment["OTEL_SDK_DISABLED"] = "true"

    result = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
        env=environment,
    )

    assert result.stdout.strip() == ""


def test_main_uses_selector_event_loop_for_async_psycopg_on_windows(monkeypatch) -> None:
    policy = object()
    policy_factory = Mock(return_value=policy)
    set_policy = Mock()
    run_server = Mock()
    monkeypatch.setattr(job_bot.app_def.sys, "platform", "win32")
    monkeypatch.setattr(
        job_bot.app_def.asyncio,
        "WindowsSelectorEventLoopPolicy",
        policy_factory,
        raising=False,
    )
    monkeypatch.setattr(job_bot.app_def.asyncio, "set_event_loop_policy", set_policy)
    monkeypatch.setattr(job_bot.app_def.uvicorn, "run", run_server)

    job_bot.app_def.main()

    policy_factory.assert_called_once_with()
    set_policy.assert_called_once_with(policy)
    run_server.assert_called_once()
