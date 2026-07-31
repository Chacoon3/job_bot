from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from job_bot.db.candidate_profile_models import CandidateProfileRecord
from job_bot.schemas import CandidateProfile


def profile_from_record(record: CandidateProfileRecord) -> CandidateProfile:
    """Build the API schema from explicitly stored profile columns."""
    return CandidateProfile.model_validate(
        {field_name: getattr(record, field_name) for field_name in CandidateProfile.model_fields}
    )


def get_profile_version(
    session: Session,
    candidate_id: UUID,
    version: int | None = None,
) -> CandidateProfileRecord | None:
    """Return one active version, defaulting to the latest active version."""
    statement = select(CandidateProfileRecord).where(
        CandidateProfileRecord.candidate_id == candidate_id,
        CandidateProfileRecord.deleted_at.is_(None),
    )
    if version is not None:
        statement = statement.where(CandidateProfileRecord.version == version)
    else:
        statement = statement.order_by(CandidateProfileRecord.version.desc())

    return session.scalars(statement).first()


def create_profile_version(
    session: Session,
    *,
    candidate_id: UUID,
    profile: CandidateProfile,
    resume_filename: str,
    resume_sha256: str,
) -> CandidateProfileRecord:
    """Append a profile version while serializing writers for one candidate."""
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:candidate_id, 0))"),
        {"candidate_id": str(candidate_id)},
    )
    latest_version = session.scalar(
        select(func.max(CandidateProfileRecord.version)).where(
            CandidateProfileRecord.candidate_id == candidate_id
        )
    )
    record = CandidateProfileRecord(
        candidate_id=candidate_id,
        version=(latest_version or 0) + 1,
        **profile.model_dump(mode="json"),
        resume_filename=resume_filename,
        resume_sha256=resume_sha256,
    )
    session.add(record)
    session.flush()
    return record


def delete_profile_version(
    session: Session,
    candidate_id: UUID,
    version: int | None = None,
) -> CandidateProfileRecord | None:
    """Soft-delete one version, defaulting to the latest active version."""
    record = get_profile_version(session, candidate_id, version)
    if record is None:
        return None

    record.deleted_at = datetime.now(UTC)
    session.flush()
    return record
