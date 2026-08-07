from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from job_bot.config import settings
from job_bot.db.application_models import JobApplicationAttempt

ApplicationAttemptStatus = Literal["in_progress", "succeeded", "failed"]
ApplicationReservationReason = Literal["new_attempt", "already_succeeded", "in_progress"]
JOB_IDENTITY_VERSION = 1
DEFAULT_ATTEMPT_LEASE = timedelta(hours=1)
TRACKING_QUERY_PARAMETERS = {"fbclid", "gclid", "msclkid"}


@dataclass(frozen=True)
class ApplicationReservation:
    attempt: JobApplicationAttempt
    should_execute: bool
    reason: ApplicationReservationReason


@dataclass(frozen=True)
class ApplicationRunResult:
    attempt: JobApplicationAttempt
    executed: bool
    reason: ApplicationReservationReason


def canonical_job_url(job_url: str) -> str:
    """Normalize a public job URL without discarding job-identifying parameters."""
    raw_url = job_url.strip()
    parsed = urlsplit(raw_url)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("job_url must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ValueError("job_url must not contain credentials")

    scheme = parsed.scheme.casefold()
    hostname = parsed.hostname.encode("idna").decode("ascii").casefold()
    port = parsed.port
    if port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        hostname = f"{hostname}:{port}"

    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    query_items = [
        (name, value)
        for name, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not name.casefold().startswith("utm_")
        and name.casefold() not in TRACKING_QUERY_PARAMETERS
    ]
    query = urlencode(sorted(query_items))
    canonical = urlunsplit((scheme, hostname, path, query, ""))
    if len(canonical) > 2048:
        raise ValueError("job_url exceeds the 2048-character storage limit")
    return canonical


def job_identity_key(job_url: str) -> tuple[str, str]:
    canonical_url = canonical_job_url(job_url)
    payload = f"v{JOB_IDENTITY_VERSION}\0{canonical_url}".encode()
    return canonical_url, hashlib.sha256(payload).hexdigest()


def _active_attempt(
    session: Session,
    user_id: UUID,
    job_key: str,
) -> JobApplicationAttempt | None:
    statement = (
        select(JobApplicationAttempt)
        .where(
            JobApplicationAttempt.user_id == user_id,
            JobApplicationAttempt.job_key == job_key,
            JobApplicationAttempt.status.in_(("in_progress", "succeeded")),
        )
        .with_for_update()
    )
    return session.scalars(statement).first()


def reserve_application_attempt(
    session: Session,
    *,
    user_id: UUID,
    job_url: str,
    job_id: UUID | None = None,
    now: datetime | None = None,
    lease: timedelta = DEFAULT_ATTEMPT_LEASE,
) -> ApplicationReservation:
    """Reserve one execution while preserving failed-attempt history.

    The caller must commit before starting slow browser work so concurrent
    requests can observe the reservation.
    """
    if lease <= timedelta(0):
        raise ValueError("lease must be positive")
    canonical_url, job_key = job_identity_key(job_url)
    timestamp = now or datetime.now(UTC)
    lock_key = f"{user_id}:{job_key}"
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": lock_key},
    )

    existing = _active_attempt(session, user_id, job_key)
    if existing is not None and existing.status == "succeeded":
        return ApplicationReservation(existing, False, "already_succeeded")
    if existing is not None and existing.lease_expires_at > timestamp:
        return ApplicationReservation(existing, False, "in_progress")
    if existing is not None:
        existing.status = "failed"
        existing.completed_at = timestamp
        existing.error_type = "ApplicationAttemptLeaseExpired"
        existing.error_message = "The previous application attempt lease expired"
        session.flush()

    attempt_number = session.scalar(
        select(func.coalesce(func.max(JobApplicationAttempt.attempt_number), 0) + 1).where(
            JobApplicationAttempt.user_id == user_id,
            JobApplicationAttempt.job_key == job_key,
        )
    )
    attempt = JobApplicationAttempt(
        user_id=user_id,
        job_id=job_id,
        job_url=canonical_url,
        job_key=job_key,
        attempt_number=int(attempt_number or 1),
        status="in_progress",
        started_at=timestamp,
        lease_expires_at=timestamp + lease,
    )
    session.add(attempt)
    session.flush()
    return ApplicationReservation(attempt, True, "new_attempt")


def complete_application_attempt(
    session: Session,
    attempt_id: UUID,
    *,
    status: Literal["succeeded", "failed"],
    error: BaseException | None = None,
    result: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> JobApplicationAttempt:
    attempt = session.scalar(
        select(JobApplicationAttempt)
        .where(JobApplicationAttempt.attempt_id == attempt_id)
        .with_for_update()
    )
    if attempt is None:
        raise LookupError(f"Application attempt {attempt_id} was not found")
    if attempt.status != "in_progress":
        raise RuntimeError(f"Application attempt is already {attempt.status}")

    attempt.status = status
    attempt.completed_at = now or datetime.now(UTC)
    attempt.result = result
    if error is not None:
        attempt.error_type = type(error).__name__[:255]
        attempt.error_message = str(error)[:4000]
    session.flush()
    return attempt


async def run_application_once(
    session: Session,
    *,
    user_id: UUID,
    job_url: str,
    operation: Callable[[], Awaitable[None]],
    job_id: UUID | None = None,
) -> ApplicationRunResult:
    """Reserve, execute, and durably complete one idempotent application."""
    reservation = reserve_application_attempt(
        session,
        user_id=user_id,
        job_url=job_url,
        job_id=job_id,
        lease=timedelta(seconds=settings().APPLICATION_ATTEMPT_LEASE_SECONDS),
    )
    session.commit()
    if not reservation.should_execute:
        return ApplicationRunResult(reservation.attempt, False, reservation.reason)

    attempt_id = reservation.attempt.attempt_id
    try:
        await operation()
    except Exception as exc:
        complete_application_attempt(session, attempt_id, status="failed", error=exc)
        session.commit()
        raise

    attempt = complete_application_attempt(session, attempt_id, status="succeeded")
    session.commit()
    return ApplicationRunResult(attempt, True, "new_attempt")
