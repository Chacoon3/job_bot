import importlib
import os
import sys
from types import ModuleType
from unittest.mock import Mock

# Application modules build the fail-open Redis cache at import time. Unit tests
# do not need a live Redis server, but they do need a syntactically valid URL.
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

# Telemetry config imports exporters and instrumentors and may initialize global
# OpenTelemetry state while application modules are collected. Replace the
# application telemetry module before any test imports job_bot.main.
telemetry = ModuleType("job_bot.telemetry")
telemetry.configure_telemetry = Mock(return_value=False)  # type: ignore[attr-defined]
sys.modules["job_bot.telemetry"] = telemetry

# Legacy module alias retained for tests while imports are migrated.
sys.modules.setdefault(
    "job_bot.agent.applier_agent",
    importlib.import_module("job_bot.agent.fill_form_agent"),
)
