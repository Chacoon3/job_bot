from __future__ import annotations

import asyncio

import httpx

from job_bot.greenhouse.service import (
    CandidateDiscoveryResult,
    CompanyCareerSites,
    GreenhouseCompanyDiscoverer,
    GreenhouseGlobalDiscoverer,
)
from job_bot.llm import LLMProvider


class FakeLLMProvider(LLMProvider):
    def __init__(self, response: CompanyCareerSites | None = None) -> None:
        self.model = FakeStructuredModel(response or CompanyCareerSites(root={}))

    def get_model(self):
        return self.model


class FakeStructuredModel:
    def __init__(self, response: CompanyCareerSites) -> None:
        self.response = response
        self.schema = None
        self.method = None
        self.messages = None

    def with_structured_output(self, schema, *, method=None):
        self.schema = schema
        self.method = method
        return self

    async def ainvoke(self, messages):
        self.messages = messages
        return self.response


def test_company_discoverer_calls_llm_provider_for_career_sites() -> None:
    expected = CompanyCareerSites(root={"Acme": "https://boards.greenhouse.io/acme"})
    provider = FakeLLMProvider(expected)
    discoverer = GreenhouseCompanyDiscoverer(["Acme"], provider)

    result = asyncio.run(discoverer._find_career_sites())

    assert result == expected.root
    assert provider.model.schema is CompanyCareerSites
    assert provider.model.method == "function_calling"
    assert provider.model.messages is not None


def test_company_discoverer_uses_llm_sites_and_extracts_greenhouse_boards(
    monkeypatch,
) -> None:
    discoverer = GreenhouseCompanyDiscoverer(
        ["Acme", "Other"],
        FakeLLMProvider(),
    )
    career_sites = CompanyCareerSites(
        root={"Acme": "https://careers.acme.test", "Other": "https://other.test/jobs"}
    )

    async def fake_find_career_sites():
        return career_sites.root

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "careers.acme.test":
            return httpx.Response(
                200,
                request=request,
                html='<iframe src="https://job-boards.greenhouse.io/acme"></iframe>',
            )
        return httpx.Response(200, request=request, html="<p>Not Greenhouse</p>")

    monkeypatch.setattr(discoverer, "_find_career_sites", fake_find_career_sites)
    async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        result = asyncio.run(discoverer._discover_candidates(async_client))
    finally:
        asyncio.run(async_client.aclose())

    assert list(result.candidates) == ["acme"]
    assert result.candidates["acme"].discovered_urls == ["https://job-boards.greenhouse.io/acme"]


def test_company_discoverer_accepts_direct_greenhouse_job_site(monkeypatch) -> None:
    discoverer = GreenhouseCompanyDiscoverer(["Acme"], FakeLLMProvider())

    async def fake_find_career_sites():
        return {"Acme": "https://boards.greenhouse.io/acme/jobs/123"}

    monkeypatch.setattr(discoverer, "_find_career_sites", fake_find_career_sites)
    result = asyncio.run(discoverer._discover_candidates(None))  # type: ignore[arg-type]

    assert list(result.candidates) == ["acme"]


def test_global_discoverer_maps_common_crawl_results(monkeypatch) -> None:
    class FakeCommonCrawlClient:
        def __init__(self, client: httpx.AsyncClient) -> None:
            del client

        async def latest_indexes(self, count: int) -> list[object]:
            assert count == 2
            return [type("Index", (), {"id": "CC-MAIN-1"})()]

        async def discover_candidates(self, **kwargs):
            assert kwargs["max_candidates"] == 10_000
            return {}, 12, ["partial failure"]

    monkeypatch.setattr(
        "job_bot.greenhouse.service.CommonCrawlClient",
        FakeCommonCrawlClient,
    )
    discoverer = GreenhouseGlobalDiscoverer()

    result = asyncio.run(discoverer._discover_candidates(None))  # type: ignore[arg-type]

    assert result == CandidateDiscoveryResult(
        records_seen=12,
        crawl_indexes_used=["CC-MAIN-1"],
        errors=["partial failure"],
    )
