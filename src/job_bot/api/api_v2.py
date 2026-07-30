import hashlib

from fastapi import APIRouter, Request

from job_bot.agent.planned_applier import inspect_page
from job_bot.agent.react_applier import apply_for_job
from job_bot.db.app_redis import AppRedisAsync
from job_bot.llm import OpenAILLMProvider
from job_bot.schemas import CandidateProfile
from job_bot.utils.file_upload import extract_uploadable_file, parse_pure_text_pdf
from job_bot.utils.resume_parser import ai_parse_resume

router = APIRouter(prefix="/apiv2", tags=["job_bot"])


@router.post("/inspect")
async def inspect(request: Request) -> dict:
    form = await request.form()
    job_url = form.get("job_url")
    return await inspect_page(job_url)


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
        profile = CandidateProfile.model_validate_json(profile_json)
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
