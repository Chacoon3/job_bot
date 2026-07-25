from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock

from sqlalchemy.dialects import postgresql
from sqlalchemy.pool import QueuePool
from sqlalchemy.schema import CreateTable

from job_bot.db.database import create_database_engine
from job_bot.db.greenhouse_models import GreenhouseBoard
from job_bot.greenhouse.models import DiscoveredBoard
from job_bot.greenhouse.repository import upsert_boards


def _board(token: str) -> DiscoveredBoard:
    return DiscoveredBoard(
        token=token,
        board_url=f"https://job-boards.greenhouse.io/{token}",
        api_url=f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
        active_job_count=1,
        verified_at=datetime(2026, 7, 25, tzinfo=UTC),
    )


def test_greenhouse_board_compiles_to_postgresql_ddl() -> None:
    ddl = str(CreateTable(GreenhouseBoard.__table__).compile(dialect=postgresql.dialect()))

    assert "CREATE TABLE greenhouse_boards" in ddl
    assert "token VARCHAR(255) NOT NULL" in ddl
    assert "sample_job_titles JSONB NOT NULL" in ddl
    assert "verified_at TIMESTAMP WITH TIME ZONE NOT NULL" in ddl
    assert "UNIQUE (token)" in ddl


def test_postgresql_engine_uses_configured_connection_pool(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DB_POOL_SIZE", "4")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "6")
    monkeypatch.setenv("DB_POOL_TIMEOUT_SECONDS", "12")
    monkeypatch.setenv("DB_POOL_RECYCLE_SECONDS", "900")

    engine = create_database_engine("postgresql+psycopg://user:password@localhost/job_bot")

    try:
        assert isinstance(engine.pool, QueuePool)
        assert engine.pool.size() == 4
        assert engine.pool._max_overflow == 6
        assert engine.pool._timeout == 12
        assert engine.pool._recycle == 900
        assert engine.pool._pre_ping is True
    finally:
        engine.dispose()


def test_upsert_boards_executes_one_statement_per_batch() -> None:
    session = Mock()

    count = upsert_boards(session, (_board(str(index)) for index in range(5)), batch_size=2)

    assert count == 5
    assert session.execute.call_count == 3

    first_call = session.execute.call_args_list[0]
    first_statement = first_call.args[0]
    first_values = first_call.args[1]
    compiled = str(first_statement.compile(dialect=postgresql.dialect()))
    assert len(first_values) == 2
    assert "ON CONFLICT (token) DO UPDATE" in compiled


def test_upsert_boards_does_not_execute_for_empty_input() -> None:
    session = Mock()

    count = upsert_boards(session, [])

    assert count == 0
    session.execute.assert_not_called()


def test_upsert_boards_rejects_invalid_batch_size() -> None:
    session = Mock()

    try:
        upsert_boards(session, [_board("example")], batch_size=0)
    except ValueError as exc:
        assert str(exc) == "batch_size must be at least 1"
    else:
        raise AssertionError("Expected invalid batch size to raise ValueError")

    session.execute.assert_not_called()
