from __future__ import annotations

import os
from datetime import datetime
from logging import getLogger
from typing import Literal

from langchain.agents import create_agent
from langchain.messages import HumanMessage
from playwright.async_api import async_playwright
from pydantic import BaseModel, Field

from job_bot.applier import BrowserSession, build_browser_tools
from job_bot.llm import OpenAILLMProvider
from job_bot.openai_client import get_openai_client


class Interval(BaseModel):
    minimum: int
    maximum: int


class EducationDegree(BaseModel):
    degree: str
    field_of_study: str
    institution: str
    duration: Interval
    gpa: float


class CandidateProfile(BaseModel):
    name: str
    email: str
    phone: str
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None
    education: list[EducationDegree]
    resume_text: str
    require_sponsorship: bool = False
    summary: str


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
    extra_criteria: list[str] | None = None
    num_limit: int = 10


class ApplicationStatus(BaseModel):
    job: JobEntry
    status: Literal["applied", "failed"]
    message: str | None = None


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


def _build_search_prompt(query: JobQuery) -> str:
    min_pay, max_pay = query.pay_range.minimum, query.pay_range.maximum
    extra = ", ".join(query.extra_criteria or []) or "None"
    stack = ", ".join(query.key_words)
    return (
        f"Find at most {query.num_limit} job opportunities that match these criteria:\n"
        f"- Job title: {query.job_title}\n"
        f"- Years of experience: {query.year_of_experience.minimum} to "
        f"{query.year_of_experience.maximum}\n"
        f"- Location: {query.job_location}\n"
        f"- Pay range target: {min_pay} to {max_pay}\n"
        f"- Key words (match any): {stack}\n"
        f"- Posted since: {query.posted_since or 'Any time'}\n"
        "- Prefer high-tech and fortune 500 companies. Do not include jobs from staffing "
        "agencies or small unknown companies.\n"
        "- If a role has no explicit pay range, do not include it.\n"
        "- Only include jobs that are posted on the company's own official career website. Do not include jobs from job boards or aggregators.\n"
        "- Do not include jobs from startup companies or companies with less than 100 employees.\n"
        f"- Extra criteria: {extra}\n\n"
        "For each matching role, include:\n"
        "- job_title\n- url\n- year_of_experience\n- company_name\n"
        "- job_location\n- jd_summary\n- pay_range\n\n"
        "If pay range is not explicitly listed, skip the job.\n"
    )


def find_jobs(query: JobQuery) -> list[JobEntry]:
    model_name = os.getenv("JOB_BOT_LLM_MODEL", "gpt-5.4-nano")
    client = get_openai_client()
    prompt = _build_search_prompt(query)
    response = client.responses.parse(
        model=model_name,
        input=[
            {
                "role": "system",
                "content": (
                    f"{SYSTEM_PROMPT}\n\n"
                    "Return only JSON that matches the JobSearchResponse schema."
                ),
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


async def apply_job(job_url: str, candidate: CandidateProfile) -> dict[str, object]:
    """Run one browser-agent application attempt in an isolated browser context."""
    async with async_playwright() as playwright:
        session = BrowserSession(playwright=playwright, headless=False)
        await session.start()

        try:
            tools = build_browser_tools(session)
            model = OpenAILLMProvider().get_model()
            agent = create_agent(
                model=model,
                tools=tools,
                system_prompt=(
                    "You are a careful browser automation agent. Use only the supplied "
                    "candidate data. Inspect the page before interacting, never invent "
                    "answers, and report any missing required information. Before filling "
                    "a form, use browser_list_tabs and browser_list_frames, then inspect "
                    "the relevant frame with browser_inspect_form_controls. Use selectors "
                    "returned by that tool instead of guessing selectors. If a click opens "
                    "a new tab, list the tabs again and switch to the new tab. Use "
                    "browser_read_dom only when the structured form inspection does not "
                    "provide enough context. If the URL has expired, report it, do not "
                    "apply, and return a message indicating the job posting is no longer "
                    "available. Continue using the Playwright tools until the application "
                    "is submitted or progress requires missing candidate information."
                ),
            )

            prompt = (
                f"Open and apply to the job at {job_url}.\n\n"
                "Candidate profile:\n"
                f"{candidate.model_dump_json(indent=2)}\n\n"
                "Fill the application form using the candidate profile. Upload a resume "
                "only when a valid local resume file path is explicitly available in the "
                "profile or task context. Review the completed form before submitting."
            )
            return await agent.ainvoke(
                {"messages": [HumanMessage(content=prompt)]},
            )
        finally:
            await session.stop()


async def apply_jobs(query: JobQuery, candidate: CandidateProfile) -> list[ApplicationStatus]:
    jobs = find_jobs(query)
    status: list[ApplicationStatus] = []
    for job in jobs:
        try:
            resp = await apply_job(job.url, candidate)
            getLogger().info(resp)
        except Exception as exc:
            status.append(ApplicationStatus(job=job, status="failed", message=str(exc)))
            continue
        status.append(ApplicationStatus(job=job, status="applied"))

    return status
