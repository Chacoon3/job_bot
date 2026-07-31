"""Create jobs and job page inspections.

Revision ID: 20260731_09
Revises: 20260731_08
Create Date: 2026-07-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260731_09"
down_revision: str | Sequence[str] | None = "20260731_08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("company_name", sa.String(length=512), nullable=True),
        sa.Column("location", sa.String(length=512), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("posted_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("job_id", name="pk_jobs"),
        sa.UniqueConstraint("url", name="uq_jobs_url"),
    )
    op.create_index("idx_jobs_company_name", "jobs", ["company_name"], unique=False)
    op.create_index("idx_jobs_posted_since", "jobs", ["posted_since"], unique=False)

    op.create_table(
        "job_page_inspections",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("page_index", sa.Integer(), nullable=False),
        sa.Column("inspection", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "page_index >= 0",
            name="ck_job_page_inspections_page_index",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.job_id"],
            name="fk_job_page_inspections_job_id_jobs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_job_page_inspections"),
        sa.UniqueConstraint(
            "job_id",
            "page_index",
            name="uq_job_page_inspections_job_page",
        ),
    )
    op.create_index(
        "idx_job_page_inspections_job_id",
        "job_page_inspections",
        ["job_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_job_page_inspections_job_id",
        table_name="job_page_inspections",
    )
    op.drop_table("job_page_inspections")
    op.drop_index("idx_jobs_posted_since", table_name="jobs")
    op.drop_index("idx_jobs_company_name", table_name="jobs")
    op.drop_table("jobs")
