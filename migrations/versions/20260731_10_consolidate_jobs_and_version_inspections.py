"""Consolidate job entries and version page inspections.

Revision ID: 20260731_10
Revises: 20260731_09
Create Date: 2026-07-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260731_10"
down_revision: str | Sequence[str] | None = "20260731_09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_job_page_inspections_job_page",
        "job_page_inspections",
        type_="unique",
    )
    op.add_column(
        "job_page_inspections",
        sa.Column("version", sa.String(length=64), server_default="legacy", nullable=False),
    )
    op.alter_column("job_page_inspections", "version", server_default=None)
    op.create_unique_constraint(
        "uq_job_page_inspections_job_page_version",
        "job_page_inspections",
        ["job_id", "page_index", "version"],
    )

    op.drop_index("idx_jobs_posted_since", table_name="jobs")
    op.alter_column("jobs", "title", new_column_name="job_title")
    op.alter_column("jobs", "location", new_column_name="job_location")
    op.alter_column("jobs", "description", new_column_name="jd_summary")
    op.alter_column("jobs", "posted_since", new_column_name="date_posted")
    op.alter_column(
        "jobs",
        "source",
        existing_type=sa.String(length=64),
        existing_nullable=True,
        nullable=True,
        server_default=sa.text("NULL"),
    )
    op.execute(
        """
        UPDATE jobs
        SET company_name = COALESCE(company_name, ''),
            job_location = COALESCE(job_location, ''),
            jd_summary = COALESCE(jd_summary, '')
        """
    )
    for column_name in ("company_name", "job_location", "jd_summary"):
        op.alter_column("jobs", column_name, existing_nullable=True, nullable=False)

    op.execute(
        """
        INSERT INTO jobs (
            job_id, source, job_title, url, company_name, job_location,
            jd_summary, date_posted, created_at, updated_at
        )
        SELECT
            gen_random_uuid(), source, job_title, url, company_name, job_location,
            jd_summary, date_posted, created_at, updated_at
        FROM job_entries
        ON CONFLICT (url) DO UPDATE SET
            source = EXCLUDED.source,
            job_title = EXCLUDED.job_title,
            company_name = EXCLUDED.company_name,
            job_location = EXCLUDED.job_location,
            jd_summary = EXCLUDED.jd_summary,
            date_posted = EXCLUDED.date_posted,
            updated_at = EXCLUDED.updated_at
        """
    )
    op.drop_table("job_entries")

    op.create_index("idx_jobs_date_posted", "jobs", ["date_posted"])
    op.create_index("idx_jobs_source", "jobs", ["source"])


def downgrade() -> None:
    op.create_table(
        "job_entries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("job_title", sa.String(length=512), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("year_of_experience", postgresql.INT4RANGE(), nullable=False),
        sa.Column("company_name", sa.String(length=512), nullable=False),
        sa.Column("job_location", sa.String(length=512), nullable=False),
        sa.Column("jd_summary", sa.Text(), nullable=False),
        sa.Column("pay_range", postgresql.INT8RANGE(), nullable=False),
        sa.Column("date_posted", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_job_entries"),
        sa.UniqueConstraint("url", name="uq_job_entries_url"),
        sa.CheckConstraint(
            "NOT isempty(year_of_experience) "
            "AND NOT lower_inf(year_of_experience) "
            "AND NOT upper_inf(year_of_experience) "
            "AND lower(year_of_experience) >= 0",
            name="ck_job_entries_experience_finite_nonnegative",
        ),
        sa.CheckConstraint(
            "NOT isempty(pay_range) "
            "AND NOT lower_inf(pay_range) "
            "AND NOT upper_inf(pay_range) "
            "AND lower(pay_range) >= 0",
            name="ck_job_entries_pay_finite_nonnegative",
        ),
    )
    op.execute(
        """
        INSERT INTO job_entries (
            source, job_title, url, year_of_experience, company_name,
            job_location, jd_summary, pay_range, date_posted, created_at, updated_at
        )
        SELECT
            COALESCE(source, 'unknown'), job_title, url, '[0,0]'::int4range, company_name,
            job_location, jd_summary, '[0,0]'::int8range, date_posted, created_at, updated_at
        FROM jobs
        """
    )
    op.create_index("idx_job_entries_company_name", "job_entries", ["company_name"])
    op.create_index("idx_job_entries_date_posted", "job_entries", ["date_posted"])
    op.create_index("idx_job_entries_source", "job_entries", ["source"])
    op.create_index(
        "idx_job_entries_years_experience_gist",
        "job_entries",
        ["year_of_experience"],
        postgresql_using="gist",
    )
    op.create_index(
        "idx_job_entries_pay_range_gist",
        "job_entries",
        ["pay_range"],
        postgresql_using="gist",
    )

    op.drop_index("idx_jobs_source", table_name="jobs")
    op.drop_index("idx_jobs_date_posted", table_name="jobs")
    op.alter_column("jobs", "source", server_default=None)
    for column_name in ("company_name", "job_location", "jd_summary"):
        op.alter_column("jobs", column_name, existing_nullable=False, nullable=True)
    op.alter_column("jobs", "job_title", new_column_name="title")
    op.alter_column("jobs", "job_location", new_column_name="location")
    op.alter_column("jobs", "jd_summary", new_column_name="description")
    op.alter_column("jobs", "date_posted", new_column_name="posted_since")
    op.create_index("idx_jobs_posted_since", "jobs", ["posted_since"])

    op.drop_constraint(
        "uq_job_page_inspections_job_page_version",
        "job_page_inspections",
        type_="unique",
    )
    op.drop_column("job_page_inspections", "version")
    op.create_unique_constraint(
        "uq_job_page_inspections_job_page",
        "job_page_inspections",
        ["job_id", "page_index"],
    )
