from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from job_bot.db import greenhouse_models
from job_bot.db.base import Base

DATABASE_URL_ENV = "DATABASE_URL"
DB_POOL_SIZE_ENV = "DB_POOL_SIZE"
DB_MAX_OVERFLOW_ENV = "DB_MAX_OVERFLOW"
DB_POOL_TIMEOUT_ENV = "DB_POOL_TIMEOUT_SECONDS"
DB_POOL_RECYCLE_ENV = "DB_POOL_RECYCLE_SECONDS"


def _integer_setting(name: str, default: int, minimum: int = 0) -> int:
    raw_value = os.getenv(name)
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
    url = database_url or os.getenv(DATABASE_URL_ENV)
    if not url:
        raise RuntimeError(
            f"{DATABASE_URL_ENV} is required; expected a "
            "mysql+pymysql://user:password@host:3306/database URL"
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
    return sessionmaker(bind=engine, expire_on_commit=False)


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


def create_schema(engine: Engine) -> None:
    # The top-level model import registers tables with Base.metadata.
    _ = greenhouse_models
    Base.metadata.create_all(engine)
