from __future__ import annotations

import os
import subprocess
import sys


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
