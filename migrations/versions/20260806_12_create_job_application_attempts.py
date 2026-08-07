"""Create durable, idempotent job application attempts.

Revision ID: 20260806_12
Revises: 20260801_11
Create Date: 2026-08-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260806_12"
down_revision: str | Sequence[str] | None = "20260801_11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_application_attempts",
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("job_url", sa.String(length=2048), nullable=False),
        sa.Column("job_key", sa.String(length=64), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_type", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
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
            "status IN ('in_progress', 'succeeded', 'failed')",
            name="ck_job_application_attempts_status",
        ),
        sa.CheckConstraint(
            "attempt_number > 0",
            name="ck_job_application_attempts_attempt_number_positive",
        ),
        sa.CheckConstraint(
            "(status = 'in_progress' AND completed_at IS NULL) OR "
            "(status IN ('succeeded', 'failed') AND completed_at IS NOT NULL)",
            name="ck_job_application_attempts_completion",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_job_application_attempts_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.job_id"],
            name="fk_job_application_attempts_job_id_jobs",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("attempt_id", name="pk_job_application_attempts"),
        sa.UniqueConstraint(
            "user_id",
            "job_key",
            "attempt_number",
            name="uq_job_application_attempts_user_job_number",
        ),
    )
    op.create_index(
        "idx_job_application_attempts_user_id",
        "job_application_attempts",
        ["user_id"],
    )
    op.create_index(
        "idx_job_application_attempts_job_id",
        "job_application_attempts",
        ["job_id"],
    )
    op.create_index(
        "idx_job_application_attempts_status",
        "job_application_attempts",
        ["status"],
    )
    op.create_index(
        "uq_job_application_attempts_active",
        "job_application_attempts",
        ["user_id", "job_key"],
        unique=True,
        postgresql_where=sa.text("status IN ('in_progress', 'succeeded')"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_job_application_attempts_active",
        table_name="job_application_attempts",
    )
    op.drop_index(
        "idx_job_application_attempts_status",
        table_name="job_application_attempts",
    )
    op.drop_index(
        "idx_job_application_attempts_job_id",
        table_name="job_application_attempts",
    )
    op.drop_index(
        "idx_job_application_attempts_user_id",
        table_name="job_application_attempts",
    )
    op.drop_table("job_application_attempts")
