from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class CrawlIndex(BaseModel):
    """Describe one Common Crawl collection that can be queried through CDX.

    Common Crawl returns this metadata from ``collinfo.json``. The discovery
    service keeps the model separate from HTTP handling so index selection and
    provenance can pass through the pipeline as validated data.
    """

    id: str
    name: str | None = None
    timegate: str | None = None
    cdx_api: str = Field(alias="cdx-api")
    from_date: str | None = Field(default=None, alias="from")
    to_date: str | None = Field(default=None, alias="to")


class CandidateToken(BaseModel):
    """Represent an unverified board token extracted from archived URLs.

    A token remains a candidate until the live Greenhouse API accepts it. URLs
    and crawl-index IDs are retained as evidence and later copied to a verified
    board so consumers can understand where it was discovered.
    """

    token: str
    discovered_urls: list[str] = Field(default_factory=list)
    crawl_indexes: list[str] = Field(default_factory=list)


class DiscoveredBoard(BaseModel):
    """Represent the current, verified view of a public Greenhouse board.

    The model combines stable board identity and URLs with a point-in-time job
    count, a small title sample, and Common Crawl provenance. It is the primary
    discovery output and the input shape used by persistence and exporters.
    """

    token: str
    company_name: str | None = None
    board_url: str
    api_url: str
    active_job_count: int
    sample_job_titles: list[str] = Field(default_factory=list)
    discovered_urls: list[str] = Field(default_factory=list)
    crawl_indexes: list[str] = Field(default_factory=list)
    verified_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DiscoveryConfig(BaseModel):
    """Define resource limits and behavior for one discovery operation.

    Bounds on candidates, crawl pages, concurrency, and returned boards prevent
    an internet-wide search from becoming unbounded. Pydantic constraints reject
    unsafe values before any network work begins.
    """

    # Number of live, API-verified boards to return.
    limit: int = Field(default=10, ge=1, le=100_000)

    # Stop enumerating Common Crawl after this many unique token candidates.
    max_candidates: int = Field(default=10_000, ge=1)

    # Search this many newest Common Crawl monthly indexes.
    crawl_count: int = Field(default=2, ge=1, le=24)

    # A board can be valid with zero open jobs. Set true to include it.
    include_empty_boards: bool = False

    # Concurrent Greenhouse API validations.
    verification_concurrency: int = Field(default=30, ge=1, le=200)

    # Concurrent optional board-page enrichment requests.
    enrichment_concurrency: int = Field(default=10, ge=1, le=100)

    request_timeout_seconds: float = Field(default=30.0, gt=0)

    # Common Crawl query pages can be large; this bounds each host/index.
    max_pages_per_query: int = Field(default=100, ge=1)

    # Public Greenhouse hosts to enumerate.
    hosts: list[str] = Field(
        default_factory=lambda: [
            "job-boards.greenhouse.io",
            "boards.greenhouse.io",
        ]
    )

    # Resolve a human-facing company/board name from the live board HTML.
    enrich_company_names: bool = True


class DiscoveryStats(BaseModel):
    """Summarize how much work a discovery run performed.

    The counters distinguish archived records scanned, candidates found,
    candidates verified, and boards rejected. They are operational diagnostics,
    not persistent board attributes.
    """

    crawl_indexes_used: list[str] = Field(default_factory=list)
    cdx_records_seen: int = 0
    unique_candidates: int = 0
    candidates_verified: int = 0
    invalid_or_stale_candidates: int = 0
    empty_boards_excluded: int = 0


class DiscoveryReport(BaseModel):
    """Package all externally useful results from one discovery run.

    Successful boards remain available when an individual crawl query fails, so
    errors are collected beside results instead of aborting the entire run. The
    generation timestamp identifies when this snapshot was assembled.
    """

    boards: list[DiscoveredBoard]
    stats: DiscoveryStats
    errors: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
