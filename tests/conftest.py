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
