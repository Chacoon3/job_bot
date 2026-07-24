from __future__ import annotations

import json
from collections.abc import AsyncIterator
from urllib.parse import urlparse

import httpx

from job_bot.greenhouse_discovery.models import CandidateToken, CrawlIndex

COLLINFO_URL = "https://index.commoncrawl.org/collinfo.json"
GREENHOUSE_HOSTS = {
    "boards.greenhouse.io",
    "job-boards.greenhouse.io",
}


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
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def latest_indexes(self, count: int) -> list[CrawlIndex]:
        response = await self.client.get(COLLINFO_URL)
        response.raise_for_status()
        raw = response.json()

        indexes = [CrawlIndex.model_validate(item) for item in raw]
        # collinfo is normally newest-first, but sort defensively by id.
        indexes.sort(key=lambda item: item.id, reverse=True)
        return indexes[:count]

    async def _num_pages(
        self,
        index: CrawlIndex,
        host: str,
    ) -> int:
        response = await self.client.get(
            index.cdx_api,
            params={
                "url": f"{host}/*",
                "output": "json",
                "matchType": "prefix",
                "filter": "status:200",
                "showNumPages": "true",
            },
        )
        response.raise_for_status()

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
            response = await self.client.get(
                index.cdx_api,
                params={
                    "url": f"{host}/*",
                    "output": "json",
                    "matchType": "prefix",
                    "filter": "status:200",
                    # Collapse repeat captures of the same canonical URL.
                    "collapse": "urlkey",
                    "fl": "url",
                    "page": page,
                },
            )
            response.raise_for_status()

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
                    errors.append(f"{index.id} {host}: " f"{type(exc).__name__}: {exc}")

        return candidates, records_seen, errors
