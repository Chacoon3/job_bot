from __future__ import annotations

from sqlalchemy.dialects import mysql
from sqlalchemy.pool import QueuePool
from sqlalchemy.schema import CreateTable

from job_bot.db.database import create_database_engine
from job_bot.db.greenhouse_models import GreenhouseBoard


def test_greenhouse_board_compiles_to_mysql_ddl() -> None:
    ddl = str(CreateTable(GreenhouseBoard.__table__).compile(dialect=mysql.dialect()))

    assert "CREATE TABLE greenhouse_boards" in ddl
    assert "token VARCHAR(255) NOT NULL" in ddl
    assert "sample_job_titles JSON NOT NULL" in ddl
    assert "verified_at DATETIME(6) NOT NULL" in ddl
    assert "UNIQUE (token)" in ddl


def test_mysql_engine_uses_configured_connection_pool(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DB_POOL_SIZE", "4")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "6")
    monkeypatch.setenv("DB_POOL_TIMEOUT_SECONDS", "12")
    monkeypatch.setenv("DB_POOL_RECYCLE_SECONDS", "900")

    engine = create_database_engine("mysql+pymysql://user:password@localhost/job_bot")

    try:
        assert isinstance(engine.pool, QueuePool)
        assert engine.pool.size() == 4
        assert engine.pool._max_overflow == 6
        assert engine.pool._timeout == 12
        assert engine.pool._recycle == 900
        assert engine.pool._pre_ping is True
    finally:
        engine.dispose()
