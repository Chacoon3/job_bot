import hashlib
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from job_bot.api.dependencies import get_session
from job_bot.applier.flow import (
    ApplicationStatus,
    JobQuery,
    apply_job,
    apply_jobs,
    find_jobs,
)
from job_bot.db.app_redis import AppRedisAsync
from job_bot.db.job_models import Job
from job_bot.db.upsert import batched_upsert
from job_bot.job_providers.llm_job_provider import LLMJobProvider
from job_bot.llm import OpenAILLMProvider
from job_bot.schemas import JobEntrySchema, User
from job_bot.utils.file_tools import parse_pure_text_pdf
from job_bot.utils.resume_parser import ai_parse_resume

router = APIRouter(prefix="/api", tags=["job_bot"])


class LoadJobQuery(BaseModel):
    company_names: list[str]
    earliest_post_date: datetime | None = None


@router.get("/")
def root() -> dict[str, str]:
    return {"service": "job_bot", "status": "ok"}


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}


@router.post("/jobs/load")
def load_jobs(
    query: LoadJobQuery, session: Annotated[Session, Depends(get_session)]
) -> list[JobEntrySchema]:
    job_provider = LLMJobProvider(
        company_names=query.company_names,
        llm_provider=OpenAILLMProvider(),
        earliest_post_date=query.earliest_post_date or datetime.now() - timedelta(days=30),
    )
    jobs = job_provider.provide()
    jobs = [job.model_copy(update={"source": "llm"}) for job in jobs]
    records = [job.to_orm_model() for job in jobs]
    batched_upsert(
        session,
        Job,
        (
            {
                "source": record.source,
                "job_title": record.job_title,
                "url": record.url,
                "company_name": record.company_name,
                "job_location": record.job_location,
                "jd_summary": record.jd_summary,
                "date_posted": record.date_posted,
            }
            for record in records
        ),
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
    session.commit()

    return jobs


@router.get("/find_jobs")
def api_find_jobs() -> list[JobEntrySchema]:

    criteria = JobQuery(
        job_title="Software Engineer",
        year_of_experience_minimum=1,
        year_of_experience_maximum=4,
        job_location="United States",
        pay_range_minimum=130000,
        pay_range_maximum=180000,
        key_words=["Python", "C#", "Cloud", "Agents", "LangChain", "Backend"],
        posted_since=datetime.now() - timedelta(days=30),
    )

    jobs = find_jobs(criteria)
    return jobs


@router.post("/user")
async def user(request: Request) -> dict[str, str]:
    form = await request.form()
    uploaded_file = form.get("file")

    if not uploaded_file:
        return {"error": "No file uploaded"}

    # Check if file is PDF or Word document
    filename = uploaded_file.filename
    if not (filename.endswith(".pdf") or filename.endswith((".doc", ".docx"))):
        return {"error": "File must be PDF or Word document"}

    # Read file content
    content = await uploaded_file.read()

    # Convert to string and generate a user profile.
    profile = User.from_document(content, filename)

    return {"profile": str(profile)}


@router.post("/apply")
async def api_apply(request: Request) -> ApplicationStatus:
    form = await request.form()
    uploaded_file = form.get("file")
    job_url = form.get("job_url")

    if not uploaded_file:
        return {"error": "No file uploaded"}

    # Check if file is PDF or Word document
    filename = uploaded_file.filename
    if not (filename.endswith(".pdf") or filename.endswith((".doc", ".docx"))):
        return {"error": "File must be PDF or Word document"}

    # Read file content
    content = await uploaded_file.read()

    profile_hash = hashlib.sha256(content).hexdigest()

    profile_hash_key = f"resume:{profile_hash}"
    # check if the content has been processed before in redis
    profile_json = await AppRedisAsync.get(profile_hash_key)
    if profile_json:
        profile = User.model_validate_json(profile_json)
    else:
        if filename.endswith(".pdf"):
            resume_str = parse_pure_text_pdf(content)
        # elif filename.endswith((".doc", ".docx")):
        #     resume_str = parse_pure_text_word(content)
        else:
            return {"error": "Unsupported file type"}

        profile = ai_parse_resume(resume_str)
        await AppRedisAsync.set(profile_hash_key, profile.model_dump_json())

    status = await apply_job(job_url, profile)
    return status


@router.post("/find_and_apply")
async def api_apply_jobs(request: Request) -> list[ApplicationStatus]:

    criteria = JobQuery(
        job_title="Software Engineer",
        year_of_experience_minimum=1,
        year_of_experience_maximum=4,
        job_location="United States",
        pay_range_minimum=130000,
        pay_range_maximum=180000,
        key_words=["Python", "C#", "Cloud", "Agents", "LangChain", "Backend"],
        posted_since=datetime.now() - timedelta(days=30),
    )

    form = await request.form()
    uploaded_file = form.get("file")

    if not uploaded_file:
        return {"error": "No file uploaded"}

    # Check if file is PDF or Word document
    filename = uploaded_file.filename
    if not (filename.endswith(".pdf") or filename.endswith((".doc", ".docx"))):
        return {"error": "File must be PDF or Word document"}

    # Read file content
    content = await uploaded_file.read()

    profile_hash = hashlib.sha256(content).hexdigest()

    profile_hash_key = f"resume:{profile_hash}"
    # check if the content has been processed before in redis
    profile_json = await AppRedisAsync.get(profile_hash_key)
    if profile_json:
        profile = User.model_validate_json(profile_json)
    else:
        if filename.endswith(".pdf"):
            resume_str = parse_pure_text_pdf(content)
        # elif filename.endswith((".doc", ".docx")):
        #     resume_str = parse_pure_text_word(content)
        else:
            return {"error": "Unsupported file type"}

        profile = ai_parse_resume(resume_str)
        await AppRedisAsync.set(profile_hash_key, profile.model_dump_json())

    jobs = await apply_jobs(criteria, profile)
    return jobs
