"""Clean users, make email unique, and remove deleted_at.

Revision ID: 20260730_07
Revises: 20260730_06
Create Date: 2026-07-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_07"
down_revision: str | Sequence[str] | None = "20260730_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # This schema change intentionally starts the user store from a clean slate.
    op.execute("DELETE FROM users")

    op.drop_index("idx_users_email", table_name="users")
    op.create_unique_constraint("uq_users_email", "users", ["email"])
    op.drop_column("users", "deleted_at")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_constraint("uq_users_email", "users", type_="unique")
    op.create_index("idx_users_email", "users", ["email"], unique=False)
