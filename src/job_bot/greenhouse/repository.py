from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import func
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.orm import Session

from job_bot.db.greenhouse_models import GreenhouseBoard
from job_bot.greenhouse.models import DiscoveredBoard


def upsert_boards(session: Session, boards: Iterable[DiscoveredBoard]) -> int:
    """Insert or refresh Greenhouse boards and return the number processed."""
    count = 0

    for board in boards:
        values = board.model_dump()
        statement = insert(GreenhouseBoard).values(**values)
        statement = statement.on_duplicate_key_update(
            company_name=statement.inserted.company_name,
            board_url=statement.inserted.board_url,
            api_url=statement.inserted.api_url,
            active_job_count=statement.inserted.active_job_count,
            sample_job_titles=statement.inserted.sample_job_titles,
            discovered_urls=statement.inserted.discovered_urls,
            crawl_indexes=statement.inserted.crawl_indexes,
            verified_at=statement.inserted.verified_at,
            updated_at=func.current_timestamp(),
        )
        session.execute(statement)
        count += 1

    return count
