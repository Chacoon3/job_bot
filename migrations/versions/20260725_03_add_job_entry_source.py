"""Add source provenance to job entries.

Revision ID: 20260725_03
Revises: 20260725_02
Create Date: 2026-07-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260725_03"
down_revision: str | Sequence[str] | None = "20260725_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "job_entries",
        sa.Column(
            "source",
            sa.String(length=64),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.alter_column("job_entries", "source", server_default=None)
    op.create_index(
        "idx_job_entries_source",
        "job_entries",
        ["source"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_job_entries_source", table_name="job_entries")
    op.drop_column("job_entries", "source")
