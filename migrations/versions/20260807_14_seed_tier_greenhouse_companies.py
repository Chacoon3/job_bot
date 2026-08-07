"""Seed curated Tier 1 and Tier 2 companies with verified Greenhouse boards.

Tier 1 contains large, established, or category-leading employers; Tier 2
contains established growth-stage employers. The current schema has no tier
column, so the labels are documented here as seed-selection metadata.

Revision ID: 20260807_14
Revises: 20260807_13
Create Date: 2026-08-07
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import insert

revision: str = "20260807_14"
down_revision: str | Sequence[str] | None = "20260807_13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VERIFIED_AT = datetime(2026, 8, 7, tzinfo=UTC)
SEED_PROVENANCE = "curated-tier-seed-2026-08-07"

# tier, name, Greenhouse token, official website, industry, headquarters
COMPANY_SEEDS = (
    (
        1,
        "Stripe",
        "stripe",
        "https://stripe.com",
        "Financial technology",
        "San Francisco, California",
    ),
    (
        1,
        "Datadog",
        "datadog",
        "https://www.datadoghq.com",
        "Observability software",
        "New York, New York",
    ),
    (
        1,
        "Cloudflare",
        "cloudflare",
        "https://www.cloudflare.com",
        "Cloud computing and security",
        "San Francisco, California",
    ),
    (1, "Figma", "figma", "https://www.figma.com", "Design software", "San Francisco, California"),
    (
        1,
        "Discord",
        "discord",
        "https://discord.com",
        "Communications software",
        "San Francisco, California",
    ),
    (
        1,
        "Asana",
        "asana",
        "https://asana.com",
        "Work management software",
        "San Francisco, California",
    ),
    (
        1,
        "Duolingo",
        "duolingo",
        "https://www.duolingo.com",
        "Education technology",
        "Pittsburgh, Pennsylvania",
    ),
    (
        1,
        "Roblox",
        "roblox",
        "https://www.roblox.com",
        "Gaming and entertainment",
        "San Mateo, California",
    ),
    (1, "MongoDB", "mongodb", "https://www.mongodb.com", "Database software", "New York, New York"),
    (
        1,
        "Affirm",
        "affirm",
        "https://www.affirm.com",
        "Financial technology",
        "San Francisco, California",
    ),
    (
        1,
        "Coinbase",
        "coinbase",
        "https://www.coinbase.com",
        "Financial technology",
        "San Francisco, California",
    ),
    (
        1,
        "Reddit",
        "reddit",
        "https://www.redditinc.com",
        "Social media",
        "San Francisco, California",
    ),
    (
        1,
        "Airtable",
        "airtable",
        "https://www.airtable.com",
        "Work management software",
        "San Francisco, California",
    ),
    (
        1,
        "Instacart",
        "instacart",
        "https://www.instacart.com",
        "E-commerce",
        "San Francisco, California",
    ),
    (
        1,
        "Lyft",
        "lyft",
        "https://www.lyft.com",
        "Transportation technology",
        "San Francisco, California",
    ),
    (
        1,
        "Flexport",
        "flexport",
        "https://www.flexport.com",
        "Logistics technology",
        "San Francisco, California",
    ),
    (
        1,
        "Scale AI",
        "scaleai",
        "https://scale.com",
        "Artificial intelligence",
        "San Francisco, California",
    ),
    (
        1,
        "Okta",
        "okta",
        "https://www.okta.com",
        "Identity and security software",
        "San Francisco, California",
    ),
    (
        1,
        "Braze",
        "braze",
        "https://www.braze.com",
        "Customer engagement software",
        "New York, New York",
    ),
    (
        1,
        "Klaviyo",
        "klaviyo",
        "https://www.klaviyo.com",
        "Marketing automation software",
        "Boston, Massachusetts",
    ),
    (
        1,
        "Elastic",
        "elastic",
        "https://www.elastic.co",
        "Search and observability software",
        "Mountain View, California",
    ),
    (
        2,
        "Brex",
        "brex",
        "https://www.brex.com",
        "Financial technology",
        "San Francisco, California",
    ),
    (
        2,
        "Gusto",
        "gusto",
        "https://gusto.com",
        "Payroll and HR software",
        "San Francisco, California",
    ),
    (
        2,
        "Checkr",
        "checkr",
        "https://checkr.com",
        "Background-check technology",
        "San Francisco, California",
    ),
    (
        2,
        "Webflow",
        "webflow",
        "https://webflow.com",
        "Website experience platform",
        "San Francisco, California",
    ),
    (
        2,
        "Amplitude",
        "amplitude",
        "https://amplitude.com",
        "Product analytics software",
        "San Francisco, California",
    ),
    (
        2,
        "Mixpanel",
        "mixpanel",
        "https://mixpanel.com",
        "Product analytics software",
        "San Francisco, California",
    ),
    (
        2,
        "Nuro",
        "nuro",
        "https://www.nuro.ai",
        "Autonomous vehicle technology",
        "Mountain View, California",
    ),
    (
        2,
        "Coursera",
        "coursera",
        "https://www.coursera.org",
        "Education technology",
        "Mountain View, California",
    ),
    (
        2,
        "Fivetran",
        "fivetran",
        "https://www.fivetran.com",
        "Data integration software",
        "Oakland, California",
    ),
    (
        2,
        "Lucid Software",
        "lucidsoftware",
        "https://www.lucid.co",
        "Visual collaboration software",
        "South Jordan, Utah",
    ),
    (
        2,
        "Chime",
        "chime",
        "https://www.chime.com",
        "Financial technology",
        "San Francisco, California",
    ),
)

# Live Greenhouse Job Board API counts recorded during source verification.
ACTIVE_JOB_COUNTS = {
    "stripe": 554,
    "datadog": 441,
    "cloudflare": 299,
    "figma": 165,
    "discord": 48,
    "asana": 150,
    "duolingo": 66,
    "roblox": 222,
    "mongodb": 406,
    "affirm": 197,
    "coinbase": 170,
    "reddit": 171,
    "airtable": 40,
    "instacart": 115,
    "lyft": 168,
    "flexport": 164,
    "scaleai": 214,
    "okta": 339,
    "braze": 257,
    "klaviyo": 146,
    "elastic": 242,
    "brex": 304,
    "gusto": 94,
    "checkr": 50,
    "webflow": 29,
    "amplitude": 35,
    "mixpanel": 53,
    "nuro": 102,
    "coursera": 19,
    "fivetran": 198,
    "lucidsoftware": 39,
    "chime": 59,
}


def _companies_table() -> sa.Table:
    return sa.table(
        "companies",
        sa.column("company_id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("website_url", sa.String()),
        sa.column("careers_url", sa.String()),
        sa.column("industry", sa.String()),
        sa.column("headquarters_location", sa.String()),
        sa.column("country_code", sa.String()),
    )


def _boards_table() -> sa.Table:
    return sa.table(
        "greenhouse_boards",
        sa.column("token", sa.String()),
        sa.column("company_name", sa.String()),
        sa.column("board_url", sa.String()),
        sa.column("api_url", sa.String()),
        sa.column("active_job_count", sa.Integer()),
        sa.column("sample_job_titles", sa.JSON()),
        sa.column("discovered_urls", sa.JSON()),
        sa.column("crawl_indexes", sa.JSON()),
        sa.column("verified_at", sa.DateTime(timezone=True)),
    )


def upgrade() -> None:
    company_rows = []
    board_rows = []
    for _, name, token, website_url, industry, headquarters_location in COMPANY_SEEDS:
        board_url = f"https://job-boards.greenhouse.io/{token}"
        api_url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
        company_rows.append(
            {
                "company_id": uuid4(),
                "name": name,
                "website_url": website_url,
                "careers_url": board_url,
                "industry": industry,
                "headquarters_location": headquarters_location,
                "country_code": "US",
            }
        )
        board_rows.append(
            {
                "token": token,
                "company_name": name,
                "board_url": board_url,
                "api_url": api_url,
                "active_job_count": ACTIVE_JOB_COUNTS[token],
                "sample_job_titles": [],
                "discovered_urls": [board_url],
                "crawl_indexes": [SEED_PROVENANCE],
                "verified_at": VERIFIED_AT,
            }
        )

    companies = _companies_table()
    boards = _boards_table()
    bind = op.get_bind()
    company_insert = insert(companies)
    bind.execute(
        company_insert.on_conflict_do_update(
            constraint="uq_companies_website_url",
            set_={
                "name": company_insert.excluded.name,
                "careers_url": company_insert.excluded.careers_url,
                "industry": company_insert.excluded.industry,
                "headquarters_location": company_insert.excluded.headquarters_location,
                "country_code": company_insert.excluded.country_code,
            },
        ),
        company_rows,
    )
    board_insert = insert(boards)
    bind.execute(
        board_insert.on_conflict_do_update(
            index_elements=[boards.c.token],
            set_={
                "company_name": board_insert.excluded.company_name,
                "board_url": board_insert.excluded.board_url,
                "api_url": board_insert.excluded.api_url,
                "active_job_count": board_insert.excluded.active_job_count,
                "sample_job_titles": board_insert.excluded.sample_job_titles,
                "discovered_urls": board_insert.excluded.discovered_urls,
                "crawl_indexes": board_insert.excluded.crawl_indexes,
                "verified_at": board_insert.excluded.verified_at,
            },
        ),
        board_rows,
    )


def downgrade() -> None:
    # The upgrade upserts records that may predate this migration.  A rollback
    # therefore intentionally preserves the data instead of risking deletion
    # of records owned by an earlier import or a user.
    pass
