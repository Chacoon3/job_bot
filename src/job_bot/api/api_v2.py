from importlib import import_module
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from job_bot.api.dependencies import get_session, require_browser_automation
from job_bot.schemas import ApplicationFileSet
from job_bot.users import canonical_email, get_user, user_from_record
from job_bot.utils.file_tools import extract_uploadable_file

router = APIRouter(prefix="/apiv2", tags=["job_bot"])


def async_playwright() -> Any:
    """Load Playwright only for browser application requests."""
    return import_module("playwright.async_api").async_playwright()


def GreenHouseFiller(*args: Any, **kwargs: Any) -> Any:  # pylint: disable=invalid-name
    """Construct the Greenhouse filler without loading the agent graph at startup."""
    filler_class = import_module("job_bot.applier.greenhouse_applier").GreenHouseFiller
    return filler_class(*args, **kwargs)


@router.post("/apply")
async def inspect(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    _browser_enabled: Annotated[None, Depends(require_browser_automation)] = None,
) -> Any:
    form = await request.form()
    email = form.get("email")
    resume = await extract_uploadable_file(request, "resume")
    if not resume:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Resume is required",
        )
    cover_letter = await extract_uploadable_file(request, "cover_letter")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is required",
        )
    application_file_set = ApplicationFileSet(resume=resume, cover_letter=cover_letter)
    email = canonical_email(str(email))
    job_url = form.get("job_url")
    record = get_user(session, email)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    user = user_from_record(record)

    async with async_playwright() as playwright:
        filler = GreenHouseFiller(playwright, user, job_url, application_file_set)
        await filler.apply()
    # pause the execution
