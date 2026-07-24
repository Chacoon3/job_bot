from __future__ import annotations

import asyncio
import html
import re

import httpx
from bs4 import BeautifulSoup

from job_bot.greenhouse_discovery.models import CandidateToken, DiscoveredBoard

API_ROOT = "https://boards-api.greenhouse.io/v1/boards"


def _clean_title(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value).strip()
    suffixes = (
        " | Greenhouse",
        " - Greenhouse",
        " Jobs | Greenhouse",
        " Careers | Greenhouse",
    )
    for suffix in suffixes:
        if value.casefold().endswith(suffix.casefold()):
            value = value[: -len(suffix)].strip()
    return value


class GreenhouseVerifier:
    def __init__(
        self,
        client: httpx.AsyncClient,
        concurrency: int,
        include_empty_boards: bool,
    ) -> None:
        self.client = client
        self.semaphore = asyncio.Semaphore(concurrency)
        self.include_empty_boards = include_empty_boards

    async def verify(
        self,
        candidate: CandidateToken,
    ) -> tuple[DiscoveredBoard | None, str]:
        """
        Status values:
          valid
          invalid
          empty
        """
        token = candidate.token
        api_url = f"{API_ROOT}/{token}/jobs"

        async with self.semaphore:
            try:
                response = await self.client.get(
                    api_url,
                    params={"content": "false"},
                )
            except httpx.HTTPError:
                return None, "invalid"

        if response.status_code != 200:
            return None, "invalid"

        try:
            payload = response.json()
        except ValueError:
            return None, "invalid"

        jobs = payload.get("jobs")
        if not isinstance(jobs, list):
            return None, "invalid"

        if not jobs and not self.include_empty_boards:
            return None, "empty"

        titles = [
            str(job.get("title", "")).strip()
            for job in jobs[:5]
            if str(job.get("title", "")).strip()
        ]

        board = DiscoveredBoard(
            token=token,
            board_url=f"https://job-boards.greenhouse.io/{token}",
            api_url=api_url,
            active_job_count=len(jobs),
            sample_job_titles=titles,
            discovered_urls=candidate.discovered_urls[:20],
            crawl_indexes=candidate.crawl_indexes,
        )
        return board, "valid"


class BoardNameEnricher:
    def __init__(
        self,
        client: httpx.AsyncClient,
        concurrency: int,
    ) -> None:
        self.client = client
        self.semaphore = asyncio.Semaphore(concurrency)

    async def enrich(self, board: DiscoveredBoard) -> None:
        async with self.semaphore:
            try:
                response = await self.client.get(board.board_url)
            except httpx.HTTPError:
                return

        if response.status_code != 200:
            return

        soup = BeautifulSoup(response.text, "html.parser")

        candidates: list[str] = []
        for selector, attribute in (
            ('meta[property="og:title"]', "content"),
            ('meta[name="twitter:title"]', "content"),
        ):
            tag = soup.select_one(selector)
            if tag and tag.get(attribute):
                candidates.append(str(tag.get(attribute)))

        if soup.title and soup.title.string:
            candidates.append(soup.title.string)

        for raw in candidates:
            cleaned = _clean_title(raw)
            if cleaned and cleaned.casefold() not in {
                "greenhouse",
                "jobs",
                "careers",
            }:
                board.company_name = cleaned
                return
