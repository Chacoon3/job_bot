"""Create the versioned candidate_profiles table.

Revision ID: 20260730_04
Revises: 20260725_03
Create Date: 2026-07-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260730_04"
down_revision: str | Sequence[str] | None = "20260725_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_profiles",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("first_name", sa.String(length=255), nullable=False),
        sa.Column("last_name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("phone_country", sa.String(length=16), nullable=False),
        sa.Column("phone", sa.String(length=64), nullable=False),
        sa.Column("address_line_1", sa.String(length=512), nullable=True),
        sa.Column("address_line_2", sa.String(length=512), nullable=True),
        sa.Column("city", sa.String(length=255), nullable=True),
        sa.Column("state", sa.String(length=255), nullable=True),
        sa.Column("postal_code", sa.String(length=32), nullable=True),
        sa.Column("country", sa.String(length=255), nullable=True),
        sa.Column("linkedin_url", sa.String(length=2048), nullable=True),
        sa.Column("github_url", sa.String(length=2048), nullable=True),
        sa.Column("portfolio_url", sa.String(length=2048), nullable=True),
        sa.Column("website_url", sa.String(length=2048), nullable=True),
        sa.Column("authorized_to_work", sa.String(length=16), nullable=False),
        sa.Column("requires_sponsorship", sa.String(length=16), nullable=False),
        sa.Column("visa_status", sa.String(length=128), nullable=True),
        sa.Column("willing_to_relocate", sa.String(length=16), nullable=False),
        sa.Column("gender", sa.String(length=32), nullable=True),
        sa.Column("is_hispanic_or_latino", sa.String(length=16), nullable=False),
        sa.Column("race", sa.String(length=64), nullable=False),
        sa.Column("disability_status", sa.String(length=16), nullable=False),
        sa.Column("veteran_status", sa.String(length=16), nullable=False),
        sa.Column(
            "education",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("resume_text", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("resume_filename", sa.String(length=512), nullable=False),
        sa.Column("resume_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "version > 0",
            name="ck_candidate_profiles_version_positive",
        ),
        sa.CheckConstraint(
            "authorized_to_work IN ('yes', 'no', 'decline')",
            name="ck_candidate_profiles_authorized_to_work",
        ),
        sa.CheckConstraint(
            "requires_sponsorship IN ('yes', 'no', 'decline')",
            name="ck_candidate_profiles_requires_sponsorship",
        ),
        sa.CheckConstraint(
            "willing_to_relocate IN ('yes', 'no', 'decline')",
            name="ck_candidate_profiles_willing_to_relocate",
        ),
        sa.CheckConstraint(
            "gender IS NULL OR gender IN "
            "('male', 'female', 'nonbinary', 'self_describe', 'decline')",
            name="ck_candidate_profiles_gender",
        ),
        sa.CheckConstraint(
            "is_hispanic_or_latino IN ('yes', 'no', 'decline')",
            name="ck_candidate_profiles_is_hispanic_or_latino",
        ),
        sa.CheckConstraint(
            "race IN ("
            "'american_indian_alaska_native', 'asian', 'black', "
            "'hispanic_latino', 'native_hawaiian_pacific_islander', "
            "'white', 'two_or_more', 'other', 'decline'"
            ")",
            name="ck_candidate_profiles_race",
        ),
        sa.CheckConstraint(
            "disability_status IN ('yes', 'no', 'decline')",
            name="ck_candidate_profiles_disability_status",
        ),
        sa.CheckConstraint(
            "veteran_status IN ('yes', 'no', 'decline')",
            name="ck_candidate_profiles_veteran_status",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(education) = 'array'",
            name="ck_candidate_profiles_education_array",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_candidate_profiles"),
        sa.UniqueConstraint(
            "candidate_id",
            "version",
            name="uq_candidate_profiles_candidate_version",
        ),
    )
    op.create_index(
        "idx_candidate_profiles_candidate_version",
        "candidate_profiles",
        ["candidate_id", "version"],
        unique=False,
    )
    op.create_index(
        "idx_candidate_profiles_created_at",
        "candidate_profiles",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_candidate_profiles_created_at", table_name="candidate_profiles")
    op.drop_index(
        "idx_candidate_profiles_candidate_version",
        table_name="candidate_profiles",
    )
    op.drop_table("candidate_profiles")
