from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from job_bot.greenhouse.service import CompanyCareerSite, CompanyCareerSiteList
from job_bot.job_providers.llm_job_provider import JobEntryList, LLMJobProvider
from job_bot.schemas import JobEntrySchema


class FakeStructuredModel:
    def __init__(self, response: object) -> None:
        self.response = response
        self.messages: list[object] | None = None

    def invoke(self, messages: list[object]) -> object:
        self.messages = messages
        return self.response


class FakeModel:
    def __init__(self, responses: dict[type[object], object]) -> None:
        self.responses = responses

    def with_structured_output(self, schema: type[object]) -> FakeStructuredModel:
        return FakeStructuredModel(self.responses[schema])


class FakeLLMProvider:
    def __init__(self, responses: dict[type[object], object]) -> None:
        self.model = FakeModel(responses)

    def get_model(self) -> FakeModel:
        return self.model


class FakePage:
    url = "https://careers.example.com/jobs"

    def __init__(self) -> None:
        self.visited: list[str] = []
        self.timeout: int | None = None
        self.settle_time_ms: int | None = None
        self.load_states: list[str] = []

    def set_default_navigation_timeout(self, timeout: int) -> None:
        self.timeout = timeout

    def goto(self, url: str, *, wait_until: str) -> None:
        self.visited.append(url)
        assert wait_until == "domcontentloaded"

    def wait_for_load_state(self, state: str, *, timeout: int) -> None:
        self.load_states.append(state)

    def wait_for_timeout(self, timeout: int) -> None:
        self.settle_time_ms = timeout

    def content(self) -> str:
        return "<a href='/jobs/1'>Engineer</a>"


class FakeBrowserContext:
    def __init__(self, page: FakePage) -> None:
        self.page = page
        self.closed = False

    def new_page(self) -> FakePage:
        return self.page

    def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self, page: FakePage) -> None:
        self.context = FakeBrowserContext(page)
        self.context_options: dict[str, object] | None = None
        self.closed = False

    def new_context(self, **kwargs: object) -> FakeBrowserContext:
        self.context_options = kwargs
        return self.context

    def close(self) -> None:
        self.closed = True


class FakePlaywrightContext:
    def __init__(self) -> None:
        self.page = FakePage()
        self.browser = FakeBrowser(self.page)
        self.playwright = SimpleNamespace(
            chromium=SimpleNamespace(launch=lambda **_kwargs: self.browser)
        )

    def __enter__(self) -> object:
        return self.playwright

    def __exit__(self, *_args: object) -> None:
        return None


def _job(*, posted: datetime | None) -> JobEntrySchema:
    return JobEntrySchema(
        job_title="Software Engineer",
        url="/jobs/1",
        year_of_experience_minimum=2,
        year_of_experience_maximum=4,
        company_name="LLM supplied value",
        job_location="Remote",
        jd_summary="Build systems.",
        pay_range_minimum=100_000,
        pay_range_maximum=150_000,
        date_posted=posted,
    )


def test_discovers_site_extracts_normalizes_and_filters_jobs(monkeypatch) -> None:
    recent = datetime(2026, 7, 20, tzinfo=UTC)
    old = datetime(2026, 6, 1, tzinfo=UTC)
    llm = FakeLLMProvider(
        {
            CompanyCareerSiteList: CompanyCareerSiteList(
                items=[
                    CompanyCareerSite(
                        company_name="Example",
                        career_site_url="https://careers.example.com/jobs",
                    )
                ]
            ),
            JobEntryList: JobEntryList(items=[_job(posted=recent), _job(posted=old)]),
        }
    )
    playwright = FakePlaywrightContext()
    monkeypatch.setattr(LLMJobProvider, "_is_safe_public_url", staticmethod(lambda _url: True))

    provider = LLMJobProvider(
        [" Example ", "Example"],
        llm,  # type: ignore[arg-type]
        earliest_post_date=datetime(2026, 7, 1, tzinfo=UTC),
        playwright_factory=lambda: playwright,
    )
    jobs = provider.provide()

    assert provider.company_names == ["Example"]
    assert playwright.page.visited == ["https://careers.example.com/jobs"]
    assert playwright.page.load_states == []
    assert playwright.page.settle_time_ms == 1_500
    assert playwright.browser.context.closed is True
    assert playwright.browser.closed is True
    options = playwright.browser.context_options
    assert options is not None
    assert options["user_agent"] == provider.user_agent
    assert options["locale"] == "en-US"
    assert options["timezone_id"] == "America/New_York"
    assert options["viewport"] == {"width": 1440, "height": 900}
    assert options["screen"] == {"width": 1440, "height": 900}
    assert options["is_mobile"] is False
    assert options["has_touch"] is False
    assert options["extra_http_headers"] == {
        "Accept-Language": "en-US,en;q=0.9",
        "Upgrade-Insecure-Requests": "1",
    }
    assert len(jobs) == 1
    assert jobs[0].company_name == "Example"
    assert jobs[0].source == "llm"
    assert jobs[0].url == "https://careers.example.com/jobs/1"


def test_empty_company_list_does_not_start_playwright() -> None:
    provider = LLMJobProvider(
        [],
        FakeLLMProvider({}),  # type: ignore[arg-type]
        playwright_factory=lambda: (_ for _ in ()).throw(AssertionError("must not start")),
    )

    assert provider.provide() == []


def test_date_filter_rejects_unknown_dates() -> None:
    provider = LLMJobProvider(
        ["Example"],
        FakeLLMProvider({}),  # type: ignore[arg-type]
        earliest_post_date=datetime(2026, 7, 1, tzinfo=UTC),
    )

    assert provider._accepts(_job(posted=None)) is False


def test_scraping_error_propagates_and_browser_closes(monkeypatch) -> None:
    llm = FakeLLMProvider(
        {
            CompanyCareerSiteList: CompanyCareerSiteList(
                items=[
                    CompanyCareerSite(
                        company_name="Example",
                        career_site_url="https://careers.example.com/jobs",
                    )
                ]
            )
        }
    )
    playwright = FakePlaywrightContext()
    monkeypatch.setattr(LLMJobProvider, "_is_safe_public_url", staticmethod(lambda _url: True))
    monkeypatch.setattr(
        playwright.page,
        "goto",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("scrape failed")),
    )
    provider = LLMJobProvider(
        ["Example"],
        llm,  # type: ignore[arg-type]
        playwright_factory=lambda: playwright,
    )

    with pytest.raises(RuntimeError, match="scrape failed"):
        provider.provide()

    assert playwright.browser.context.closed is True
    assert playwright.browser.closed is True
