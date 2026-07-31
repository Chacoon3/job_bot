from sqlalchemy import select
from sqlalchemy.orm import Session

from job_bot.db.job_models import Job
from job_bot.job_providers.job_provider import JobProvider
from job_bot.schemas import JobEntrySchema

GREENHOUSE_SOURCE = "greenhouse"


class GreenHouseJobProvider(JobProvider):
    """Provide Greenhouse jobs already persisted in the job entry store."""

    def __init__(
        self,
        session: Session,
    ) -> None:
        self.session = session

    def provide(self) -> list[JobEntrySchema]:
        jobs = (
            self.session.execute(
                select(Job)
                .where(Job.source == GREENHOUSE_SOURCE)
                .order_by(
                    Job.date_posted.desc().nullslast(),
                    Job.job_id.asc(),
                )
            )
            .scalars()
            .all()
        )
        return [JobEntrySchema.from_orm_model(job) for job in jobs]
