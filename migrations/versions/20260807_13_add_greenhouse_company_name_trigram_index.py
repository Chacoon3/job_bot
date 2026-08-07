"""Enable fuzzy greenhouse board company-name search.

Revision ID: 20260807_13
Revises: 20260806_12
Create Date: 2026-08-07
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260807_13"
down_revision: str | Sequence[str] | None = "20260806_12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_index(
        "idx_greenhouse_boards_company_name_trgm",
        "greenhouse_boards",
        ["company_name"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"company_name": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_index("idx_greenhouse_boards_company_name_trgm", table_name="greenhouse_boards")
