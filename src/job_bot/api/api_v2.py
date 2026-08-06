from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from playwright.async_api import async_playwright
from sqlalchemy.orm import Session

from job_bot.api.dependencies import get_session
from job_bot.applier.greenhouse_applier import GreenHouseFiller
from job_bot.schemas import ApplicationFileSet
from job_bot.users import canonical_email, get_user, user_from_record
from job_bot.utils.file_tools import extract_uploadable_file

router = APIRouter(prefix="/apiv2", tags=["job_bot"])


@router.post("/apply")
async def inspect(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
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
