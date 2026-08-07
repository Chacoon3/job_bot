from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from job_bot.db import database
from job_bot.db.database import TimedAsyncSession, create_database_engine, create_session_factory


def test_session_factory_tracks_commit_execution_time(monkeypatch) -> None:
    logger = Mock()
    monkeypatch.setattr(database, "logger", logger)
    engine = create_database_engine("postgresql+psycopg://user:password@localhost/job_bot")
    session = create_session_factory(engine)()

    try:
        assert isinstance(session, TimedAsyncSession)
        monkeypatch.setattr(AsyncSession, "commit", AsyncMock())
        asyncio.run(session.commit())
    finally:
        asyncio.run(session.close())
        asyncio.run(engine.dispose())

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
    session = TimedAsyncSession()
    failure = RuntimeError("commit failed")

    async def fail_commit(_: AsyncSession) -> None:
        raise failure

    monkeypatch.setattr(AsyncSession, "commit", fail_commit)

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(session.commit())

    assert exc_info.value is failure
    logger.info.assert_called_once_with(
        "database_transaction_completed",
        operation="commit",
        status="error",
        duration_ms=pytest.approx(0, abs=100),
    )
