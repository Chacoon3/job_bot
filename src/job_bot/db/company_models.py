from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from job_bot.db.base import Base


class Company(Base):
    """An organization that owns or publishes job postings."""

    __tablename__ = "companies"
    __table_args__ = (
        UniqueConstraint("website_url", name="uq_companies_website_url"),
        CheckConstraint(
            "employee_count_min IS NULL OR employee_count_min >= 0",
            name="ck_companies_employee_count_min_nonnegative",
        ),
        CheckConstraint(
            "employee_count_max IS NULL OR employee_count_max >= 0",
            name="ck_companies_employee_count_max_nonnegative",
        ),
        CheckConstraint(
            "employee_count_min IS NULL OR employee_count_max IS NULL "
            "OR employee_count_min <= employee_count_max",
            name="ck_companies_employee_count_order",
        ),
        CheckConstraint(
            "founded_year IS NULL OR founded_year BETWEEN 1000 AND 9999",
            name="ck_companies_founded_year",
        ),
        CheckConstraint(
            "country_code IS NULL OR "
            "(char_length(country_code) = 2 AND country_code = upper(country_code))",
            name="ck_companies_country_code",
        ),
        Index("idx_companies_name", "name"),
        Index("idx_companies_industry", "industry"),
    )

    company_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(512))
    description: Mapped[str | None] = mapped_column(Text)
    website_url: Mapped[str | None] = mapped_column(String(2048))
    careers_url: Mapped[str | None] = mapped_column(String(2048))
    linkedin_url: Mapped[str | None] = mapped_column(String(2048))
    logo_url: Mapped[str | None] = mapped_column(String(2048))
    industry: Mapped[str | None] = mapped_column(String(255))
    organization_type: Mapped[str | None] = mapped_column(String(64))
    headquarters_location: Mapped[str | None] = mapped_column(String(512))
    country_code: Mapped[str | None] = mapped_column(String(2))
    employee_count_min: Mapped[int | None] = mapped_column(Integer)
    employee_count_max: Mapped[int | None] = mapped_column(Integer)
    founded_year: Mapped[int | None] = mapped_column(Integer)
    is_staffing_agency: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
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
