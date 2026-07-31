import hashlib
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from playwright.async_api import async_playwright
from sqlalchemy.orm import Session

from job_bot.agent.planned_applier import agent_flow
from job_bot.agent.react_applier import apply_for_job
from job_bot.api.dependencies import get_session
from job_bot.db.app_redis import AppRedisAsync
from job_bot.llm import OpenAILLMProvider
from job_bot.schemas import User
from job_bot.users import canonical_email, get_user, user_from_record
from job_bot.utils.file_upload import extract_uploadable_file, parse_pure_text_pdf
from job_bot.utils.resume_parser import ai_parse_resume

router = APIRouter(prefix="/apiv2", tags=["job_bot"])


@router.post("/inspect")
async def inspect(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> Any:
    form = await request.form()
    email = form.get("email")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is required",
        )
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
        await agent_flow(job_url, playwright, user)

    # pause the execution


@router.post("/apply")
async def api_apply(request: Request):
    form = await request.form()
    job_url = form.get("job_url")
    uploadable = await extract_uploadable_file(request)
    # Read file content
    content = uploadable.content

    profile_hash = hashlib.sha256(content).hexdigest()

    profile_hash_key = f"resume:{profile_hash}"
    # check if the content has been processed before in redis
    profile_json = await AppRedisAsync.get(profile_hash_key)
    if profile_json:
        profile = User.model_validate_json(profile_json)
    else:
        if uploadable.filename.endswith(".pdf"):
            resume_str = parse_pure_text_pdf(content)
        # elif uploadable.filename.endswith((".doc", ".docx")):
        #     resume_str = parse_pure_text_word(content)
        else:
            return {"error": "Unsupported file type"}

        profile = ai_parse_resume(resume_str)
        await AppRedisAsync.set(profile_hash_key, profile.model_dump_json())

    res = await apply_for_job(job_url, profile, uploadable, model_provider=OpenAILLMProvider())
    return res
