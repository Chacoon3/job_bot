from __future__ import annotations

import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from job_bot.logging import configure_logging

DATABASE_URL_ENV = "DATABASE_URL"

config = context.config

configure_logging()

# Migrations are deliberately explicit. Runtime ORM metadata is not used for
# schema generation or autogeneration.
target_metadata = None


def database_url() -> str:
    url = os.getenv(DATABASE_URL_ENV)
    if not url:
        raise RuntimeError(
            f"{DATABASE_URL_ENV} is required; expected a "
            "postgresql+psycopg://user:password@host:5432/database URL"
        )
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    settings = config.get_section(config.config_ini_section, {})
    settings["sqlalchemy.url"] = database_url()
    connectable = engine_from_config(
        settings,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()

    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
