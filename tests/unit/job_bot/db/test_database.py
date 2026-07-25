from __future__ import annotations

from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from job_bot.db import database
from job_bot.db.database import TimedSession, create_session_factory


def test_session_factory_tracks_commit_execution_time(monkeypatch) -> None:
    logger = Mock()
    monkeypatch.setattr(database, "logger", logger)
    engine = create_engine("sqlite://")
    session = create_session_factory(engine)()

    try:
        assert isinstance(session, TimedSession)
        session.execute(text("SELECT 1"))
        session.commit()
    finally:
        session.close()
        engine.dispose()

    logger.info.assert_called_once()
    (event,) = logger.info.call_args.args
    fields = logger.info.call_args.kwargs
    assert event == "database_transaction_completed"
    assert fields["operation"] == "commit"
    assert fields["status"] == "success"
    assert fields["duration_ms"] >= 0


def test_session_tracks_failed_transaction_time(monkeypatch) -> None:
    logger = Mock()
    monkeypatch.setattr(database, "logger", logger)
    session = TimedSession()
    failure = RuntimeError("commit failed")

    def fail_commit(_: Session) -> None:
        raise failure

    monkeypatch.setattr(Session, "commit", fail_commit)

    with pytest.raises(RuntimeError) as exc_info:
        session.commit()

    assert exc_info.value is failure
    logger.info.assert_called_once_with(
        "database_transaction_completed",
        operation="commit",
        status="error",
        duration_ms=pytest.approx(0, abs=100),
    )
