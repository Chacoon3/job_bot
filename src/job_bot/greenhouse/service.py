from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from langchain.messages import HumanMessage, SystemMessage
from pydantic import RootModel

from job_bot.greenhouse.commoncrawl import CommonCrawlClient, extract_token_from_url
from job_bot.greenhouse.greenhouse import BoardNameEnricher, GreenhouseVerifier
from job_bot.greenhouse.models import (
    CandidateToken,
    DiscoveredBoard,
    DiscoveryConfig,
    DiscoveryReport,
    DiscoveryStats,
)
from job_bot.llm import LLMProvider


class CompanyCareerSites(RootModel[dict[str, str | None]]):
    """Map requested company names to their official job or career websites."""


@dataclass
class CandidateDiscoveryResult:
    """Candidates and source-specific diagnostics produced by a discoverer."""

    candidates: dict[str, CandidateToken] = field(default_factory=dict)
    records_seen: int = 0
    crawl_indexes_used: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    fatal_error: bool = False


class GreenhouseDiscoverer(ABC):
    """Base class for Greenhouse candidate discovery and live verification."""

    user_agent = "GreenhouseDiscovery/0.3 (public-board research; rate-limited)"

    def __init__(self, config: DiscoveryConfig | None = None) -> None:
        self.config = config or DiscoveryConfig()

    @abstractmethod
    async def _discover_candidates(
        self,
        client: httpx.AsyncClient,
    ) -> CandidateDiscoveryResult:
        """Return unverified board-token candidates from a discovery source."""

    async def discover(self) -> DiscoveryReport:
        config = self.config
        limits = httpx.Limits(
            max_connections=max(
                config.verification_concurrency,
                config.enrichment_concurrency,
            )
            + 10,
            max_keepalive_connections=50,
        )

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(config.request_timeout_seconds),
            follow_redirects=True,
            headers={
                "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
                "User-Agent": self.user_agent,
            },
            limits=limits,
        ) as client:
            result = await self._discover_candidates(client)
            if result.fatal_error:
                return DiscoveryReport(
                    boards=[],
                    stats=self._stats(result),
                    errors=result.errors,
                )

            boards, verified_count, invalid_count, empty_count = await self._verify_candidates(
                client,
                list(result.candidates.values()),
            )

            if config.enrich_company_names and boards:
                enricher = BoardNameEnricher(
                    client=client,
                    concurrency=config.enrichment_concurrency,
                )
                await asyncio.gather(*(enricher.enrich(board) for board in boards))

        boards.sort(
            key=lambda board: (
                -board.active_job_count,
                (board.company_name or board.token).casefold(),
            )
        )

        return DiscoveryReport(
            boards=boards,
            stats=self._stats(
                result,
                verified_count=verified_count,
                invalid_count=invalid_count,
                empty_count=empty_count,
            ),
            errors=result.errors,
        )

    async def _verify_candidates(
        self,
        client: httpx.AsyncClient,
        candidates: list[CandidateToken],
    ) -> tuple[list[DiscoveredBoard], int, int, int]:
        config = self.config
        verifier = GreenhouseVerifier(
            client=client,
            concurrency=config.verification_concurrency,
            include_empty_boards=config.include_empty_boards,
        )
        boards: list[DiscoveredBoard] = []
        verified_count = 0
        invalid_count = 0
        empty_count = 0
        batch_size = max(config.verification_concurrency * 3, 50)

        for start in range(0, len(candidates), batch_size):
            if len(boards) >= config.limit:
                break

            batch = candidates[start : start + batch_size]
            outcomes = await asyncio.gather(*(verifier.verify(item) for item in batch))
            verified_count += len(batch)

            for board, status in outcomes:
                if status == "valid" and board is not None:
                    boards.append(board)
                elif status == "empty":
                    empty_count += 1
                else:
                    invalid_count += 1

                if len(boards) >= config.limit:
                    break

        return boards[: config.limit], verified_count, invalid_count, empty_count

    @staticmethod
    def _stats(
        result: CandidateDiscoveryResult,
        *,
        verified_count: int = 0,
        invalid_count: int = 0,
        empty_count: int = 0,
    ) -> DiscoveryStats:
        return DiscoveryStats(
            crawl_indexes_used=result.crawl_indexes_used,
            cdx_records_seen=result.records_seen,
            unique_candidates=len(result.candidates),
            candidates_verified=verified_count,
            invalid_or_stale_candidates=invalid_count,
            empty_boards_excluded=empty_count,
        )


class GreenhouseGlobalDiscoverer(GreenhouseDiscoverer):
    """Discover board candidates internet-wide through Common Crawl."""

    async def _discover_candidates(
        self,
        client: httpx.AsyncClient,
    ) -> CandidateDiscoveryResult:
        config = self.config
        commoncrawl = CommonCrawlClient(client)

        try:
            indexes = await commoncrawl.latest_indexes(config.crawl_count)
        except httpx.HTTPError as exc:
            return CandidateDiscoveryResult(
                errors=[f"Could not load Common Crawl indexes: {type(exc).__name__}: {exc}"],
                fatal_error=True,
            )

        candidates, records_seen, errors = await commoncrawl.discover_candidates(
            indexes=indexes,
            hosts=config.hosts,
            max_candidates=config.max_candidates,
            max_pages_per_query=config.max_pages_per_query,
            concurrency=config.crawl_concurrency,
        )
        return CandidateDiscoveryResult(
            candidates=candidates,
            records_seen=records_seen,
            crawl_indexes_used=[item.id for item in indexes],
            errors=errors,
        )


class GreenhouseCompanyDiscoverer(GreenhouseDiscoverer):
    """Discover Greenhouse boards from LLM-located company career websites."""

    def __init__(
        self,
        company_names: list[str],
        llm_provider: LLMProvider,
        config: DiscoveryConfig | None = None,
    ) -> None:
        super().__init__(config)
        self.company_names = company_names
        self.llm_provider = llm_provider

    async def _discover_candidates(
        self,
        client: httpx.AsyncClient,
    ) -> CandidateDiscoveryResult:
        if not self.company_names:
            return CandidateDiscoveryResult()

        try:
            career_sites = await self._find_career_sites()
        except Exception as exc:
            return CandidateDiscoveryResult(
                errors=[f"Could not find company career websites: {type(exc).__name__}: {exc}"],
                fatal_error=True,
            )

        candidates: dict[str, CandidateToken] = {}
        errors: list[str] = []

        for company_name, website_url in career_sites.items():
            if not website_url:
                continue
            try:
                greenhouse_urls = await self._find_greenhouse_urls(client, website_url)
            except httpx.HTTPError as exc:
                errors.append(f"{company_name} {website_url}: {type(exc).__name__}: {exc}")
                continue

            for greenhouse_url in greenhouse_urls:
                token = extract_token_from_url(greenhouse_url)
                if token is None:
                    continue
                key = token.casefold()
                candidate = candidates.setdefault(key, CandidateToken(token=token))
                if greenhouse_url not in candidate.discovered_urls:
                    candidate.discovered_urls.append(greenhouse_url)
                if len(candidates) >= self.config.max_candidates:
                    return CandidateDiscoveryResult(candidates=candidates, errors=errors)

        return CandidateDiscoveryResult(candidates=candidates, errors=errors)

    async def _find_career_sites(self) -> dict[str, str | None]:
        model = self.llm_provider.get_model().with_structured_output(CompanyCareerSites)
        response = await model.ainvoke(
            [
                SystemMessage(
                    content=(
                        "Find each company's official jobs or careers website. Return the "
                        "requested company names as dictionary keys and the most direct official "
                        "jobs website URL as values. Use null when no reliable official jobs "
                        "website can be found. Do not return job aggregator URLs."
                    )
                ),
                HumanMessage(content=json.dumps(self.company_names)),
            ]
        )
        if not isinstance(response, CompanyCareerSites):
            raise TypeError(f"Unexpected career website response: {type(response).__name__}")
        return response.root

    @staticmethod
    async def _find_greenhouse_urls(
        client: httpx.AsyncClient,
        website_url: str,
    ) -> list[str]:
        urls = [website_url]
        if extract_token_from_url(website_url) is not None:
            return urls

        response = await client.get(website_url)
        response.raise_for_status()
        final_url = str(response.url)
        if final_url not in urls:
            urls.append(final_url)

        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup.select("[href], [src], form[action]"):
            raw_url = tag.get("href") or tag.get("src") or tag.get("action")
            if isinstance(raw_url, str):
                resolved_url = urljoin(final_url, raw_url)
                if resolved_url not in urls:
                    urls.append(resolved_url)

        return [url for url in urls if extract_token_from_url(url) is not None]
