"""Create the greenhouse_boards table.

Revision ID: 20260724_01
Revises:
Create Date: 2026-07-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260724_01"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "greenhouse_boards",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("token", sa.String(length=255), nullable=False),
        sa.Column("company_name", sa.String(length=512), nullable=True),
        sa.Column("board_url", sa.String(length=2048), nullable=False),
        sa.Column("api_url", sa.String(length=2048), nullable=False),
        sa.Column(
            "active_job_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("sample_job_titles", postgresql.JSONB(), nullable=False),
        sa.Column("discovered_urls", postgresql.JSONB(), nullable=False),
        sa.Column("crawl_indexes", postgresql.JSONB(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_greenhouse_boards"),
        sa.UniqueConstraint("token", name="uq_greenhouse_boards_token"),
    )
    op.create_index(
        "idx_greenhouse_boards_company_name",
        "greenhouse_boards",
        ["company_name"],
        unique=False,
    )
    op.create_index(
        "idx_greenhouse_boards_active_jobs",
        "greenhouse_boards",
        ["active_job_count"],
        unique=False,
    )
    op.create_index(
        "idx_greenhouse_boards_verified_at",
        "greenhouse_boards",
        ["verified_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_greenhouse_boards_verified_at", table_name="greenhouse_boards")
    op.drop_index("idx_greenhouse_boards_active_jobs", table_name="greenhouse_boards")
    op.drop_index("idx_greenhouse_boards_company_name", table_name="greenhouse_boards")
    op.drop_table("greenhouse_boards")
