from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from job_bot.db.user_models import User as ORMUser
from job_bot.schemas import User


def user_from_record(record: ORMUser) -> User:
    """Build the Pydantic domain model from its ORM representation."""
    return User.model_validate(
        {field_name: getattr(record, field_name) for field_name in User.model_fields}
    )


def get_user(session: Session, user_id: UUID) -> ORMUser | None:
    """Return an active user by ID."""
    statement = select(ORMUser).where(
        ORMUser.id == user_id,
        ORMUser.deleted_at.is_(None),
    )
    return session.scalars(statement).first()


def upsert_user(
    session: Session,
    *,
    user_id: UUID,
    user: User,
    resume_filename: str,
    resume_sha256: str,
) -> ORMUser:
    """Create or replace the current data owned by a user."""
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:user_id, 0))"),
        {"user_id": str(user_id)},
    )

    record = session.get(ORMUser, user_id)
    values = user.model_dump(mode="json")
    if record is None:
        record = ORMUser(
            id=user_id,
            **values,
            resume_filename=resume_filename,
            resume_sha256=resume_sha256,
        )
        session.add(record)
    else:
        for field_name, value in values.items():
            setattr(record, field_name, value)
        record.resume_filename = resume_filename
        record.resume_sha256 = resume_sha256
        record.deleted_at = None

    session.flush()
    return record


def delete_user(session: Session, user_id: UUID) -> ORMUser | None:
    """Soft-delete a user."""
    record = get_user(session, user_id)
    if record is None:
        return None

    record.deleted_at = datetime.now(UTC)
    session.flush()
    return record
