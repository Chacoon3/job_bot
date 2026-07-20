import os
from typing import Any, Optional

from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel


class JobEntry(BaseModel):
    job_title: str
    url: str
    year_of_experience: int
    company_name: str
    job_location: str
    jd_summary: str
    pay_range: tuple[int, int]


class JobSearchCriteria(BaseModel):
    job_title: str
    year_of_experience: int
    job_location: str
    pay_range: tuple[int, int]
    tech_stack: list[str]
    extra_criteria: Optional[list[str]] = None


class JobSearchResponse(BaseModel):
    jobs: list[JobEntry]


SYSTEM_PROMPT = """
You are an expert technical recruiter assistant.
Your task is to find currently relevant job postings from the web.

Rules:
- Use the search tool multiple times with varied queries.
- Focus on real jobs with direct posting URLs.
- Prefer jobs that match title, location, experience, and tech stack.
- Return only factual information supported by the sources.
""".strip()


def _require_env_var(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return str(content)


def _build_search_prompt(criteria: JobSearchCriteria) -> str:
    min_pay, max_pay = criteria.pay_range
    extra = ", ".join(criteria.extra_criteria or []) or "None"
    stack = ", ".join(criteria.tech_stack)
    return (
        "Find job opportunities that match these criteria:\n"
        f"- Job title: {criteria.job_title}\n"
        f"- Years of experience: {criteria.year_of_experience}\n"
        f"- Location: {criteria.job_location}\n"
        f"- Pay range target: {min_pay} to {max_pay}\n"
        f"- Tech stack: {stack}\n"
        f"- Extra criteria: {extra}\n\n"
        "For each matching role, include:\n"
        "- job_title\n- url\n- year_of_experience\n- company_name\n"
        "- job_location\n- jd_summary\n- pay_range\n\n"
        "If pay range is not explicitly listed, infer an estimated range and note that in jd_summary."
    )


def find_jobs(criteria: JobSearchCriteria) -> list[JobEntry]:
    _require_env_var("OPENAI_API_KEY")
    _require_env_var("TAVILY_API_KEY")

    model_name = os.getenv("JOB_BOT_LLM_MODEL", "gpt-4o-mini")
    llm = ChatOpenAI(model=model_name, temperature=0)
    search_tool = TavilySearchResults(max_results=8)

    agent = create_react_agent(model=llm, tools=[search_tool], prompt=SYSTEM_PROMPT)
    agent_result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": _build_search_prompt(criteria),
                }
            ]
        }
    )

    final_message = agent_result["messages"][-1]
    research_notes = _message_content_to_text(final_message.content)

    extractor = llm.with_structured_output(JobSearchResponse)
    structured = extractor.invoke(
        [
            (
                "system",
                "Extract validated job entries from research notes. "
                "Only include postings that are likely real and have a URL.",
            ),
            (
                "user",
                "Search criteria:\n"
                f"{criteria.model_dump_json(indent=2)}\n\n"
                "Research notes:\n"
                f"{research_notes}",
            ),
        ]
    )
    return structured.jobs
