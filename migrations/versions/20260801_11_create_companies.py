"""Create companies and associate jobs with them.

Revision ID: 20260801_11
Revises: 20260731_10
Create Date: 2026-08-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260801_11"
down_revision: str | Sequence[str] | None = "20260731_10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("legal_name", sa.String(length=512), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("website_url", sa.String(length=2048), nullable=True),
        sa.Column("careers_url", sa.String(length=2048), nullable=True),
        sa.Column("linkedin_url", sa.String(length=2048), nullable=True),
        sa.Column("logo_url", sa.String(length=2048), nullable=True),
        sa.Column("industry", sa.String(length=255), nullable=True),
        sa.Column("organization_type", sa.String(length=64), nullable=True),
        sa.Column("headquarters_location", sa.String(length=512), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("employee_count_min", sa.Integer(), nullable=True),
        sa.Column("employee_count_max", sa.Integer(), nullable=True),
        sa.Column("founded_year", sa.Integer(), nullable=True),
        sa.Column(
            "is_staffing_agency",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
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
            "employee_count_min IS NULL OR employee_count_min >= 0",
            name="ck_companies_employee_count_min_nonnegative",
        ),
        sa.CheckConstraint(
            "employee_count_max IS NULL OR employee_count_max >= 0",
            name="ck_companies_employee_count_max_nonnegative",
        ),
        sa.CheckConstraint(
            "employee_count_min IS NULL OR employee_count_max IS NULL "
            "OR employee_count_min <= employee_count_max",
            name="ck_companies_employee_count_order",
        ),
        sa.CheckConstraint(
            "founded_year IS NULL OR founded_year BETWEEN 1000 AND 9999",
            name="ck_companies_founded_year",
        ),
        sa.CheckConstraint(
            "country_code IS NULL OR "
            "(char_length(country_code) = 2 AND country_code = upper(country_code))",
            name="ck_companies_country_code",
        ),
        sa.PrimaryKeyConstraint("company_id", name="pk_companies"),
        sa.UniqueConstraint("website_url", name="uq_companies_website_url"),
    )
    op.create_index("idx_companies_name", "companies", ["name"])
    op.create_index("idx_companies_industry", "companies", ["industry"])

    op.add_column("jobs", sa.Column("company_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_jobs_company_id_companies",
        "jobs",
        "companies",
        ["company_id"],
        ["company_id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_jobs_company_id", "jobs", ["company_id"])

    # Seed one company per exact existing name and connect legacy job rows.
    op.execute(
        """
        INSERT INTO companies (company_id, name)
        SELECT gen_random_uuid(), company_name
        FROM jobs
        WHERE company_name <> ''
        GROUP BY company_name
        """
    )
    op.execute(
        """
        UPDATE jobs
        SET company_id = companies.company_id
        FROM companies
        WHERE jobs.company_name = companies.name
        """
    )


def downgrade() -> None:
    op.drop_index("idx_jobs_company_id", table_name="jobs")
    op.drop_constraint("fk_jobs_company_id_companies", "jobs", type_="foreignkey")
    op.drop_column("jobs", "company_id")
    op.drop_index("idx_companies_industry", table_name="companies")
    op.drop_index("idx_companies_name", table_name="companies")
    op.drop_table("companies")
