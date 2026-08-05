from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter_ns

import structlog
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from job_bot.config import setting_value, settings

DATABASE_URL_ENV = "DATABASE_URL"
DB_POOL_SIZE_ENV = "DB_POOL_SIZE"
DB_MAX_OVERFLOW_ENV = "DB_MAX_OVERFLOW"
DB_POOL_TIMEOUT_ENV = "DB_POOL_TIMEOUT_SECONDS"
DB_POOL_RECYCLE_ENV = "DB_POOL_RECYCLE_SECONDS"

logger = structlog.get_logger(__name__)


class TimedSession(Session):
    """Log the database time spent committing or rolling back a transaction."""

    def _record_transaction(self, operation: str, started_at: int, status: str) -> None:
        logger.info(
            "database_transaction_completed",
            operation=operation,
            status=status,
            duration_ms=round((perf_counter_ns() - started_at) / 1_000_000, 3),
        )

    def commit(self) -> None:
        started_at = perf_counter_ns()
        try:
            super().commit()
        except Exception:
            self._record_transaction("commit", started_at, "error")
            raise
        self._record_transaction("commit", started_at, "success")

    def rollback(self) -> None:
        started_at = perf_counter_ns()
        try:
            super().rollback()
        except Exception:
            self._record_transaction("rollback", started_at, "error")
            raise
        self._record_transaction("rollback", started_at, "success")


def _integer_setting(name: str, default: int, minimum: int = 0) -> int:
    raw_value = setting_value(name)
    if raw_value is None:
        return default

    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc

    if value < minimum:
        raise RuntimeError(f"{name} must be at least {minimum}")
    return value


def create_database_engine(database_url: str | None = None) -> Engine:
    url = database_url or settings().DATABASE_URL
    if not url:
        raise RuntimeError(
            f"{DATABASE_URL_ENV} is required; expected a "
            "postgresql+psycopg://user:password@host:5432/database URL"
        )
    return create_engine(
        url,
        pool_size=_integer_setting(DB_POOL_SIZE_ENV, 10, minimum=1),
        max_overflow=_integer_setting(DB_MAX_OVERFLOW_ENV, 20),
        pool_timeout=_integer_setting(DB_POOL_TIMEOUT_ENV, 30, minimum=1),
        pool_recycle=_integer_setting(DB_POOL_RECYCLE_ENV, 1_800, minimum=1),
        pool_pre_ping=True,
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, class_=TimedSession, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
