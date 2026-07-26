from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.orm import Session

from job_bot.db.greenhouse_models import GreenhouseBoard
from job_bot.db.job_models import JobEntry
from job_bot.db.upsert import batched_upsert
from job_bot.greenhouse_job_provider import GREENHOUSE_SOURCE
from job_bot.job_provider import logger

GREENHOUSE_JOB_MAX_AGE = timedelta(days=30)


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
        session: Session,
        *,
        client: httpx.Client | None = None,
        request_timeout_seconds: float = 30.0,
    ) -> None:
        self.session = session
        self.client = client
        self.request_timeout_seconds = request_timeout_seconds

    def sync(
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
            GreenhouseBoardSyncPolicy.RANDOM: (func.random(),),
        }[policy]
        statement = (
            select(GreenhouseBoard).where(GreenhouseBoard.active_job_count > 0).order_by(*order_by)
        )
        if board_limit is not None:
            statement = statement.limit(board_limit)

        boards = list(self.session.execute(statement).scalars().all())
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

        jobs_stored = self._upsert_jobs(jobs)
        return GreenhouseJobSyncResult(
            boards_queried=len(boards),
            boards_failed=boards_failed,
            jobs_found=len(jobs),
            jobs_stored=jobs_stored,
        )

    def _fetch_jobs(
        self,
        boards: list[GreenhouseBoard],
        client: httpx.Client,
        *,
        posted_after: datetime,
        include_keywords: Sequence[str] = (),
        exclude_keywords: Sequence[str] = (),
    ) -> tuple[list[JobEntry], int]:
        jobs_by_url: dict[str, JobEntry] = {}
        boards_failed = 0
        for board in boards:
            try:
                response = client.get(board.api_url, params={"content": "true"})
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                boards_failed += 1
                logger.warning(
                    "greenhouse_jobs_request_failed",
                    board_token=board.token,
                    error_type=type(exc).__name__,
                )
                continue

            raw_jobs = payload.get("jobs") if isinstance(payload, dict) else None
            if not isinstance(raw_jobs, list):
                boards_failed += 1
                logger.warning("greenhouse_jobs_response_invalid", board_token=board.token)
                continue

            for raw_job in raw_jobs:
                job = self._to_job_entry_record(board, raw_job)
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

    @staticmethod
    def _is_recent(job: JobEntry, posted_after: datetime) -> bool:
        return job.date_posted is not None and job.date_posted >= posted_after

    @staticmethod
    def _matches_keywords(
        job: JobEntry,
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

    def _upsert_jobs(self, jobs: list[JobEntry]) -> int:
        values = (
            {
                "source": job.source,
                "job_title": job.job_title,
                "url": job.url,
                "year_of_experience": job.year_of_experience,
                "company_name": job.company_name,
                "job_location": job.job_location,
                "jd_summary": job.jd_summary,
                "pay_range": job.pay_range,
                "date_posted": job.date_posted,
            }
            for job in jobs
        )
        return batched_upsert(
            self.session,
            JobEntry,
            values,
            conflict_columns=[JobEntry.url],
            update_columns=[
                JobEntry.source,
                JobEntry.job_title,
                JobEntry.year_of_experience,
                JobEntry.company_name,
                JobEntry.job_location,
                JobEntry.jd_summary,
                JobEntry.pay_range,
                JobEntry.date_posted,
                JobEntry.updated_at,
            ],
        )

    @staticmethod
    def _to_job_entry_record(
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
            source=GREENHOUSE_SOURCE,
            job_title=title.strip(),
            url=url.strip(),
            year_of_experience=Range(0, 0, bounds="[]"),
            company_name=board.company_name or board.token,
            job_location=str(location_name).strip(),
            jd_summary=summary,
            pay_range=Range(0, 0, bounds="[]"),
            date_posted=_parse_datetime(raw_job.get("updated_at")),
        )
