from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from itertools import islice
from typing import Iterator, TypeVar

from sqlalchemy import Select, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from job_bot.db.greenhouse_models import GreenhouseBoard
from job_bot.greenhouse.models import DiscoveredBoard

DEFAULT_UPSERT_BATCH_SIZE = 1_000

T = TypeVar("T")


def batched[T](items: Iterable[T], size: int) -> Iterator[list[T]]:
    iterator = iter(items)

    while batch := list(islice(iterator, size)):
        yield batch


def upsert_boards(
    session: Session,
    boards: Iterable[DiscoveredBoard],
    *,
    batch_size: int = DEFAULT_UPSERT_BATCH_SIZE,
) -> int:
    """Insert or refresh Greenhouse boards and return input rows processed."""
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    insert_statement = insert(GreenhouseBoard)
    excluded = insert_statement.excluded

    changed = or_(
        GreenhouseBoard.company_name.is_distinct_from(excluded.company_name),
        GreenhouseBoard.board_url.is_distinct_from(excluded.board_url),
        GreenhouseBoard.api_url.is_distinct_from(excluded.api_url),
        GreenhouseBoard.active_job_count.is_distinct_from(excluded.active_job_count),
        GreenhouseBoard.sample_job_titles.is_distinct_from(excluded.sample_job_titles),
        GreenhouseBoard.discovered_urls.is_distinct_from(excluded.discovered_urls),
        GreenhouseBoard.crawl_indexes.is_distinct_from(excluded.crawl_indexes),
        GreenhouseBoard.verified_at.is_distinct_from(excluded.verified_at),
    )

    upsert_statement = insert_statement.on_conflict_do_update(
        index_elements=[GreenhouseBoard.token],
        set_={
            GreenhouseBoard.company_name: excluded.company_name,
            GreenhouseBoard.board_url: excluded.board_url,
            GreenhouseBoard.api_url: excluded.api_url,
            GreenhouseBoard.active_job_count: excluded.active_job_count,
            GreenhouseBoard.sample_job_titles: excluded.sample_job_titles,
            GreenhouseBoard.discovered_urls: excluded.discovered_urls,
            GreenhouseBoard.crawl_indexes: excluded.crawl_indexes,
            GreenhouseBoard.verified_at: excluded.verified_at,
            GreenhouseBoard.updated_at: excluded.updated_at,
        },
        where=changed,
    )

    processed = 0

    for batch in batched(boards, batch_size):
        values = [
            board.model_dump(
                include={
                    "token",
                    "company_name",
                    "board_url",
                    "api_url",
                    "active_job_count",
                    "sample_job_titles",
                    "discovered_urls",
                    "crawl_indexes",
                    "verified_at",
                    "updated_at",
                }
            )
            for board in batch
        ]

        session.execute(upsert_statement, values)
        processed += len(values)

    return processed


def list_boards(
    session: Session,
    *,
    token: str | None = None,
    company_name: str | None = None,
    crawl_index: str | None = None,
    has_open_jobs: bool | None = None,
    min_active_job_count: int | None = None,
    max_active_job_count: int | None = None,
    verified_after: datetime | None = None,
    verified_before: datetime | None = None,
    sort_by: str = "verified_at",
    sort_desc: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[GreenhouseBoard], int]:
    """Return a filtered, paginated board list and the total matching count."""
    statement: Select[tuple[GreenhouseBoard]] = select(GreenhouseBoard)
    count_statement: Select[tuple[int]] = select(GreenhouseBoard.id)

    if token:
        statement = statement.where(GreenhouseBoard.token.ilike(f"%{token}%"))
        count_statement = count_statement.where(GreenhouseBoard.token.ilike(f"%{token}%"))

    if company_name:
        statement = statement.where(GreenhouseBoard.company_name.ilike(f"%{company_name}%"))
        count_statement = count_statement.where(
            GreenhouseBoard.company_name.ilike(f"%{company_name}%")
        )

    if crawl_index:
        statement = statement.where(GreenhouseBoard.crawl_indexes.contains([crawl_index]))
        count_statement = count_statement.where(
            GreenhouseBoard.crawl_indexes.contains([crawl_index])
        )

    if has_open_jobs is True:
        statement = statement.where(GreenhouseBoard.active_job_count > 0)
        count_statement = count_statement.where(GreenhouseBoard.active_job_count > 0)

    if has_open_jobs is False:
        statement = statement.where(GreenhouseBoard.active_job_count == 0)
        count_statement = count_statement.where(GreenhouseBoard.active_job_count == 0)

    if min_active_job_count is not None:
        statement = statement.where(GreenhouseBoard.active_job_count >= min_active_job_count)
        count_statement = count_statement.where(
            GreenhouseBoard.active_job_count >= min_active_job_count
        )

    if max_active_job_count is not None:
        statement = statement.where(GreenhouseBoard.active_job_count <= max_active_job_count)
        count_statement = count_statement.where(
            GreenhouseBoard.active_job_count <= max_active_job_count
        )

    if verified_after is not None:
        statement = statement.where(GreenhouseBoard.verified_at >= verified_after)
        count_statement = count_statement.where(GreenhouseBoard.verified_at >= verified_after)

    if verified_before is not None:
        statement = statement.where(GreenhouseBoard.verified_at <= verified_before)
        count_statement = count_statement.where(GreenhouseBoard.verified_at <= verified_before)

    sortable_fields = {
        "verified_at": GreenhouseBoard.verified_at,
        "active_job_count": GreenhouseBoard.active_job_count,
        "company_name": GreenhouseBoard.company_name,
        "token": GreenhouseBoard.token,
    }
    order_column = sortable_fields.get(sort_by, GreenhouseBoard.verified_at)
    ordering = order_column.desc() if sort_desc else order_column.asc()

    rows = (
        session.execute(
            statement.order_by(ordering, GreenhouseBoard.id.asc()).limit(limit).offset(offset)
        )
        .scalars()
        .all()
    )
    total = len(session.execute(count_statement).scalars().all())

    return rows, total
