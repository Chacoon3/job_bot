from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from job_bot.db.user_models import User as ORMUser
from job_bot.schemas import User


def canonical_email(email: str) -> str:
    return email.strip().casefold()


def user_from_record(record: ORMUser) -> User:
    """Build the Pydantic domain model from its ORM representation."""
    return User.model_validate(
        {field_name: getattr(record, field_name) for field_name in User.model_fields}
    )


def get_user(session: Session, email: str) -> ORMUser | None:
    """Return a user by canonical email address."""
    statement = select(ORMUser).where(ORMUser.email == canonical_email(email))
    return session.scalars(statement).first()


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

    record = get_user(session, email)
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


def delete_user(session: Session, email: str) -> ORMUser | None:
    """Permanently delete a user by email address."""
    record = get_user(session, email)
    if record is None:
        return None

    session.delete(record)
    session.flush()
    return record
