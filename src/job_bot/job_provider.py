from __future__ import annotations

from abc import ABC, abstractmethod

import structlog

from job_bot.db.job_models import JobEntry

logger = structlog.get_logger(__name__)


class JobProvider(ABC):
    """Provide normalized jobs from an external or persisted job source."""

    @abstractmethod
    def provide(self) -> list[JobEntry]:
        """Return the jobs currently available from this provider."""
