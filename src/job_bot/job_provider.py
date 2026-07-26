from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import structlog

from job_bot.flow import JobEntry

logger = structlog.get_logger(__name__)


class JobProvider(ABC):
    """Provide normalized jobs from an external or persisted job source."""

    @abstractmethod
    def provide(self) -> list[JobEntry]:
        """Return the jobs currently available from this provider."""


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def __getattr__(name: str) -> Any:
    """Keep the historical provider import available without a module cycle."""
    if name == "GreenHouseJobProvider":
        from job_bot.greenhouse_job_provider import GreenHouseJobProvider

        return GreenHouseJobProvider
    raise AttributeError(name)
