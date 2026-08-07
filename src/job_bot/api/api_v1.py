from datetime import datetime, timedelta
from importlib import import_module
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from job_bot.api.dependencies import get_session, require_browser_automation
from job_bot.applier.flow import (
    JobQuery,
    find_jobs,
)
from job_bot.data.schemas import JobEntrySchema, User
from job_bot.db.job_models import Job
from job_bot.db.upsert import batched_upsert

router = APIRouter(prefix="/api", tags=["job_bot"])


class _LazyAppRedisAsync:
    """Resolve the legacy Redis client only when resume caching is used."""

    async def get(self, key: str):
        client = import_module("job_bot.db.app_redis").AppRedisAsync
        return await client.get(key)

    async def set(self, key: str, value: str):
        client = import_module("job_bot.db.app_redis").AppRedisAsync
        return await client.set(key, value)


AppRedisAsync = _LazyAppRedisAsync()


def LLMJobProvider(*args, **kwargs):  # pylint: disable=invalid-name
    """Construct the legacy LLM job provider only for job-load requests."""
    provider_class = import_module("job_bot.job_providers.llm_job_provider").LLMJobProvider
    return provider_class(*args, **kwargs)


def OpenAILLMProvider(*args, **kwargs):  # pylint: disable=invalid-name
    """Construct the OpenAI provider without loading its SDK during startup."""
    provider_class = import_module("job_bot.llm").OpenAILLMProvider
    return provider_class(*args, **kwargs)


def parse_pure_text_pdf(content: bytes) -> str:
    return import_module("job_bot.utils.file_tools").parse_pure_text_pdf(content)


def ai_parse_resume(resume: str) -> User:
    return import_module("job_bot.utils.resume_parser").ai_parse_resume(resume)


class LoadJobQuery(BaseModel):
    company_names: list[str]
    earliest_post_date: datetime | None = None


@router.post("/jobs/load")
def load_jobs(
    query: LoadJobQuery,
    session: Annotated[Session, Depends(get_session)],
    _browser_enabled: Annotated[None, Depends(require_browser_automation)] = None,
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
