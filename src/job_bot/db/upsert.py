from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from functools import cache
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

POSTGRESQL_MAX_BIND_PARAMETERS = 65_535
DEFAULT_UPSERT_BATCH_SIZE = 5_000


def _column_name(column: Any) -> str:
    name = column if isinstance(column, str) else getattr(column, "key", None)
    if not isinstance(name, str) or not name:
        raise ValueError(f"Invalid ORM column reference: {column!r}")
    return name


@cache
def _resolve_upsert_metadata(
    model: type[Any],
    conflict_columns: tuple[Any, ...],
    update_columns: tuple[Any, ...],
) -> tuple[frozenset[str], tuple[str, ...], tuple[str, ...]]:
    """Resolve and cache mapped and requested column names for an ORM model."""
    mapped_columns = frozenset(column.key for column in inspect(model).columns)
    conflict_names = tuple(_column_name(column) for column in conflict_columns)
    update_names = tuple(_column_name(column) for column in update_columns)
    requested_columns = set(conflict_names) | set(update_names)
    unknown_columns = requested_columns - mapped_columns
    if unknown_columns:
        names = ", ".join(sorted(unknown_columns))
        raise ValueError(f"Columns are not mapped by {model.__name__}: {names}")
    return mapped_columns, conflict_names, update_names


async def batched_upsert(
    session: AsyncSession,
    model: type[Any],
    rows: Iterable[Mapping[str, Any]],
    *,
    conflict_columns: Sequence[Any],
    update_columns: Sequence[Any],
    batch_size: int = DEFAULT_UPSERT_BATCH_SIZE,
    max_bind_parameters: int = POSTGRESQL_MAX_BIND_PARAMETERS,
) -> int:
    """Upsert row mappings for a SQLAlchemy ORM model in parameter-safe batches.

    The statements remain part of the caller's transaction; this function does
    not flush or commit the session.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    if max_bind_parameters < 1:
        raise ValueError("max_bind_parameters must be at least 1")

    mapped_columns, conflict_names, update_names = _resolve_upsert_metadata(
        model,
        tuple(conflict_columns),
        tuple(update_columns),
    )
    if not conflict_names:
        raise ValueError("conflict_columns must not be empty")

    pending: list[Mapping[str, Any]] = []
    rows_processed = 0

    async def execute_batch() -> None:
        nonlocal rows_processed
        statement = insert(model).values(pending)
        if update_names:
            statement = statement.on_conflict_do_update(
                index_elements=list(conflict_names),
                set_={name: getattr(statement.excluded, name) for name in update_names},
            )
        else:
            statement = statement.on_conflict_do_nothing(index_elements=list(conflict_names))
        await session.execute(statement)
        rows_processed += len(pending)
        pending.clear()

    current_batch_limit = batch_size
    expected_keys: frozenset[str] | None = None
    for row in rows:
        row_keys = frozenset(row)
        if not row_keys:
            raise ValueError("upsert rows must not be empty")
        if not row_keys <= mapped_columns:
            names = ", ".join(sorted(row_keys - mapped_columns))
            raise ValueError(f"Columns are not mapped by {model.__name__}: {names}")
        if expected_keys is None:
            expected_keys = row_keys
            current_batch_limit = min(
                batch_size,
                max_bind_parameters // len(row_keys),
            )
            if current_batch_limit < 1:
                raise ValueError(
                    "max_bind_parameters is smaller than the number of values in one row"
                )
        elif row_keys != expected_keys:
            raise ValueError("all upsert rows must contain the same columns")

        pending.append(row)
        if len(pending) == current_batch_limit:
            await execute_batch()

    if pending:
        await execute_batch()
    return rows_processed
