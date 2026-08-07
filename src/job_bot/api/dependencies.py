from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import async_sessionmaker

from job_bot.config import settings
from job_bot.db.database import TimedAsyncSession, create_database_engine, create_session_factory


@lru_cache(maxsize=1)
def _get_session_factory() -> async_sessionmaker[TimedAsyncSession]:
    return create_session_factory(create_database_engine())


async def get_session() -> AsyncIterator[TimedAsyncSession]:
    session = _get_session_factory()()
    try:
        yield session
    finally:
        await session.close()


def require_browser_automation() -> None:
    """Reject browser work on the lightweight API runtime."""
    if not settings().BROWSER_AUTOMATION_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Browser automation is available from the browser-worker service",
        )
