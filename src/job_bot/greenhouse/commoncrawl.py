from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from urllib.parse import urlparse

import httpx

from job_bot.greenhouse.models import CandidateToken, CrawlIndex

COLLINFO_URL = "https://index.commoncrawl.org/collinfo.json"
GREENHOUSE_HOSTS = {
    "boards.greenhouse.io",
    "job-boards.greenhouse.io",
}
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_REQUEST_ATTEMPTS = 3


def extract_token_from_url(url: str) -> str | None:
    """
    Extract the first path segment from a recognized Greenhouse board URL.

    Examples:
      https://job-boards.greenhouse.io/anthropic -> anthropic
      https://boards.greenhouse.io/acme/jobs/123 -> acme
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold()
    if host not in GREENHOUSE_HOSTS:
        return None

    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        return None

    token = parts[0].strip()
    if not token or token.casefold() in {"embed", "favicon.ico"}:
        return None
    return token


class CommonCrawlClient:
    """Discover Greenhouse board candidates through Common Crawl's CDX API.

    The client owns index enumeration, pagination, response parsing, transient
    retry behavior, and conversion of archived URLs into deduplicated candidate
    tokens. It does not decide whether a board is still live; that responsibility
    belongs to :class:`GreenhouseVerifier`.
    """

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def latest_indexes(self, count: int) -> list[CrawlIndex]:
        response = await self._get(COLLINFO_URL)
        raw = response.json()

        indexes = [CrawlIndex.model_validate(item) for item in raw]
        # collinfo is normally newest-first, but sort defensively by id.
        indexes.sort(key=lambda item: item.id, reverse=True)
        return indexes[:count]

    async def _get(
        self,
        url: str,
        *,
        params: dict[str, str | int] | None = None,
    ) -> httpx.Response:
        """GET a Common Crawl resource, retrying only transient failures."""
        for attempt in range(MAX_REQUEST_ATTEMPTS):
            response = await self.client.get(url, params=params)
            if response.status_code not in RETRYABLE_STATUS_CODES:
                response.raise_for_status()
                return response

            if attempt == MAX_REQUEST_ATTEMPTS - 1:
                response.raise_for_status()

            retry_after = response.headers.get("Retry-After")
            try:
                delay = float(retry_after) if retry_after is not None else 0.5 * (2**attempt)
            except ValueError:
                delay = 0.5 * (2**attempt)
            await asyncio.sleep(min(max(delay, 0), 10))

        raise RuntimeError("unreachable")

    async def _num_pages(
        self,
        index: CrawlIndex,
        host: str,
    ) -> int:
        response = await self._get(
            index.cdx_api,
            params={
                "url": f"{host}/*",
                "output": "json",
                "filter": "status:200",
                "showNumPages": "true",
            },
        )

        # Common Crawl has returned both JSON objects and plain integers
        # for this query across API versions.
        text = response.text.strip()
        try:
            payload = response.json()
        except ValueError:
            return max(1, int(text))

        if isinstance(payload, int):
            return max(1, payload)
        if isinstance(payload, dict):
            for key in ("pages", "numPages", "pageCount"):
                value = payload.get(key)
                if isinstance(value, int):
                    return max(1, value)
        if isinstance(payload, list) and payload:
            first = payload[0]
            if isinstance(first, int):
                return max(1, first)
            if isinstance(first, dict):
                for key in ("pages", "numPages", "pageCount"):
                    value = first.get(key)
                    if isinstance(value, int):
                        return max(1, value)

        # One page is a safe fallback for smaller result sets.
        return 1

    async def iter_urls(
        self,
        index: CrawlIndex,
        host: str,
        max_pages: int,
    ) -> AsyncIterator[str]:
        page_count = min(
            await self._num_pages(index, host),
            max_pages,
        )

        for page in range(page_count):
            try:
                response = await self._get(
                    index.cdx_api,
                    params={
                        # The trailing wildcard already selects prefix matching.
                        # Supplying matchType=prefix as well makes the current CDX
                        # API return a false "No Captures" 404.
                        "url": f"{host}/*",
                        "output": "json",
                        "filter": "status:200",
                        # Collapse repeat captures of the same canonical URL.
                        "collapse": "urlkey",
                        "fl": "url",
                        "page": page,
                    },
                )
            except httpx.HTTPStatusError as exc:
                # CDX uses 404 to report a valid query with no captures.
                if exc.response.status_code == 404:
                    return
                raise

            for line in response.text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if isinstance(record, dict):
                    url = record.get("url")
                elif isinstance(record, list) and record:
                    # Defensive support for array-shaped output.
                    url = record[0]
                else:
                    url = None

                if isinstance(url, str):
                    yield url

    async def discover_candidates(
        self,
        indexes: list[CrawlIndex],
        hosts: list[str],
        max_candidates: int,
        max_pages_per_query: int,
    ) -> tuple[dict[str, CandidateToken], int, list[str]]:
        candidates: dict[str, CandidateToken] = {}
        records_seen = 0
        errors: list[str] = []

        for index in indexes:
            for host in hosts:
                try:
                    async for url in self.iter_urls(
                        index=index,
                        host=host,
                        max_pages=max_pages_per_query,
                    ):
                        records_seen += 1
                        token = extract_token_from_url(url)
                        if token is None:
                            continue

                        key = token.casefold()
                        item = candidates.setdefault(
                            key,
                            CandidateToken(token=token),
                        )

                        if url not in item.discovered_urls:
                            item.discovered_urls.append(url)
                        if index.id not in item.crawl_indexes:
                            item.crawl_indexes.append(index.id)

                        if len(candidates) >= max_candidates:
                            return candidates, records_seen, errors
                except httpx.HTTPError as exc:
                    errors.append(f"{index.id} {host}: {type(exc).__name__}: {exc}")

        return candidates, records_seen, errors
