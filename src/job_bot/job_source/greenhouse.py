from __future__ import annotations

import asyncio
import html
import re
from dataclasses import dataclass
from typing import Any, Iterable

import httpx
from pydantic import BaseModel, ConfigDict, Field

GREENHOUSE_API_ROOT = "https://boards-api.greenhouse.io/v1/boards"


class Location(BaseModel):
    name: str = ""


class Department(BaseModel):
    id: int
    name: str


class Office(BaseModel):
    id: int
    name: str
    location: str | None = None


class GreenhouseJob(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    internal_job_id: int | None = None
    title: str
    updated_at: str | None = None
    requisition_id: str | None = None
    location: Location = Field(default_factory=Location)
    absolute_url: str
    language: str | None = None
    content: str | None = None
    departments: list[Department] = Field(default_factory=list)
    offices: list[Office] = Field(default_factory=list)

    @property
    def plain_description(self) -> str:
        if not self.content:
            return ""

        text = html.unescape(self.content)
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip()


class JobBoardResponse(BaseModel):
    jobs: list[GreenhouseJob]
    meta: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class JobSearch:
    keywords: tuple[str, ...] = ()
    locations: tuple[str, ...] = ()
    departments: tuple[str, ...] = ()
    exclude_keywords: tuple[str, ...] = ()
    require_all_keywords: bool = False


class GreenhouseClient:
    def __init__(
        self,
        timeout_seconds: float = 20.0,
        max_connections: int = 20,
    ) -> None:
        limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_connections,
        )

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            limits=limits,
            headers={
                "Accept": "application/json",
                "User-Agent": "job-search-agent/1.0",
            },
        )

    async def __aenter__(self) -> GreenhouseClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def list_jobs(
        self,
        board_token: str,
        include_content: bool = True,
    ) -> list[GreenhouseJob]:
        board_token = board_token.strip().lower()

        if not board_token:
            raise ValueError("board_token cannot be empty")

        url = f"{GREENHOUSE_API_ROOT}/{board_token}/jobs"

        response = await self._client.get(
            url,
            params={"content": str(include_content).lower()},
        )

        if response.status_code == 404:
            raise ValueError(f"Greenhouse board {board_token!r} was not found.")

        response.raise_for_status()

        payload = JobBoardResponse.model_validate(response.json())
        return payload.jobs

    async def search_board(
        self,
        board_token: str,
        search: JobSearch,
    ) -> list[GreenhouseJob]:
        jobs = await self.list_jobs(
            board_token=board_token,
            include_content=True,
        )

        return [job for job in jobs if matches(job, search)]

    async def search_boards(
        self,
        board_tokens: Iterable[str],
        search: JobSearch,
    ) -> dict[str, list[GreenhouseJob]]:
        tokens = list(dict.fromkeys(token.strip() for token in board_tokens))

        results = await asyncio.gather(
            *[self.search_board(board_token=token, search=search) for token in tokens],
            return_exceptions=True,
        )

        output: dict[str, list[GreenhouseJob]] = {}

        for token, result in zip(tokens, results, strict=True):
            if isinstance(result, Exception):
                print(f"Failed to search {token}: {result}")
                output[token] = []
            else:
                output[token] = result

        return output


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def contains_any(text: str, values: tuple[str, ...]) -> bool:
    normalized_text = normalize(text)
    return any(normalize(value) in normalized_text for value in values)


def contains_all(text: str, values: tuple[str, ...]) -> bool:
    normalized_text = normalize(text)
    return all(normalize(value) in normalized_text for value in values)


def matches(job: GreenhouseJob, search: JobSearch) -> bool:
    searchable_text = " ".join(
        [
            job.title,
            job.location.name,
            job.plain_description,
            *(department.name for department in job.departments),
            *(office.name for office in job.offices),
        ]
    )

    if search.exclude_keywords and contains_any(
        searchable_text,
        search.exclude_keywords,
    ):
        return False

    if search.keywords:
        keyword_match = (
            contains_all(searchable_text, search.keywords)
            if search.require_all_keywords
            else contains_any(searchable_text, search.keywords)
        )

        if not keyword_match:
            return False

    if search.locations and not contains_any(
        job.location.name,
        search.locations,
    ):
        return False

    department_text = " ".join(department.name for department in job.departments)

    if search.departments and not contains_any(
        department_text,
        search.departments,
    ):
        return False

    return True
