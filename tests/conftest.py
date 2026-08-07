"""Shared pytest setup for process-wide application state."""

import importlib
import os
import sys
from collections.abc import Iterator
from types import ModuleType
from unittest.mock import Mock

import pytest

# Application modules build the fail-open Redis cache at import time. Unit tests
# do not need a live Redis server, but they do need a syntactically valid URL.
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")


class _TelemetryStub(ModuleType):
    """Typed module stub used to prevent collection-time instrumentation."""

    configure_telemetry: Mock


# Telemetry config imports exporters and instrumentors and may initialize global
# OpenTelemetry state while application modules are collected. Replace the
# application telemetry module before any test imports job_bot.main.
_telemetry = _TelemetryStub("job_bot.telemetry")
_telemetry.configure_telemetry = Mock(name="configure_telemetry", return_value=False)
sys.modules["job_bot.telemetry"] = _telemetry


def _install_module_alias(alias: str, target: str) -> None:
    """Point a transitional import path at its canonical implementation."""
    sys.modules.setdefault(alias, importlib.import_module(target))


# Legacy module aliases retained for tests while imports are migrated.
_install_module_alias("job_bot.agent.fill_form_agent", "job_bot.agent.application_agent")
_install_module_alias("job_bot.agent.applier_agent", "job_bot.agent.application_agent")


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    """Let tests that modify environment variables observe fresh settings."""
    from job_bot.config import settings

    settings.cache_clear()
    yield
    settings.cache_clear()
