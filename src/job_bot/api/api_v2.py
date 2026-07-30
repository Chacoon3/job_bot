import hashlib

from fastapi import APIRouter, Request
from playwright.async_api import async_playwright

from job_bot.adapter.greenhouse import ApplicationDraft, GreenhouseAdapter, Upload
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


@router.post("/adapter/greenhouse")
async def greenhouse_adapter(request: Request) -> None:
    form = await request.form()
    job_url = form.get("job_url")
    resume = form.get("file")
    async with GreenhouseAdapter() as adapter:
        job = await adapter.get_job(job_url)

        # Give job.schema.model_dump(by_alias=True) to the answering layer. It
        # should return answers keyed by stable Greenhouse field names.
        draft = ApplicationDraft(
            answers={
                "first_name": "Ada",
                "last_name": "Lovelace",
                "email": "ada@example.com",
                "phone": "+1 555 010 1234",
                "question_12345": "Yes",  # A label or raw option value.
            },
            uploads={
                "resume": Upload(
                    filename="Ada-Lovelace-Resume.pdf",
                    mime_type="application/pdf",
                    content=resume.file.read(),
                )
            },
        )

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=False)
            page = await browser.new_page()

            # Fill and inspect first.
            filled = await adapter.fill_or_submit(page, job, draft, submit=False)
            print(filled.model_dump())

            # In a controlled workflow, call again with submit=True only after
            # approval. A production service should inject a persistent ledger.
            # submitted = await adapter.fill_or_submit(page, job, draft, submit=True)

            await browser.close()


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
