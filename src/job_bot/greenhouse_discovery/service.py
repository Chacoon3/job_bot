from __future__ import annotations

import asyncio

import httpx

from job_bot.greenhouse_discovery.commoncrawl import CommonCrawlClient
from job_bot.greenhouse_discovery.greenhouse import (
    BoardNameEnricher,
    GreenhouseVerifier,
)
from job_bot.greenhouse_discovery.models import (
    DiscoveredBoard,
    DiscoveryConfig,
    DiscoveryReport,
    DiscoveryStats,
)


class GreenhouseGlobalDiscoverer:
    """
    Internet-wide Greenhouse board discovery without company-name input.

    Discovery is historical/index-based; current validity is established by
    checking the live Greenhouse Job Board API before returning each board.
    """

    def __init__(
        self,
        config: DiscoveryConfig | None = None,
    ) -> None:
        self.config = config or DiscoveryConfig()

    async def discover(self) -> DiscoveryReport:
        config = self.config
        errors: list[str] = []

        headers = {
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
            "User-Agent": (
                "GreenhouseGlobalDiscovery/0.2 " "(public-board research; rate-limited)"
            ),
        }

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
            headers=headers,
            limits=limits,
        ) as client:
            commoncrawl = CommonCrawlClient(client)

            try:
                indexes = await commoncrawl.latest_indexes(config.crawl_count)
            except httpx.HTTPError as exc:
                return DiscoveryReport(
                    boards=[],
                    stats=DiscoveryStats(),
                    errors=[
                        f"Could not load Common Crawl indexes: " f"{type(exc).__name__}: {exc}"
                    ],
                )

            candidates, records_seen, cc_errors = await commoncrawl.discover_candidates(
                indexes=indexes,
                hosts=config.hosts,
                max_candidates=config.max_candidates,
                max_pages_per_query=config.max_pages_per_query,
            )
            errors.extend(cc_errors)

            verifier = GreenhouseVerifier(
                client=client,
                concurrency=config.verification_concurrency,
                include_empty_boards=config.include_empty_boards,
            )

            boards: list[DiscoveredBoard] = []
            verified_count = 0
            invalid_count = 0
            empty_count = 0

            # Validate in bounded batches and stop once the requested number
            # of live boards has been collected.
            batch_size = max(
                config.verification_concurrency * 3,
                50,
            )
            values = list(candidates.values())

            for start in range(0, len(values), batch_size):
                if len(boards) >= config.limit:
                    break

                batch = values[start : start + batch_size]
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

            boards = boards[: config.limit]

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
            stats=DiscoveryStats(
                crawl_indexes_used=[item.id for item in indexes],
                cdx_records_seen=records_seen,
                unique_candidates=len(candidates),
                candidates_verified=verified_count,
                invalid_or_stale_candidates=invalid_count,
                empty_boards_excluded=empty_count,
            ),
            errors=errors,
        )
