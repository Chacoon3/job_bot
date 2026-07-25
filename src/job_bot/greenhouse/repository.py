from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import text
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
