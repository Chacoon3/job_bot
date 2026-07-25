from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import httpx
import structlog
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from job_bot.db.greenhouse_models import GreenhouseBoard
from job_bot.flow import Interval, JobEntry

logger = structlog.get_logger(__name__)


class JobProvider(ABC):
    """Provide normalized jobs from an external or persisted job source."""

    @abstractmethod
    def provide(self) -> list[JobEntry]:
        """Return the jobs currently available from this provider."""


class GreenHouseJobProvider(JobProvider):
    """Fetch current jobs for active boards persisted by Greenhouse discovery."""

    def __init__(
        self,
        session: Session,
        *,
        client: httpx.Client | None = None,
        request_timeout_seconds: float = 30.0,
    ) -> None:
        self.session = session
        self.client = client
        self.request_timeout_seconds = request_timeout_seconds

    def provide(self) -> list[JobEntry]:
        boards = (
            self.session.execute(
                select(GreenhouseBoard)
                .where(GreenhouseBoard.active_job_count > 0)
                .order_by(GreenhouseBoard.updated_at.desc(), GreenhouseBoard.id.asc())
            )
            .scalars()
            .all()
        )

        if self.client is not None:
            return self._fetch_jobs(boards, self.client)

        with httpx.Client(timeout=self.request_timeout_seconds, follow_redirects=True) as client:
            return self._fetch_jobs(boards, client)

    def _fetch_jobs(
        self,
        boards: list[GreenhouseBoard],
        client: httpx.Client,
    ) -> list[JobEntry]:
        jobs: list[JobEntry] = []
        seen_urls: set[str] = set()

        for board in boards:
            try:
                response = client.get(board.api_url, params={"content": "true"})
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning(
                    "greenhouse_jobs_request_failed",
                    board_token=board.token,
                    error_type=type(exc).__name__,
                )
                continue

            raw_jobs = payload.get("jobs")
            if not isinstance(raw_jobs, list):
                logger.warning(
                    "greenhouse_jobs_response_invalid",
                    board_token=board.token,
                )
                continue

            for raw_job in raw_jobs:
                job = self._to_job_entry(board, raw_job)
                if job is None or job.url in seen_urls:
                    continue
                seen_urls.add(job.url)
                jobs.append(job)

        return jobs

    @staticmethod
    def _to_job_entry(
        board: GreenhouseBoard,
        raw_job: Any,
    ) -> JobEntry | None:
        if not isinstance(raw_job, dict):
            return None

        title = raw_job.get("title")
        url = raw_job.get("absolute_url")
        if not isinstance(title, str) or not title.strip():
            return None
        if not isinstance(url, str) or not url.strip():
            return None

        location = raw_job.get("location")
        location_name = location.get("name", "") if isinstance(location, dict) else ""
        content = raw_job.get("content", "")
        summary = (
            BeautifulSoup(content, "html.parser").get_text(" ", strip=True)
            if isinstance(content, str)
            else ""
        )

        return JobEntry(
            job_title=title.strip(),
            url=url.strip(),
            year_of_experience=Interval(minimum=0, maximum=0),
            company_name=board.company_name or board.token,
            job_location=str(location_name).strip(),
            jd_summary=summary,
            pay_range=Interval(minimum=0, maximum=0),
            date_posted=_parse_datetime(raw_job.get("updated_at")),
        )


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
