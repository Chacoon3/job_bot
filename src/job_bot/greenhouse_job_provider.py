from sqlalchemy import select
from sqlalchemy.orm import Session

from job_bot.db.job_models import JobEntry
from job_bot.job_provider import JobProvider

GREENHOUSE_SOURCE = "greenhouse"


class GreenHouseJobProvider(JobProvider):
    """Provide Greenhouse jobs already persisted in the job entry store."""

    def __init__(
        self,
        session: Session,
    ) -> None:
        self.session = session

    def provide(self) -> list[JobEntry]:
        return list(
            self.session.execute(
                select(JobEntry)
                .where(JobEntry.source == GREENHOUSE_SOURCE)
                .order_by(
                    JobEntry.date_posted.desc().nullslast(),
                    JobEntry.id.asc(),
                )
            )
            .scalars()
            .all()
        )
