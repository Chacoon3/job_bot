from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, String, Text, text
from sqlalchemy.dialects.postgresql import INT4RANGE, INT8RANGE, Range
from sqlalchemy.orm import Mapped, mapped_column

from job_bot.db.base import Base


class JobEntryRecord(Base):
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
