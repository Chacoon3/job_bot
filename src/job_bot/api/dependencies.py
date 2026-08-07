from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, sessionmaker

from job_bot.config import settings
from job_bot.db.database import create_database_engine, create_session_factory


@lru_cache(maxsize=1)
def _get_session_factory() -> sessionmaker[Session]:
    return create_session_factory(create_database_engine())


def get_session() -> Iterator[Session]:
    session = _get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def require_browser_automation() -> None:
    """Reject browser work on the lightweight API runtime."""
    if not settings().BROWSER_AUTOMATION_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Browser automation is available from the browser-worker service",
        )
