from __future__ import annotations

import os
import re
from datetime import datetime

from openai import OpenAI
from playwright.sync_api import sync_playwright
from pydantic import BaseModel, Field


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


def _sync_playwright_session() -> object:
    return sync_playwright()


def _keyword_pattern(keywords: list[str]) -> re.Pattern[str]:
    escaped = [re.escape(keyword) for keyword in keywords if keyword]
    if not escaped:
        escaped = [r".*"]
    return re.compile("|".join(escaped), re.IGNORECASE)


def _try_action(locator: object, value: str | None = None, allow_check: bool = False) -> bool:
    if value is not None:
        for method_name, method_args in (("fill", (value,)), ("select_option", (),)):
            method = getattr(locator, method_name, None)
            if not callable(method):
                continue

            try:
                if method_name == "select_option":
                    method(label=value)
                else:
                    method(*method_args)
                return True
            except Exception:
                continue

    for method_name in (("check", "click") if allow_check else ("click",)):
        method = getattr(locator, method_name, None)
        if not callable(method):
            continue

        try:
            method()
            return True
        except Exception:
            continue

    return False


def _fill_field(page: object, keywords: list[str], value: str) -> bool:
    pattern = _keyword_pattern(keywords)
    locators = [
        page.get_by_label(pattern),
        page.get_by_placeholder(pattern),
        page.get_by_role("textbox", name=pattern),
        page.get_by_role("combobox", name=pattern),
    ]
    for locator in locators:
        first_locator = getattr(locator, "first", locator)
        if _try_action(first_locator, value):
            return True
    return False


def _click_match(page: object, role_names: list[str], keywords: list[str]) -> bool:
    pattern = _keyword_pattern(keywords)
    for role_name in role_names:
        locator = page.get_by_role(role_name, name=pattern)
        first_locator = getattr(locator, "first", locator)
        if _try_action(first_locator, allow_check=role_name in {"radio", "checkbox"}):
            return True
    return False


def _maybe_click_common_controls(page: object) -> None:
    for keywords in (
        ["Accept all"],
        ["Accept"],
        ["I agree"],
        ["Agree"],
        ["Close"],
        ["Got it"],
    ):
        _click_match(page, ["button", "link"], keywords)


def _education_summary(candidate: CandidateProfile) -> str:
    lines: list[str] = []
    for degree in candidate.education:
        lines.append(
            f"{degree.degree} in {degree.field_of_study} at {degree.institution} "
            f"({degree.duration.minimum}-{degree.duration.maximum}), GPA {degree.gpa}"
        )
    return "\n".join(lines)


def _apply_candidate_details(page: object, candidate: CandidateProfile) -> None:
    field_values = [
        (["name", "full name", "legal name"], candidate.name),
        (["email", "e-mail"], candidate.email),
        (["phone", "mobile", "telephone"], candidate.phone),
        (["linkedin", "linkedin url", "linkedin profile"], candidate.linkedin_url),
        (["github", "github url", "github profile"], candidate.github_url),
        (["portfolio", "portfolio url", "website", "personal website"], candidate.portfolio_url),
        (["resume", "cv", "cover letter", "summary", "about you"], candidate.resume_text),
        (
            ["education", "school", "university", "degree", "qualification"],
            _education_summary(candidate),
        ),
    ]

    for keywords, value in field_values:
        if value:
            _fill_field(page, keywords, value)

    sponsorship_keywords = [
        "visa sponsorship",
        "sponsorship",
        "work authorization",
        "work authorization status",
    ]
    sponsorship_answer = (
        ["yes", "required", "need sponsorship"]
        if candidate.require_sponsorship
        else ["no", "not required", "no sponsorship"]
    )
    _click_match(page, ["radio", "checkbox", "button"], sponsorship_keywords + sponsorship_answer)


def _submit_application(page: object) -> bool:
    for keywords in (
        ["submit application"],
        ["submit"],
        ["apply now"],
        ["apply"],
        ["send application"],
        ["finish"],
    ):
        if _click_match(page, ["button", "link"], keywords):
            return True
    return False


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


def _apply_job(job: JobEntry, candidate: CandidateProfile) -> None:
    with _sync_playwright_session() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 2000})
        page = context.new_page()

        try:
            page.goto(job.url, wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass

            _maybe_click_common_controls(page)
            _click_match(
                page,
                ["button", "link"],
                ["apply now", "apply", "start application", "continue"],
            )

            for _ in range(4):
                _apply_candidate_details(page, candidate)
                if _submit_application(page):
                    return
                if not _click_match(
                    page,
                    ["button", "link"],
                    ["next", "continue", "review", "save and continue"],
                ):
                    break

            raise RuntimeError(f"Could not complete the application flow for {job.url}")
        finally:
            context.close()
            browser.close()


def apply_jobs(query: JobQuery, candidate: CandidateProfile) -> list[JobEntry]:
    jobs = find_jobs(query)
    applied_jobs = []
    for job in jobs:
        # Simulate applying to the job (this is a placeholder for actual application logic)
        try:
            _apply_job(job, candidate)
        except Exception as e:
            print(f"Failed to apply for job {job.job_title} at {job.company_name}: {e}")
            continue
        applied_jobs.append(job)

    return applied_jobs
