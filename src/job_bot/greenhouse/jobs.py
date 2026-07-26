from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range, insert
from sqlalchemy.orm import Session

from job_bot.db.greenhouse_models import GreenhouseBoard
from job_bot.db.job_models import JobEntryRecord
from job_bot.greenhouse_job_provider import GREENHOUSE_SOURCE
from job_bot.job_provider import _parse_datetime, logger


@dataclass(frozen=True)
class GreenhouseJobSyncResult:
    boards_queried: int
    boards_failed: int
    jobs_found: int
    jobs_stored: int


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

    def sync(self) -> GreenhouseJobSyncResult:
        boards = list(
            self.session.execute(
                select(GreenhouseBoard)
                .where(GreenhouseBoard.active_job_count > 0)
                .order_by(GreenhouseBoard.updated_at.desc(), GreenhouseBoard.id.asc())
            )
            .scalars()
            .all()
        )
        if self.client is not None:
            jobs, boards_failed = self._fetch_jobs(boards, self.client)
        else:
            with httpx.Client(
                timeout=self.request_timeout_seconds,
                follow_redirects=True,
            ) as client:
                jobs, boards_failed = self._fetch_jobs(boards, client)

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
    ) -> tuple[list[JobEntryRecord], int]:
        jobs_by_url: dict[str, JobEntryRecord] = {}
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
                if job is not None:
                    jobs_by_url[job.url] = job
        return list(jobs_by_url.values()), boards_failed

    def _upsert_jobs(self, jobs: list[JobEntryRecord]) -> int:
        if not jobs:
            return 0
        values = [
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
        ]
        statement = insert(JobEntryRecord).values(values)
        excluded = statement.excluded
        statement = statement.on_conflict_do_update(
            index_elements=[JobEntryRecord.url],
            set_={
                "source": excluded.source,
                "job_title": excluded.job_title,
                "year_of_experience": excluded.year_of_experience,
                "company_name": excluded.company_name,
                "job_location": excluded.job_location,
                "jd_summary": excluded.jd_summary,
                "pay_range": excluded.pay_range,
                "date_posted": excluded.date_posted,
                "updated_at": excluded.updated_at,
            },
        )
        self.session.execute(statement)
        return len(values)

    @staticmethod
    def _to_job_entry_record(
        board: GreenhouseBoard,
        raw_job: Any,
    ) -> JobEntryRecord | None:
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
        return JobEntryRecord(
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
