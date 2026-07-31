from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from job_bot.db.base import Base


class CandidateProfileRecord(Base):
    """An immutable, versioned snapshot of one candidate's profile."""

    __tablename__ = "candidate_profiles"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_candidate_profiles_version_positive"),
        CheckConstraint(
            "authorized_to_work IN ('yes', 'no', 'decline')",
            name="ck_candidate_profiles_authorized_to_work",
        ),
        CheckConstraint(
            "requires_sponsorship IN ('yes', 'no', 'decline')",
            name="ck_candidate_profiles_requires_sponsorship",
        ),
        CheckConstraint(
            "willing_to_relocate IN ('yes', 'no', 'decline')",
            name="ck_candidate_profiles_willing_to_relocate",
        ),
        CheckConstraint(
            "gender IS NULL OR gender IN "
            "('male', 'female', 'nonbinary', 'self_describe', 'decline')",
            name="ck_candidate_profiles_gender",
        ),
        CheckConstraint(
            "is_hispanic_or_latino IN ('yes', 'no', 'decline')",
            name="ck_candidate_profiles_is_hispanic_or_latino",
        ),
        CheckConstraint(
            "race IN ("
            "'american_indian_alaska_native', 'asian', 'black', "
            "'hispanic_latino', 'native_hawaiian_pacific_islander', "
            "'white', 'two_or_more', 'other', 'decline'"
            ")",
            name="ck_candidate_profiles_race",
        ),
        CheckConstraint(
            "disability_status IN ('yes', 'no', 'decline')",
            name="ck_candidate_profiles_disability_status",
        ),
        CheckConstraint(
            "veteran_status IN ('yes', 'no', 'decline')",
            name="ck_candidate_profiles_veteran_status",
        ),
        CheckConstraint(
            "jsonb_typeof(education) = 'array'",
            name="ck_candidate_profiles_education_array",
        ),
        UniqueConstraint(
            "candidate_id",
            "version",
            name="uq_candidate_profiles_candidate_version",
        ),
        Index(
            "idx_candidate_profiles_candidate_version",
            "candidate_id",
            "version",
        ),
        Index("idx_candidate_profiles_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    candidate_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    first_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    phone_country: Mapped[str] = mapped_column(String(16), nullable=False)
    phone: Mapped[str] = mapped_column(String(64), nullable=False)
    address_line_1: Mapped[str | None] = mapped_column(String(512))
    address_line_2: Mapped[str | None] = mapped_column(String(512))
    city: Mapped[str | None] = mapped_column(String(255))
    state: Mapped[str | None] = mapped_column(String(255))
    postal_code: Mapped[str | None] = mapped_column(String(32))
    country: Mapped[str | None] = mapped_column(String(255))

    linkedin_url: Mapped[str | None] = mapped_column(String(2048))
    github_url: Mapped[str | None] = mapped_column(String(2048))
    portfolio_url: Mapped[str | None] = mapped_column(String(2048))
    website_url: Mapped[str | None] = mapped_column(String(2048))

    authorized_to_work: Mapped[str] = mapped_column(String(16), nullable=False)
    requires_sponsorship: Mapped[str] = mapped_column(String(16), nullable=False)
    visa_status: Mapped[str | None] = mapped_column(String(128))
    willing_to_relocate: Mapped[str] = mapped_column(String(16), nullable=False)
    gender: Mapped[str | None] = mapped_column(String(32))
    is_hispanic_or_latino: Mapped[str] = mapped_column(String(16), nullable=False)
    race: Mapped[str] = mapped_column(String(64), nullable=False)
    disability_status: Mapped[str] = mapped_column(String(16), nullable=False)
    veteran_status: Mapped[str] = mapped_column(String(16), nullable=False)

    education: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    resume_text: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)

    resume_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    resume_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


Index(
    "idx_candidate_profiles_email_latest_active",
    CandidateProfileRecord.email,
    CandidateProfileRecord.created_at.desc(),
    CandidateProfileRecord.id.desc(),
    postgresql_where=CandidateProfileRecord.deleted_at.is_(None),
)
