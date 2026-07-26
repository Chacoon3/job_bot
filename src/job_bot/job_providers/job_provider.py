from __future__ import annotations

from abc import ABC, abstractmethod

import structlog

from job_bot.schemas import JobEntrySchema

logger = structlog.get_logger(__name__)


class JobProvider(ABC):
    """Provide normalized jobs from an external or persisted job source."""

    @abstractmethod
    def provide(self) -> list[JobEntrySchema]:
        """Return the jobs currently available from this provider."""
