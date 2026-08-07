from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, TypeVar

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.stdlib import get_logger

from job_bot.db.greenhouse_models import GreenhouseBoard
from job_bot.db.job_models import Job
from job_bot.db.upsert import batched_upsert
from job_bot.greenhouse.greenhouse import API_ROOT
from job_bot.job_providers.greenhouse_job_provider import GREENHOUSE_SOURCE

GREENHOUSE_JOB_MAX_AGE = timedelta(days=30)
JobEntryT = TypeVar("JobEntryT")


def _parse_datetime(raw_value: Any) -> datetime | None:
    """Parse provider timestamp values into timezone-aware UTC datetimes."""
    if raw_value is None:
        return None

    if isinstance(raw_value, datetime):
        if raw_value.tzinfo is None:
            return raw_value.replace(tzinfo=UTC)
        return raw_value.astimezone(UTC)

    if isinstance(raw_value, (int, float)):
        try:
            value = float(raw_value)
            # Some feeds publish Unix milliseconds while others use seconds.
            if abs(value) >= 1_000_000_000_000:
                value = value / 1000
            return datetime.fromtimestamp(value, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None

    if isinstance(raw_value, str):
        text = raw_value.strip()
        if not text:
            return None

        if text.isdigit():
            return _parse_datetime(int(text))

        normalized = text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    return None


@dataclass(frozen=True)
class GreenhouseJobSyncResult:
    boards_queried: int
    boards_failed: int
    jobs_found: int
    jobs_stored: int


class GreenhouseBoardSyncPolicy(StrEnum):
    """Define how boards are prioritized for a Greenhouse job sync."""

    RECENTLY_UPDATED = "recently_updated"
    MOST_JOBS = "most_jobs"
    FEWEST_JOBS = "fewest_jobs"
    RANDOM = "random"


class GreenhouseJobSyncService:
    """Fetch active Greenhouse boards and upsert normalized jobs into storage."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        client: httpx.Client | None = None,
        request_timeout_seconds: float = 30.0,
    ) -> None:
        self.session = session
        self.client = client
        self.request_timeout_seconds = request_timeout_seconds

    async def sync(
        self,
        *,
        policy: GreenhouseBoardSyncPolicy = GreenhouseBoardSyncPolicy.RECENTLY_UPDATED,
        board_limit: int | None = None,
        include_keywords: Sequence[str] = (),
        exclude_keywords: Sequence[str] = (),
    ) -> GreenhouseJobSyncResult:
        if board_limit is not None and board_limit < 1:
            raise ValueError("board_limit must be at least 1")

        order_by = {
            GreenhouseBoardSyncPolicy.RECENTLY_UPDATED: (
                GreenhouseBoard.updated_at.desc(),
                GreenhouseBoard.id.asc(),
            ),
            GreenhouseBoardSyncPolicy.MOST_JOBS: (
                GreenhouseBoard.active_job_count.desc(),
                GreenhouseBoard.id.asc(),
            ),
            GreenhouseBoardSyncPolicy.FEWEST_JOBS: (
                GreenhouseBoard.active_job_count.asc(),
                GreenhouseBoard.id.asc(),
            ),
            GreenhouseBoardSyncPolicy.RANDOM: (
                text("random()"),
            ),  # pyright: ignore[reportCallIssue]
        }[policy]
        statement = (
            select(GreenhouseBoard).where(GreenhouseBoard.active_job_count > 0).order_by(*order_by)
        )
        if board_limit is not None:
            statement = statement.limit(board_limit)

        boards = list((await self.session.execute(statement)).scalars().all())
        posted_after = datetime.now(UTC) - GREENHOUSE_JOB_MAX_AGE
        if self.client is not None:
            jobs, boards_failed = self._fetch_jobs(
                boards,
                self.client,
                posted_after=posted_after,
                include_keywords=include_keywords,
                exclude_keywords=exclude_keywords,
            )
        else:
            with httpx.Client(
                timeout=self.request_timeout_seconds,
                follow_redirects=True,
            ) as client:
                jobs, boards_failed = self._fetch_jobs(
                    boards,
                    client,
                    posted_after=posted_after,
                    include_keywords=include_keywords,
                    exclude_keywords=exclude_keywords,
                )

        jobs_stored = await self._upsert_jobs(jobs)
        return GreenhouseJobSyncResult(
            boards_queried=len(boards),
            boards_failed=boards_failed,
            jobs_found=len(jobs),
            jobs_stored=jobs_stored,
        )

    def pull_company_job_entries(
        self,
        company_token: str,
        *,
        transform: Callable[[dict[str, Any]], JobEntryT],
        client: httpx.Client | None = None,
    ) -> list[JobEntryT]:
        if client is not None:
            return self._pull_company_job_entries(
                company_token,
                client,
                transform=transform,
            )

        with httpx.Client(
            timeout=self.request_timeout_seconds,
            follow_redirects=True,
        ) as generated_client:
            return self._pull_company_job_entries(
                company_token,
                generated_client,
                transform=transform,
            )

    def _fetch_jobs(
        self,
        boards: list[GreenhouseBoard],
        client: httpx.Client,
        *,
        posted_after: datetime,
        include_keywords: Sequence[str] = (),
        exclude_keywords: Sequence[str] = (),
    ) -> tuple[list[Job], int]:
        jobs_by_url: dict[str, Job] = {}
        logger = get_logger(__name__)
        boards_failed = 0
        for board in boards:
            try:
                jobs = self.pull_company_job_entries(
                    board.token,
                    client=client,
                    transform=lambda raw_job, board=board: self.to_job_entry_record(
                        board,
                        raw_job,
                    ),
                )
            except (httpx.HTTPError, ValueError) as exc:
                boards_failed += 1
                logger.warning(
                    "greenhouse_jobs_request_failed",
                    board_token=board.token,
                    error_type=type(exc).__name__,
                )
                continue

            for job in jobs:
                if (
                    job is not None
                    and self._is_recent(job, posted_after)
                    and self._matches_keywords(
                        job,
                        include_keywords=include_keywords,
                        exclude_keywords=exclude_keywords,
                    )
                ):
                    jobs_by_url[job.url] = job
        return list(jobs_by_url.values()), boards_failed

    def _pull_company_job_entries(
        self,
        company_token: str,
        client: httpx.Client,
        *,
        transform: Callable[[dict[str, Any]], JobEntryT],
    ) -> list[JobEntryT]:
        response = client.get(f"{API_ROOT}/{company_token}/jobs", params={"content": "true"})
        response.raise_for_status()

        payload = response.json()
        raw_jobs = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(raw_jobs, list):
            raise ValueError("greenhouse jobs response was missing a jobs list")

        return [transform(raw_job) for raw_job in raw_jobs]

    @staticmethod
    def _is_recent(job: Job, posted_after: datetime) -> bool:
        return job.date_posted is not None and job.date_posted >= posted_after

    @staticmethod
    def _matches_keywords(
        job: Job,
        *,
        include_keywords: Sequence[str],
        exclude_keywords: Sequence[str],
    ) -> bool:
        title_text = job.job_title.casefold()
        searchable_text = " ".join(
            (job.job_title, job.company_name, job.job_location, job.jd_summary)
        ).casefold()
        included = tuple(
            keyword.strip().casefold() for keyword in include_keywords if keyword.strip()
        )
        excluded = tuple(
            keyword.strip().casefold() for keyword in exclude_keywords if keyword.strip()
        )
        if any(keyword in searchable_text for keyword in excluded):
            return False
        return not included or any(keyword in title_text for keyword in included)

    async def _upsert_jobs(self, jobs: list[Job]) -> int:
        values = (
            {
                "source": job.source,
                "job_title": job.job_title,
                "url": job.url,
                "company_name": job.company_name,
                "job_location": job.job_location,
                "jd_summary": job.jd_summary,
                "date_posted": job.date_posted,
            }
            for job in jobs
        )
        return await batched_upsert(
            self.session,
            Job,
            values,
            conflict_columns=[Job.url],
            update_columns=[
                Job.source,
                Job.job_title,
                Job.company_name,
                Job.job_location,
                Job.jd_summary,
                Job.date_posted,
                Job.updated_at,
            ],
        )

    @staticmethod
    def to_job_entry_record(
        board: GreenhouseBoard,
        raw_job: Any,
    ) -> Job | None:
        """Convert a public Greenhouse job payload into the normalized job model."""
        return GreenhouseJobSyncService._to_job_entry_record(board, raw_job)

    @staticmethod
    def _to_job_entry_record(
        board: GreenhouseBoard,
        raw_job: Any,
    ) -> Job | None:
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
        return Job(
            source=GREENHOUSE_SOURCE,
            job_title=title.strip(),
            url=url.strip(),
            company_name=board.company_name or board.token,
            job_location=str(location_name).strip(),
            jd_summary=summary,
            date_posted=_parse_datetime(raw_job.get("updated_at")),
        )
