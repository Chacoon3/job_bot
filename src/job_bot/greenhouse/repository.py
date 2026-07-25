from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import Select, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from job_bot.db.greenhouse_models import GreenhouseBoard
from job_bot.greenhouse.models import DiscoveredBoard


def upsert_boards(session: Session, boards: Iterable[DiscoveredBoard]) -> int:
    """Insert or refresh Greenhouse boards and return the number processed."""
    count = 0

    for board in boards:
        values = board.model_dump()
        statement = insert(GreenhouseBoard).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[GreenhouseBoard.token],
            set_={
                "company_name": statement.excluded.company_name,
                "board_url": statement.excluded.board_url,
                "api_url": statement.excluded.api_url,
                "active_job_count": statement.excluded.active_job_count,
                "sample_job_titles": statement.excluded.sample_job_titles,
                "discovered_urls": statement.excluded.discovered_urls,
                "crawl_indexes": statement.excluded.crawl_indexes,
                "verified_at": statement.excluded.verified_at,
                "updated_at": text("CURRENT_TIMESTAMP"),
            },
        )
        session.execute(statement)
        count += 1

    return count


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
