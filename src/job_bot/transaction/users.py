from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from job_bot.data.schemas import User
from job_bot.db.user_models import User as ORMUser


def canonical_email(email: str) -> str:
    return email.strip().casefold()


def user_from_record(record: ORMUser) -> User:
    """Build the Pydantic domain model from its ORM representation."""
    return User.model_validate(
        {field_name: getattr(record, field_name) for field_name in User.model_fields}
    )


def get_user_by_email(session: Session, email: str) -> ORMUser | None:
    """Return a user by canonical email address."""
    statement = select(ORMUser).where(ORMUser.email == canonical_email(email))
    return session.scalars(statement).first()


def get_user_by_id(session: Session, user_id: UUID) -> ORMUser | None:
    """Return a user by its immutable identifier."""
    return session.get(ORMUser, user_id)


def upsert_user(
    session: Session,
    *,
    user: User,
    resume_filename: str,
    resume_sha256: str,
) -> ORMUser:
    """Create or replace a user identified by email address."""
    email = canonical_email(str(user.email))
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:email, 0))"),
        {"email": email},
    )

    record = get_user_by_email(session, email)
    values = user.model_dump(mode="json")
    if record is None:
        record = ORMUser(
            id=uuid4(),
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

    session.flush()
    return record


def update_user(
    session: Session,
    *,
    user_id: UUID,
    user: User,
    resume_filename: str,
    resume_sha256: str,
) -> ORMUser | None:
    """Replace an existing user identified by its immutable identifier."""
    record = get_user_by_id(session, user_id)
    if record is None:
        return None

    for field_name, value in user.model_dump(mode="json").items():
        setattr(record, field_name, value)
    record.resume_filename = resume_filename
    record.resume_sha256 = resume_sha256
    session.flush()
    return record


def delete_user(session: Session, user_id: UUID) -> ORMUser | None:
    """Permanently delete a user by its immutable identifier."""
    record = get_user_by_id(session, user_id)
    if record is None:
        return None

    session.delete(record)
    session.flush()
    return record
