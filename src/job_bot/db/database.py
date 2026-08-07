from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import perf_counter_ns

import structlog
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from job_bot.config import setting_value, settings

DATABASE_URL_ENV = "DATABASE_URL"
DB_POOL_SIZE_ENV = "DB_POOL_SIZE"
DB_MAX_OVERFLOW_ENV = "DB_MAX_OVERFLOW"
DB_POOL_TIMEOUT_ENV = "DB_POOL_TIMEOUT_SECONDS"
DB_POOL_RECYCLE_ENV = "DB_POOL_RECYCLE_SECONDS"

logger = structlog.get_logger(__name__)


class TimedAsyncSession(AsyncSession):
    """Log the database time spent committing or rolling back a transaction."""

    def _record_transaction(self, operation: str, started_at: int, status: str) -> None:
        logger.info(
            "database_transaction_completed",
            operation=operation,
            status=status,
            duration_ms=round((perf_counter_ns() - started_at) / 1_000_000, 3),
        )

    async def commit(self) -> None:
        started_at = perf_counter_ns()
        try:
            await super().commit()
        except Exception:
            self._record_transaction("commit", started_at, "error")
            raise
        self._record_transaction("commit", started_at, "success")

    async def rollback(self) -> None:
        started_at = perf_counter_ns()
        try:
            await super().rollback()
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


def create_database_engine(database_url: str | None = None) -> AsyncEngine:
    url = database_url or settings().DATABASE_URL
    if not url:
        raise RuntimeError(
            f"{DATABASE_URL_ENV} is required; expected a "
            "postgresql+psycopg://user:password@host:5432/database URL"
        )
    return create_async_engine(
        url,
        pool_size=_integer_setting(DB_POOL_SIZE_ENV, 10, minimum=1),
        max_overflow=_integer_setting(DB_MAX_OVERFLOW_ENV, 20),
        pool_timeout=_integer_setting(DB_POOL_TIMEOUT_ENV, 30, minimum=1),
        pool_recycle=_integer_setting(DB_POOL_RECYCLE_ENV, 1_800, minimum=1),
        pool_pre_ping=True,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[TimedAsyncSession]:
    return async_sessionmaker(bind=engine, class_=TimedAsyncSession, expire_on_commit=False)


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[TimedAsyncSession],
) -> AsyncIterator[TimedAsyncSession]:
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
