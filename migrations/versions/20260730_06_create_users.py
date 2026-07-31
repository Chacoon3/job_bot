"""Replace candidate_profiles with one current users table.

Revision ID: 20260730_06
Revises: 20260730_05
Create Date: 2026-07-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260730_06"
down_revision: str | Sequence[str] | None = "20260730_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _profile_columns() -> list[sa.Column]:
    return [
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
        sa.Column("education", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("resume_text", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("resume_filename", sa.String(length=512), nullable=False),
        sa.Column("resume_sha256", sa.String(length=64), nullable=False),
    ]


def _checks(prefix: str) -> list[sa.CheckConstraint]:
    return [
        sa.CheckConstraint(
            "authorized_to_work IN ('yes', 'no', 'decline')",
            name=f"ck_{prefix}_authorized_to_work",
        ),
        sa.CheckConstraint(
            "requires_sponsorship IN ('yes', 'no', 'decline')",
            name=f"ck_{prefix}_requires_sponsorship",
        ),
        sa.CheckConstraint(
            "willing_to_relocate IN ('yes', 'no', 'decline')",
            name=f"ck_{prefix}_willing_to_relocate",
        ),
        sa.CheckConstraint(
            "gender IS NULL OR gender IN "
            "('male', 'female', 'nonbinary', 'self_describe', 'decline')",
            name=f"ck_{prefix}_gender",
        ),
        sa.CheckConstraint(
            "is_hispanic_or_latino IN ('yes', 'no', 'decline')",
            name=f"ck_{prefix}_is_hispanic_or_latino",
        ),
        sa.CheckConstraint(
            "race IN ("
            "'american_indian_alaska_native', 'asian', 'black', "
            "'hispanic_latino', 'native_hawaiian_pacific_islander', "
            "'white', 'two_or_more', 'other', 'decline'"
            ")",
            name=f"ck_{prefix}_race",
        ),
        sa.CheckConstraint(
            "disability_status IN ('yes', 'no', 'decline')",
            name=f"ck_{prefix}_disability_status",
        ),
        sa.CheckConstraint(
            "veteran_status IN ('yes', 'no', 'decline')",
            name=f"ck_{prefix}_veteran_status",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(education) = 'array'",
            name=f"ck_{prefix}_education_array",
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        *_profile_columns(),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *_checks("users"),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )
    op.create_index("idx_users_email", "users", ["email"], unique=False)
    op.create_index("idx_users_created_at", "users", ["created_at"], unique=False)

    # Versioning is intentionally removed. Preserve the latest row for every
    # candidate ID, preferring an active row when one exists.
    op.execute(
        """
        INSERT INTO users (
            id, first_name, last_name, email, phone_country, phone,
            address_line_1, address_line_2, city, state, postal_code, country,
            linkedin_url, github_url, portfolio_url, website_url,
            authorized_to_work, requires_sponsorship, visa_status,
            willing_to_relocate, gender, is_hispanic_or_latino, race,
            disability_status, veteran_status, education, resume_text, summary,
            resume_filename, resume_sha256, created_at, updated_at, deleted_at
        )
        SELECT DISTINCT ON (candidate_id)
            candidate_id, first_name, last_name, email, phone_country, phone,
            address_line_1, address_line_2, city, state, postal_code, country,
            linkedin_url, github_url, portfolio_url, website_url,
            authorized_to_work, requires_sponsorship, visa_status,
            willing_to_relocate, gender, is_hispanic_or_latino, race,
            disability_status, veteran_status, education, resume_text, summary,
            resume_filename, resume_sha256, created_at, created_at, deleted_at
        FROM candidate_profiles
        ORDER BY candidate_id, (deleted_at IS NULL) DESC, version DESC, id DESC
        """
    )
    op.drop_table("candidate_profiles")


def downgrade() -> None:
    op.create_table(
        "candidate_profiles",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        *_profile_columns(),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("version > 0", name="ck_candidate_profiles_version_positive"),
        *_checks("candidate_profiles"),
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
    op.create_index(
        "idx_candidate_profiles_email_latest_active",
        "candidate_profiles",
        ["email", sa.text("created_at DESC"), sa.text("id DESC")],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.execute(
        """
        INSERT INTO candidate_profiles (
            candidate_id, version, first_name, last_name, email, phone_country,
            phone, address_line_1, address_line_2, city, state, postal_code,
            country, linkedin_url, github_url, portfolio_url, website_url,
            authorized_to_work, requires_sponsorship, visa_status,
            willing_to_relocate, gender, is_hispanic_or_latino, race,
            disability_status, veteran_status, education, resume_text, summary,
            resume_filename, resume_sha256, created_at, deleted_at
        )
        SELECT
            id, 1, first_name, last_name, email, phone_country, phone,
            address_line_1, address_line_2, city, state, postal_code, country,
            linkedin_url, github_url, portfolio_url, website_url,
            authorized_to_work, requires_sponsorship, visa_status,
            willing_to_relocate, gender, is_hispanic_or_latino, race,
            disability_status, veteran_status, education, resume_text, summary,
            resume_filename, resume_sha256, created_at, deleted_at
        FROM users
        """
    )
    op.drop_index("idx_users_created_at", table_name="users")
    op.drop_index("idx_users_email", table_name="users")
    op.drop_table("users")
