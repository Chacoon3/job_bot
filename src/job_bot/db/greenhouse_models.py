from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from job_bot.db.base import Base


class GreenhouseBoard(Base):
    """Map the latest known state of a Greenhouse board to PostgreSQL.

    The token is the natural upsert key. Mutable discovery results such as job
    count, samples, provenance, and verification time are refreshed in place,
    while JSONB preserves list-shaped data without child tables. Alembic, rather
    than ORM metadata, owns creation and evolution of the database table.
    """

    __tablename__ = "greenhouse_boards"
    __table_args__ = (
        Index("idx_greenhouse_boards_company_name", "company_name"),
        Index(
            "idx_greenhouse_boards_company_name_trgm",
            "company_name",
            postgresql_using="gin",
            postgresql_ops={"company_name": "gin_trgm_ops"},
        ),
        Index("idx_greenhouse_boards_active_jobs", "active_job_count"),
        Index("idx_greenhouse_boards_verified_at", "verified_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    company_name: Mapped[str | None] = mapped_column(String(512))
    board_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    api_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    active_job_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sample_job_titles: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    discovered_urls: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    crawl_indexes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "token": self.token,
            "company_name": self.company_name,
            "board_url": self.board_url,
            "api_url": self.api_url,
            "active_job_count": self.active_job_count,
            "sample_job_titles": self.sample_job_titles,
            "discovered_urls": self.discovered_urls,
            "crawl_indexes": self.crawl_indexes,
            "verified_at": self.verified_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
