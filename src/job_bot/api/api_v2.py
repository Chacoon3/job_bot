import re
from datetime import UTC, date, datetime, time, timedelta
from importlib import import_module
from typing import Annotated, Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from job_bot.api.dependencies import get_session, require_browser_automation
from job_bot.applications import run_application_once
from job_bot.data.schemas import ApplicationFileSet, JobEntrySchema
from job_bot.db.greenhouse_models import GreenhouseBoard
from job_bot.greenhouse.jobs import GreenhouseJobSyncService
from job_bot.greenhouse.repository import list_boards
from job_bot.users import canonical_email, get_user, user_from_record
from job_bot.utils.file_tools import extract_uploadable_file

router = APIRouter(prefix="/apiv2/job", tags=["job_bot"])


class ApplicationAttemptResponse(BaseModel):
    attempt_id: UUID
    status: str
    attempt_number: int
    job_url: str
    executed: bool


def async_playwright() -> Any:
    """Load Playwright only for browser application requests."""
    return import_module("playwright.async_api").async_playwright()


def GreenHouseFiller(*args: Any, **kwargs: Any) -> Any:  # pylint: disable=invalid-name
    """Construct the Greenhouse filler without loading the agent graph at startup."""
    filler_class = import_module("job_bot.applier.greenhouse_applier").GreenHouseFiller
    return filler_class(*args, **kwargs)


def _greenhouse_token_from_company_name(company_name: str) -> str:
    """Build Greenhouse's common compact board-token form from a company name."""
    return re.sub(r"[^a-z0-9]+", "", company_name.casefold())


def _fallback_greenhouse_board(company_name: str) -> GreenhouseBoard:
    token = _greenhouse_token_from_company_name(company_name)
    return GreenhouseBoard(
        token=token,
        company_name=company_name,
        board_url=f"https://job-boards.greenhouse.io/{token}",
        api_url=f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
        active_job_count=0,
        sample_job_titles=[],
        discovered_urls=[],
        crawl_indexes=[],
        verified_at=datetime.now(UTC),
    )


@router.get("/")
async def get_company_jobs(
    session: Annotated[Session, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    company_names: Annotated[str | None, Query()] = None,
    posted_after: Annotated[
        date | None,
        Query(description="Only return jobs posted on or after this UTC date."),
    ] = None,
) -> list[JobEntrySchema]:
    """Fetch recent jobs from requested Greenhouse companies or three random boards."""
    company_names_list = (
        [name.strip() for name in company_names.split(",") if name.strip()]
        if company_names
        else None
    )
    if company_names is not None and not company_names_list:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="company_names is empty"
        )

    if company_names_list:
        boards_by_token: dict[str, GreenhouseBoard] = {}
        for company_name in company_names_list:
            boards, _ = list_boards(
                session,
                company_name=company_name,
                limit=50,
            )
            if not boards:
                boards = [_fallback_greenhouse_board(company_name)]
            boards_by_token.update({board.token: board for board in boards})
        boards = list(boards_by_token.values())
    else:
        boards = list(
            session.execute(
                select(GreenhouseBoard)
                .where(GreenhouseBoard.active_job_count > 0)
                .order_by(func.random())
                .limit(3)
            )
            .scalars()
            .all()
        )

    effective_posted_after = posted_after or (date.today() - timedelta(days=30))
    posted_after_at = datetime.combine(effective_posted_after, time.min, tzinfo=UTC)
    service = GreenhouseJobSyncService(session)
    jobs = []
    for board in boards:
        try:
            entries = service.pull_company_job_entries(
                board.token,
                transform=lambda raw_job, board=board: service.to_job_entry_record(board, raw_job),
            )
        except (httpx.HTTPError, ValueError):
            # One unavailable Greenhouse board should not hide the others.
            continue
        jobs.extend(
            JobEntrySchema.from_orm_model(job)
            for job in entries
            if job is not None
            and job.date_posted is not None
            and job.date_posted >= posted_after_at
        )

    return sorted(
        jobs, key=lambda job: job.date_posted or datetime.min.replace(tzinfo=UTC), reverse=True
    )[:limit]


@router.post("/apply")
async def apply_job(
    session: Annotated[Session, Depends(get_session)],
    email: Annotated[str | None, Form()] = None,
    resume: Annotated[UploadFile | None, File()] = None,
    cover_letter: Annotated[UploadFile | None, File()] = None,
    job_url: Annotated[str | None, Form()] = None,
    _browser_enabled: Annotated[None, Depends(require_browser_automation)] = None,
) -> ApplicationAttemptResponse:
    email = canonical_email(email or "")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is required",
        )

    resume_file = await extract_uploadable_file(resume)
    if not resume_file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Resume is required",
        )

    cover_letter_file = await extract_uploadable_file(cover_letter)

    application_file_set = ApplicationFileSet(
        resume=resume_file,
        cover_letter=cover_letter_file,
    )

    if not job_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job URL is required",
        )

    user_record = get_user(session, email)
    if user_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    user = user_from_record(user_record)

    async def apply() -> None:
        async with async_playwright() as playwright:
            filler = GreenHouseFiller(playwright, user, job_url, application_file_set)
            await filler.apply()

    try:
        run = await run_application_once(
            session,
            user_id=user_record.id,
            job_url=job_url,
            operation=apply,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if run.reason == "in_progress":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "An application attempt is already in progress",
                "attempt_id": str(run.attempt.attempt_id),
            },
        )

    return ApplicationAttemptResponse(
        attempt_id=run.attempt.attempt_id,
        status=run.attempt.status,
        attempt_number=run.attempt.attempt_number,
        job_url=run.attempt.job_url,
        executed=run.executed,
    )
