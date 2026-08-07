from importlib import import_module
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from job_bot.api.dependencies import get_session, require_browser_automation
from job_bot.applications import run_application_once
from job_bot.schemas import ApplicationFileSet
from job_bot.users import canonical_email, get_user, user_from_record
from job_bot.utils.file_tools import extract_uploadable_file

router = APIRouter(prefix="/apiv2", tags=["job_bot"])


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


@router.post("/apply")
async def apply_job(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    _browser_enabled: Annotated[None, Depends(require_browser_automation)] = None,
) -> ApplicationAttemptResponse:
    form = await request.form()
    email = form.get("email")
    email = canonical_email(str(email))
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is required",
        )

    resume = await extract_uploadable_file(request, "resume")
    if not resume:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Resume is required",
        )

    cover_letter = await extract_uploadable_file(request, "cover_letter")

    application_file_set = ApplicationFileSet(resume=resume, cover_letter=cover_letter)

    job_url = form.get("job_url")
    if not job_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job URL is required",
        )
    job_url = str(job_url)

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
