from __future__ import annotations

import asyncio

import httpx
import pytest

from job_bot.greenhouse.commoncrawl import CommonCrawlClient
from job_bot.greenhouse.models import CrawlIndex


def crawl_index() -> CrawlIndex:
    return CrawlIndex.model_validate(
        {
            "id": "CC-MAIN-2026-25",
            "cdx-api": "https://index.commoncrawl.org/test-index",
        }
    )


def test_iter_urls_uses_wildcard_without_conflicting_match_type() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.params.get("showNumPages") == "true":
            return httpx.Response(200, json={"pages": 0})
        return httpx.Response(200, text='{"url":"https://boards.greenhouse.io/acme/jobs/1"}\n')

    async def run() -> list[str]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return [
                url
                async for url in CommonCrawlClient(client).iter_urls(
                    crawl_index(), "boards.greenhouse.io", max_pages=10
                )
            ]

    urls = asyncio.run(run())
    assert urls == ["https://boards.greenhouse.io/acme/jobs/1"]
    assert all("matchType" not in request.url.params for request in requests)
    assert all(request.url.params["url"] == "boards.greenhouse.io/*" for request in requests)


def test_iter_urls_retries_transient_response(monkeypatch: pytest.MonkeyPatch) -> None:
    page_attempts = 0

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("job_bot.greenhouse.commoncrawl.asyncio.sleep", no_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal page_attempts
        if request.url.params.get("showNumPages") == "true":
            return httpx.Response(200, json={"pages": 0})
        page_attempts += 1
        if page_attempts == 1:
            return httpx.Response(503)
        return httpx.Response(200, text='{"url":"https://boards.greenhouse.io/acme"}\n')

    async def run() -> list[str]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return [
                url
                async for url in CommonCrawlClient(client).iter_urls(
                    crawl_index(), "boards.greenhouse.io", max_pages=10
                )
            ]

    urls = asyncio.run(run())
    assert urls == ["https://boards.greenhouse.io/acme"]
    assert page_attempts == 2


def test_iter_urls_treats_no_captures_as_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("showNumPages") == "true":
            return httpx.Response(200, json={"pages": 0})
        return httpx.Response(404, json={"message": "No Captures found"})

    async def run() -> list[str]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return [
                url
                async for url in CommonCrawlClient(client).iter_urls(
                    crawl_index(), "boards.greenhouse.io", max_pages=10
                )
            ]

    urls = asyncio.run(run())
    assert urls == []
