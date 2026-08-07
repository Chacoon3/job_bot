from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

from sqlalchemy.dialects import postgresql
from sqlalchemy.pool import QueuePool
from sqlalchemy.schema import CreateTable
from sqlalchemy.sql import Select

from job_bot.db.database import create_database_engine
from job_bot.db.greenhouse_models import GreenhouseBoard
from job_bot.greenhouse.models import DiscoveredBoard
from job_bot.greenhouse.repository import (
    COMPANY_NAME_SIMILARITY_THRESHOLD,
    _build_company_name_filter,
    list_boards,
    upsert_boards,
)


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
        asyncio.run(engine.dispose())


def test_upsert_boards_executes_one_statement_per_batch() -> None:
    session = AsyncMock()

    count = asyncio.run(
        upsert_boards(session, (_board(str(index)) for index in range(5)), batch_size=2)
    )

    assert count == 5
    assert session.execute.call_count == 3

    first_call = session.execute.call_args_list[0]
    first_statement = first_call.args[0]
    first_values = first_call.args[1]
    compiled = str(first_statement.compile(dialect=postgresql.dialect()))
    assert len(first_values) == 2
    assert "ON CONFLICT (token) DO UPDATE" in compiled


def test_upsert_boards_does_not_execute_for_empty_input() -> None:
    session = AsyncMock()

    count = asyncio.run(upsert_boards(session, []))

    assert count == 0
    session.execute.assert_not_called()


def test_upsert_boards_rejects_invalid_batch_size() -> None:
    session = AsyncMock()

    try:
        asyncio.run(upsert_boards(session, [_board("example")], batch_size=0))
    except ValueError as exc:
        assert str(exc) == "batch_size must be at least 1"
    else:
        raise AssertionError("Expected invalid batch size to raise ValueError")

    session.execute.assert_not_called()


def test_company_name_filter_uses_trigram_fuzzy_matching() -> None:
    clause = _build_company_name_filter("  Acne   Corporation ")
    compiled = str(
        clause.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )

    assert "ILIKE '%%Acne Corporation%%'" in compiled
    assert "similarity(" in compiled
    assert f">= {COMPANY_NAME_SIMILARITY_THRESHOLD}" in compiled
    assert "word_similarity(" in compiled
    assert (
        "regexp_replace(lower(coalesce(greenhouse_boards.company_name, '')), '\\\\s+', ' ', 'g')"
        in compiled
    )


def test_list_boards_applies_same_company_name_filter_to_rows_and_count() -> None:
    session = AsyncMock()
    rows_result = Mock()
    rows_scalars = Mock()
    rows_scalars.all.return_value = []
    rows_result.scalars.return_value = rows_scalars
    count_result = Mock()
    count_scalars = Mock()
    count_scalars.all.return_value = []
    count_result.scalars.return_value = count_scalars
    session.execute.side_effect = [rows_result, count_result]

    asyncio.run(list_boards(session, company_name="Acne"))

    assert session.execute.call_count == 2

    row_statement = session.execute.call_args_list[0].args[0]
    count_statement = session.execute.call_args_list[1].args[0]
    assert isinstance(row_statement, Select)
    assert isinstance(count_statement, Select)

    row_sql = str(
        row_statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    count_sql = str(
        count_statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )

    assert "ILIKE '%%Acne%%'" in row_sql
    assert "similarity(" in row_sql
    assert "word_similarity(" in row_sql
    assert "ILIKE '%%Acne%%'" in count_sql
    assert "similarity(" in count_sql
    assert "word_similarity(" in count_sql
