from sqlalchemy import select
from sqlalchemy.orm import Session

from job_bot.db.job_models import JobEntryRecord
from job_bot.job_provider import JobProvider

GREENHOUSE_SOURCE = "greenhouse"


class GreenHouseJobProvider(JobProvider):
    """Provide Greenhouse jobs already persisted in the job entry store."""

    def __init__(
        self,
        session: Session,
    ) -> None:
        self.session = session

    def provide(self) -> list[JobEntryRecord]:
        return list(
            self.session.execute(
                select(JobEntryRecord)
                .where(JobEntryRecord.source == GREENHOUSE_SOURCE)
                .order_by(
                    JobEntryRecord.date_posted.desc().nullslast(),
                    JobEntryRecord.id.asc(),
                )
            )
            .scalars()
            .all()
        )
