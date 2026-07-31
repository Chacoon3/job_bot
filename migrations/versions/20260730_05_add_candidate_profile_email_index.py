"""Add an index for candidate profile email lookups.

Revision ID: 20260730_05
Revises: 20260730_04
Create Date: 2026-07-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_05"
down_revision: str | Sequence[str] | None = "20260730_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE candidate_profiles "
        "SET email = lower(btrim(email)) "
        "WHERE email <> lower(btrim(email))"
    )
    op.create_index(
        "idx_candidate_profiles_email_latest_active",
        "candidate_profiles",
        [
            "email",
            sa.text("created_at DESC"),
            sa.text("id DESC"),
        ],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "idx_candidate_profiles_email_latest_active",
        table_name="candidate_profiles",
    )
