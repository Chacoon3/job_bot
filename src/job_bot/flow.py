import os
from datetime import datetime
from typing import Optional

from openai import OpenAI
from pydantic import BaseModel, Field


class Interval(BaseModel):
    minimum: int
    maximum: int


class JobEntry(BaseModel):
    job_title: str
    url: str
    year_of_experience: Interval
    company_name: str
    job_location: str
    jd_summary: str
    pay_range: Interval


class JobQuery(BaseModel):
    job_title: str
    year_of_experience: Interval
    job_location: str
    pay_range: Interval
    key_words: list[str]
    posted_since: datetime | None = None
    extra_criteria: Optional[list[str]] = None
    num_limit: int = 10


class JobSearchResponse(BaseModel):
    jobs: list[JobEntry] = Field(default_factory=list)


SYSTEM_PROMPT = """
You are an expert technical recruiter assistant.
Your task is to find currently relevant job postings from the web.

Rules:
- Use web search multiple times with varied queries.
- Focus on real jobs with direct posting URLs.
- Prefer jobs that match title, location, experience, and tech stack.
- Return only factual information supported by the sources.
""".strip()


def _require_env_var(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _build_search_prompt(query: JobQuery) -> str:
    min_pay, max_pay = query.pay_range.minimum, query.pay_range.maximum
    extra = ", ".join(query.extra_criteria or []) or "None"
    stack = ", ".join(query.key_words)
    return (
        f"Find at most {query.num_limit} job opportunities that match these criteria:\n"
        f"- Job title: {query.job_title}\n"
        f"- Years of experience: {query.year_of_experience.minimum} to {query.year_of_experience.maximum}\n"
        f"- Location: {query.job_location}\n"
        f"- Pay range target: {min_pay} to {max_pay}\n"
        f"- Key words (match any): {stack}\n"
        f"- Posted since: {query.posted_since or 'Any time'}\n"
        "- Prefer high-tech and fortune 500 companies. Do not include jobs from staffing agencies or small unknown companies.\n"
        "- If a role has no explicit pay range, do not include it.\n"
        "- Do not include jobs from startup companies or companies with less than 100 employees.\n"
        f"- Extra criteria: {extra}\n\n"
        "For each matching role, include:\n"
        "- job_title\n- url\n- year_of_experience\n- company_name\n"
        "- job_location\n- jd_summary\n- pay_range\n\n"
        "If pay range is not explicitly listed, skip the job.\n"
    )


def find_jobs(query: JobQuery) -> list[JobEntry]:
    api_key = _require_env_var("OPENAI_API_KEY")
    model_name = os.getenv("JOB_BOT_LLM_MODEL", "gpt-5.4-nano")
    client = OpenAI(api_key=api_key)
    prompt = _build_search_prompt(query)
    response = client.responses.parse(
        model=model_name,
        input=[
            {
                "role": "system",
                "content": f"""{SYSTEM_PROMPT}\n\nReturn only JSON that matches the JobSearchResponse schema.""",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        tools=[{"type": "web_search"}],
        text_format=JobSearchResponse,
    )

    structured: JobSearchResponse = response.output_parsed
    if not isinstance(structured, JobSearchResponse):
        raise RuntimeError(f"Unexpected response type: {type(structured)}. Actual: {structured}")
    return structured.jobs
