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
from sqlalchemy.dialects.postgresql import INT4RANGE, INT8RANGE, JSONB, Range
from sqlalchemy.orm import Mapped, mapped_column, relationship

from job_bot.db.base import Base


class JobEntry(Base):
    """Persist a normalized job entry independently of its source provider."""

    __tablename__ = "job_entries"
    __table_args__ = (
        CheckConstraint(
            "NOT isempty(year_of_experience) "
            "AND NOT lower_inf(year_of_experience) "
            "AND NOT upper_inf(year_of_experience) "
            "AND lower(year_of_experience) >= 0",
            name="ck_job_entries_experience_finite_nonnegative",
        ),
        CheckConstraint(
            "NOT isempty(pay_range) "
            "AND NOT lower_inf(pay_range) "
            "AND NOT upper_inf(pay_range) "
            "AND lower(pay_range) >= 0",
            name="ck_job_entries_pay_finite_nonnegative",
        ),
        Index("idx_job_entries_company_name", "company_name"),
        Index("idx_job_entries_date_posted", "date_posted"),
        Index("idx_job_entries_source", "source"),
        Index(
            "idx_job_entries_years_experience_gist",
            "year_of_experience",
            postgresql_using="gist",
        ),
        Index(
            "idx_job_entries_pay_range_gist",
            "pay_range",
            postgresql_using="gist",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    job_title: Mapped[str] = mapped_column(String(512), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False, unique=True)
    year_of_experience: Mapped[Range[int]] = mapped_column(INT4RANGE, nullable=False)
    company_name: Mapped[str] = mapped_column(String(512), nullable=False)
    job_location: Mapped[str] = mapped_column(String(512), nullable=False)
    jd_summary: Mapped[str] = mapped_column(Text, nullable=False)
    pay_range: Mapped[Range[int]] = mapped_column(INT8RANGE, nullable=False)
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


class Job(Base):
    """A durable job posting that can have one inspection per application page."""

    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("url", name="uq_jobs_url"),
        Index("idx_jobs_posted_since", "posted_since"),
        Index("idx_jobs_company_name", "company_name"),
    )

    job_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    company_name: Mapped[str | None] = mapped_column(String(512))
    location: Mapped[str | None] = mapped_column(String(512))
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(64))
    posted_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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


class JobPageInspection(Base):
    """A JSON snapshot of a ``PageInspection`` for one page in a job flow."""

    __tablename__ = "job_page_inspections"
    __table_args__ = (
        CheckConstraint("page_index >= 0", name="ck_job_page_inspections_page_index"),
        UniqueConstraint(
            "job_id",
            "page_index",
            name="uq_job_page_inspections_job_page",
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
