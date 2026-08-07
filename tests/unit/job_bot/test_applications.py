from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from job_bot import applications
from job_bot.applications import (
    canonical_job_url,
    complete_application_attempt,
    job_identity_key,
    reserve_application_attempt,
    run_application_once,
)
from job_bot.db.application_models import JobApplicationAttempt


def test_canonical_job_url_removes_only_tracking_data() -> None:
    first = canonical_job_url(
        "HTTPS://Careers.Example.com:443/jobs/123/?utm_source=email&department=engineering#apply"
    )
    second = canonical_job_url(
        "https://careers.example.com/jobs/123?department=engineering&utm_medium=social"
    )

    assert first == "https://careers.example.com/jobs/123?department=engineering"
    assert second == first
    assert job_identity_key(first) == job_identity_key(second)


@pytest.mark.parametrize(
    "job_url",
    ["", "not-a-url", "file:///tmp/job", "https://user:pass@example.com/job"],
)
def test_canonical_job_url_rejects_unsafe_or_relative_values(job_url: str) -> None:
    with pytest.raises(ValueError):
        canonical_job_url(job_url)


def _session_with_active(active=None, attempt_number: int = 0) -> Mock:
    session = Mock()
    session.scalars.return_value.first.return_value = active
    session.scalar.return_value = attempt_number
    return session


def test_successful_attempt_prevents_another_reservation() -> None:
    user_id = uuid4()
    existing = JobApplicationAttempt(
        attempt_id=uuid4(),
        user_id=user_id,
        job_url="https://example.com/jobs/1",
        job_key="a" * 64,
        attempt_number=1,
        status="succeeded",
        started_at=datetime.now(UTC),
        lease_expires_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    session = _session_with_active(existing)

    reservation = reserve_application_attempt(
        session,
        user_id=user_id,
        job_url=existing.job_url,
    )

    assert reservation.attempt is existing
    assert reservation.should_execute is False
    assert reservation.reason == "already_succeeded"
    session.add.assert_not_called()


def test_failed_history_gets_a_numbered_retry() -> None:
    session = _session_with_active(None, attempt_number=2)
    user_id = uuid4()
    timestamp = datetime(2026, 8, 6, tzinfo=UTC)

    reservation = reserve_application_attempt(
        session,
        user_id=user_id,
        job_url="https://example.com/jobs/1?utm_source=test",
        now=timestamp,
    )

    assert reservation.should_execute is True
    assert reservation.reason == "new_attempt"
    assert reservation.attempt.attempt_number == 2
    assert reservation.attempt.status == "in_progress"
    assert reservation.attempt.job_url == "https://example.com/jobs/1"
    assert reservation.attempt.lease_expires_at == timestamp + timedelta(hours=1)
    session.add.assert_called_once_with(reservation.attempt)
    session.flush.assert_called_once_with()


def test_expired_attempt_is_failed_before_retry() -> None:
    timestamp = datetime(2026, 8, 6, tzinfo=UTC)
    existing = JobApplicationAttempt(
        attempt_id=uuid4(),
        user_id=uuid4(),
        job_url="https://example.com/jobs/1",
        job_key="a" * 64,
        attempt_number=1,
        status="in_progress",
        started_at=timestamp - timedelta(hours=1),
        lease_expires_at=timestamp - timedelta(minutes=30),
    )
    session = _session_with_active(existing, attempt_number=2)

    reservation = reserve_application_attempt(
        session,
        user_id=existing.user_id,
        job_url=existing.job_url,
        now=timestamp,
    )

    assert existing.status == "failed"
    assert existing.completed_at == timestamp
    assert existing.error_type == "ApplicationAttemptLeaseExpired"
    assert reservation.attempt.attempt_number == 2
    assert session.flush.call_count == 2


def test_complete_attempt_records_failure_details() -> None:
    attempt = SimpleNamespace(status="in_progress")
    session = Mock()
    session.scalar.return_value = attempt
    failure = RuntimeError("browser failed")

    result = complete_application_attempt(
        session,
        uuid4(),
        status="failed",
        error=failure,
    )

    assert result is attempt
    assert attempt.status == "failed"
    assert attempt.error_type == "RuntimeError"
    assert attempt.error_message == "browser failed"
    assert attempt.completed_at is not None


def test_run_application_once_skips_prior_success(monkeypatch) -> None:
    attempt = SimpleNamespace(attempt_id=uuid4(), status="succeeded")
    reservation = applications.ApplicationReservation(
        attempt=attempt,
        should_execute=False,
        reason="already_succeeded",
    )
    monkeypatch.setattr(
        applications,
        "reserve_application_attempt",
        lambda *_args, **_kwargs: reservation,
    )
    operation = AsyncMock()
    session = Mock()

    result = asyncio.run(
        run_application_once(
            session,
            user_id=uuid4(),
            job_url="https://example.com/jobs/1",
            operation=operation,
        )
    )

    assert result.executed is False
    assert result.reason == "already_succeeded"
    operation.assert_not_awaited()
    session.commit.assert_called_once_with()


def test_run_application_once_records_success(monkeypatch) -> None:
    attempt = SimpleNamespace(attempt_id=uuid4(), status="in_progress")
    completed = SimpleNamespace(attempt_id=attempt.attempt_id, status="succeeded")
    reservation = applications.ApplicationReservation(attempt, True, "new_attempt")
    monkeypatch.setattr(
        applications,
        "reserve_application_attempt",
        lambda *_args, **_kwargs: reservation,
    )
    complete = Mock(return_value=completed)
    monkeypatch.setattr(applications, "complete_application_attempt", complete)
    operation = AsyncMock()
    session = Mock()

    result = asyncio.run(
        run_application_once(
            session,
            user_id=uuid4(),
            job_url="https://example.com/jobs/1",
            operation=operation,
        )
    )

    assert result.executed is True
    assert result.attempt is completed
    operation.assert_awaited_once_with()
    complete.assert_called_once_with(session, attempt.attempt_id, status="succeeded")
    assert session.commit.call_count == 2


def test_run_application_once_records_failure_and_reraises(monkeypatch) -> None:
    attempt = SimpleNamespace(attempt_id=uuid4(), status="in_progress")
    reservation = applications.ApplicationReservation(attempt, True, "new_attempt")
    monkeypatch.setattr(
        applications,
        "reserve_application_attempt",
        lambda *_args, **_kwargs: reservation,
    )
    complete = Mock(return_value=attempt)
    monkeypatch.setattr(applications, "complete_application_attempt", complete)
    failure = RuntimeError("submission failed")

    async def fail() -> None:
        raise failure

    session = Mock()
    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(
            run_application_once(
                session,
                user_id=uuid4(),
                job_url="https://example.com/jobs/1",
                operation=fail,
            )
        )

    assert exc_info.value is failure
    complete.assert_called_once_with(
        session,
        attempt.attempt_id,
        status="failed",
        error=failure,
    )
    assert session.commit.call_count == 2
