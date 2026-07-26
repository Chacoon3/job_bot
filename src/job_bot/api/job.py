import hashlib
from datetime import datetime, timedelta

from fastapi import APIRouter, Request

from job_bot.db.app_redis import AppRedisAsync
from job_bot.db.job_models import JobEntry
from job_bot.flow import (
    ApplicationStatus,
    CandidateProfile,
    JobQuery,
    apply_job,
    apply_jobs,
    find_jobs,
)
from job_bot.resume_parser import parse_resume
from job_bot.utils.file_upload import parse_pure_text_pdf

router = APIRouter(prefix="/api", tags=["job_bot"])


@router.get("/")
def root() -> dict[str, str]:
    return {"service": "job_bot", "status": "ok"}


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}


@router.get("/find_jobs")
def api_find_jobs() -> list[JobEntry]:

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


@router.post("/candidate_profile")
async def candidate_profile(request: Request) -> dict[str, str]:
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

    # Convert to string and generate candidate profile
    profile = CandidateProfile.from_document(content, filename)

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
        profile = CandidateProfile.model_validate_json(profile_json)
    else:
        if filename.endswith(".pdf"):
            resume_str = parse_pure_text_pdf(content)
        # elif filename.endswith((".doc", ".docx")):
        #     resume_str = parse_pure_text_word(content)
        else:
            return {"error": "Unsupported file type"}

        profile = parse_resume(resume_str)
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
        profile = CandidateProfile.model_validate_json(profile_json)
    else:
        if filename.endswith(".pdf"):
            resume_str = parse_pure_text_pdf(content)
        # elif filename.endswith((".doc", ".docx")):
        #     resume_str = parse_pure_text_word(content)
        else:
            return {"error": "Unsupported file type"}

        profile = parse_resume(resume_str)
        await AppRedisAsync.set(profile_hash_key, profile.model_dump_json())

    jobs = await apply_jobs(criteria, profile)
    return jobs
