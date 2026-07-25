"""Create the job_entries table.

Revision ID: 20260725_02
Revises: 20260724_01
Create Date: 2026-07-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260725_02"
down_revision: str | Sequence[str] | None = "20260724_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_entries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_job_entries"),
        sa.UniqueConstraint("url", name="uq_job_entries_url"),
    )
    op.create_index(
        "idx_job_entries_company_name",
        "job_entries",
        ["company_name"],
        unique=False,
    )
    op.create_index(
        "idx_job_entries_date_posted",
        "job_entries",
        ["date_posted"],
        unique=False,
    )
    op.create_index(
        "idx_job_entries_years_experience_gist",
        "job_entries",
        ["year_of_experience"],
        unique=False,
        postgresql_using="gist",
    )
    op.create_index(
        "idx_job_entries_pay_range_gist",
        "job_entries",
        ["pay_range"],
        unique=False,
        postgresql_using="gist",
    )


def downgrade() -> None:
    op.drop_index("idx_job_entries_pay_range_gist", table_name="job_entries")
    op.drop_index("idx_job_entries_years_experience_gist", table_name="job_entries")
    op.drop_index("idx_job_entries_date_posted", table_name="job_entries")
    op.drop_index("idx_job_entries_company_name", table_name="job_entries")
    op.drop_table("job_entries")
