from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import structlog
from langchain.messages import HumanMessage, SystemMessage
from playwright.sync_api import Page, PlaywrightContextManager, sync_playwright
from pydantic import BaseModel

from job_bot.greenhouse.service import CompanyCareerSiteList
from job_bot.job_providers.job_provider import JobProvider
from job_bot.llm import LLMProvider
from job_bot.schemas import JobEntrySchema
from job_bot.utils.caching import AppDiskCache

logger = structlog.get_logger(__name__)

LLM_SOURCE = "llm"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)


def _career_site_cache_key(
    _func: Callable[..., Any],
    args: tuple[Any, ...],
    _kwargs: dict[str, Any],
) -> str:
    company_names = args[1]
    digest = hashlib.sha256(json.dumps(company_names).encode()).hexdigest()
    return f"llm_job_provider_find_career_sites_{digest}"


class JobEntryList(BaseModel):
    """Structured LLM output containing jobs found on one career site."""

    items: list[JobEntrySchema]


class LLMJobProvider(JobProvider):
    """Discover company career sites and extract their jobs with an LLM."""

    def __init__(
        self,
        company_names: list[str],
        llm_provider: LLMProvider,
        *,
        earliest_post_date: datetime | None = None,
        headless: bool = True,
        navigation_timeout_ms: int = 30_000,
        page_settle_ms: int = 1_500,
        max_page_content_chars: int = 200_000,
        user_agent: str = DEFAULT_USER_AGENT,
        locale: str = "en-US",
        timezone_id: str = "America/New_York",
        playwright_factory: Callable[[], PlaywrightContextManager] = sync_playwright,
    ) -> None:
        if navigation_timeout_ms <= 0:
            raise ValueError("navigation_timeout_ms must be positive")
        if page_settle_ms < 0:
            raise ValueError("page_settle_ms must not be negative")
        if max_page_content_chars <= 0:
            raise ValueError("max_page_content_chars must be positive")
        if not user_agent.strip():
            raise ValueError("user_agent must not be empty")
        if not locale.strip():
            raise ValueError("locale must not be empty")
        if not timezone_id.strip():
            raise ValueError("timezone_id must not be empty")

        self.company_names = list(
            dict.fromkeys(name.strip() for name in company_names if name.strip())
        )
        self.llm_provider = llm_provider
        self.earliest_post_date = earliest_post_date
        self.headless = headless
        self.navigation_timeout_ms = navigation_timeout_ms
        self.page_settle_ms = page_settle_ms
        self.max_page_content_chars = max_page_content_chars
        self.user_agent = user_agent
        self.locale = locale
        self.timezone_id = timezone_id
        self.playwright_factory = playwright_factory

    def provide(self) -> list[JobEntrySchema]:
        if not self.company_names:
            return []

        career_sites = self._find_career_sites(self.company_names)
        jobs_by_url: dict[str, JobEntrySchema] = {}
        requested_names = {name.casefold(): name for name in self.company_names}

        with self.playwright_factory() as playwright:
            browser = playwright.chromium.launch(headless=self.headless)
            try:
                context = browser.new_context(
                    user_agent=self.user_agent,
                    locale=self.locale,
                    timezone_id=self.timezone_id,
                    viewport={"width": 1440, "height": 900},
                    screen={"width": 1440, "height": 900},
                    device_scale_factor=1,
                    is_mobile=False,
                    has_touch=False,
                    color_scheme="light",
                    reduced_motion="no-preference",
                    extra_http_headers={
                        "Accept-Language": f"{self.locale},en;q=0.9",
                        "Upgrade-Insecure-Requests": "1",
                    },
                )
                try:
                    page = context.new_page()
                    page.set_default_navigation_timeout(self.navigation_timeout_ms)
                    for item in career_sites.items:
                        company_name = requested_names.get(item.company_name.casefold())
                        if company_name is None:
                            logger.warning(
                                "llm_job_provider_unrequested_company",
                                company_name=item.company_name,
                            )
                            continue
                        if not item.career_site_url:
                            continue
                        if not self._is_safe_public_url(item.career_site_url):
                            logger.warning(
                                "llm_job_provider_unsafe_url",
                                company_name=company_name,
                                url=item.career_site_url,
                            )
                            continue
                        jobs = self._extract_company_jobs(
                            page,
                            company_name,
                            item.career_site_url,
                        )

                        for job in jobs:
                            if self._accepts(job):
                                jobs_by_url.setdefault(job.url, job)
                finally:
                    context.close()
            finally:
                browser.close()

        return sorted(
            jobs_by_url.values(),
            key=lambda job: (
                job.date_posted is None,
                -(self._as_utc(job.date_posted).timestamp()) if job.date_posted else 0,
                job.company_name.casefold(),
                job.job_title.casefold(),
            ),
        )

    @AppDiskCache.cached(key_builder=_career_site_cache_key)
    def _find_career_sites(self, company_names: list[str]) -> CompanyCareerSiteList:
        model = self.llm_provider.get_model().with_structured_output(CompanyCareerSiteList)
        response = model.invoke(
            [
                SystemMessage(
                    content=(
                        "Find the official jobs or careers website for each requested company. "
                        "Return the company name exactly as supplied and the most direct official "
                        "career-site URL. Use null when no reliable official site can be found. "
                        "Never return job aggregators, localhost, private-network, file, or other "
                        "non-HTTP(S) URLs."
                    )
                ),
                HumanMessage(content=json.dumps(company_names)),
            ]
        )
        if not isinstance(response, CompanyCareerSiteList):
            raise TypeError(f"Unexpected career website response: {type(response).__name__}")
        return response

    def _extract_company_jobs(
        self,
        page: Page,
        company_name: str,
        career_site_url: str,
    ) -> list[JobEntrySchema]:
        page.goto(career_site_url, wait_until="domcontentloaded")
        if self.page_settle_ms:
            page.wait_for_timeout(self.page_settle_ms)
        final_url = page.url
        if not self._is_safe_public_url(final_url):
            raise ValueError(f"Career site redirected to an unsafe URL: {final_url}")

        content = page.content()[: self.max_page_content_chars]
        model = self.llm_provider.get_model().with_structured_output(JobEntryList)
        response = model.invoke(
            [
                SystemMessage(
                    content=(
                        "Extract every actual job posting visible in the supplied career-page "
                        "HTML. Return no navigation, search, category, or talent-network links. "
                        "Use the supplied company name. Resolve relative URLs against the supplied "
                        "final page URL. Summarize the job description briefly. Use 0 when a "
                        "minimum/maximum experience or annual pay value is not stated. Preserve "
                        "the posted date when present; otherwise use null. Set source to 'llm'."
                    )
                ),
                HumanMessage(
                    content=json.dumps(
                        {
                            "company_name": company_name,
                            "page_url": final_url,
                            "earliest_accepted_post_date": (
                                self.earliest_post_date.isoformat()
                                if self.earliest_post_date
                                else None
                            ),
                            "html": content,
                        }
                    )
                ),
            ]
        )
        if not isinstance(response, JobEntryList):
            raise TypeError(f"Unexpected job extraction response: {type(response).__name__}")

        normalized: list[JobEntrySchema] = []
        for job in response.items:
            job.company_name = company_name
            job.source = LLM_SOURCE
            job.url = urljoin(final_url, job.url)
            if self._is_safe_public_url(job.url):
                normalized.append(job)
        return normalized

    def _accepts(self, job: JobEntrySchema) -> bool:
        if self.earliest_post_date is None:
            return True
        if job.date_posted is None:
            return False
        return self._as_utc(job.date_posted) >= self._as_utc(self.earliest_post_date)

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _is_safe_public_url(url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False
        if parsed.username or parsed.password:
            return False

        try:
            addresses = {
                ipaddress.ip_address(item[4][0])
                for item in socket.getaddrinfo(
                    parsed.hostname,
                    parsed.port or (443 if parsed.scheme == "https" else 80),
                )
            }
        except (OSError, ValueError):
            return False
        return bool(addresses) and all(address.is_global for address in addresses)
