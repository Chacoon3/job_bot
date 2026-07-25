from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Index, Integer, String, text
from sqlalchemy.dialects.mysql import DATETIME, JSON
from sqlalchemy.orm import Mapped, mapped_column

from job_bot.db.base import Base


class GreenhouseBoard(Base):
    __tablename__ = "greenhouse_boards"
    __table_args__ = (
        Index("idx_greenhouse_boards_company_name", "company_name"),
        Index("idx_greenhouse_boards_active_jobs", "active_job_count"),
        Index("idx_greenhouse_boards_verified_at", "verified_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    company_name: Mapped[str | None] = mapped_column(String(512))
    board_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    api_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    active_job_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sample_job_titles: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    discovered_urls: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    crawl_indexes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # MySQL DATETIME does not retain offsets; all application values use UTC.
    verified_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
        onupdate=text("CURRENT_TIMESTAMP(6)"),
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
