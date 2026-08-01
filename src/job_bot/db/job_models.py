from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from job_bot.db.base import Base
from job_bot.db.company_models import Company


class Job(Base):
    """A normalized job posting and the owner of its page inspections."""

    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("url", name="uq_jobs_url"),
        Index("idx_jobs_company_name", "company_name"),
        Index("idx_jobs_company_id", "company_id"),
        Index("idx_jobs_date_posted", "date_posted"),
        Index("idx_jobs_source", "source"),
    )

    job_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("companies.company_id", ondelete="SET NULL"),
    )
    source: Mapped[str | None] = mapped_column(
        String(64), nullable=True, default=None, server_default=text("NULL")
    )
    job_title: Mapped[str] = mapped_column(String(512), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    company_name: Mapped[str] = mapped_column(String(512), nullable=False)
    job_location: Mapped[str] = mapped_column(String(512), nullable=False)
    jd_summary: Mapped[str] = mapped_column(Text, nullable=False)
    date_posted: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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

    page_inspections: Mapped[list[JobPageInspection]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="JobPageInspection.page_index",
    )
    company: Mapped[Company | None] = relationship()


class JobPageInspection(Base):
    """A JSON snapshot of a ``PageInspection`` for one page in a job flow."""

    __tablename__ = "job_page_inspections"
    __table_args__ = (
        CheckConstraint("page_index >= 0", name="ck_job_page_inspections_page_index"),
        UniqueConstraint(
            "job_id",
            "page_index",
            "version",
            name="uq_job_page_inspections_job_page_version",
        ),
        Index("idx_job_page_inspections_job_id", "job_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("jobs.job_id", ondelete="CASCADE"),
        nullable=False,
    )
    page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    inspection: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
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

    job: Mapped[Job] = relationship(back_populates="page_inspections")
