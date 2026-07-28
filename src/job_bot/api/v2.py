import hashlib

from fastapi import APIRouter, Request

from job_bot.agent.react_applier import apply_for_job
from job_bot.db.app_redis import AppRedisAsync
from job_bot.llm import OpenAILLMProvider
from job_bot.resume_parser import parse_resume
from job_bot.schemas import CandidateProfile
from job_bot.utils.file_upload import parse_pure_text_pdf

router = APIRouter(prefix="/apiv2", tags=["job_bot"])


@router.post("/apply")
async def api_apply(request: Request):
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

    res = await apply_for_job(
        job_url, profile, content, parse_pure_text_pdf(content), model_provider=OpenAILLMProvider()
    )
    return res
