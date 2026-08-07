from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from job_bot.data.schemas import JobEntrySchema
from job_bot.db.job_models import Job
from job_bot.job_providers.job_provider import JobProvider

GREENHOUSE_SOURCE = "greenhouse"


class GreenHouseJobProvider(JobProvider):
    """Provide Greenhouse jobs already persisted in the job entry store."""

    def __init__(
        self,
        session: AsyncSession,
    ) -> None:
        self.session = session

    async def provide(self) -> list[JobEntrySchema]:
        jobs = (
            (
                await self.session.execute(
                    select(Job)
                    .where(Job.source == GREENHOUSE_SOURCE)
                    .order_by(
                        Job.date_posted.desc().nullslast(),
                        Job.job_id.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        return [JobEntrySchema.from_orm_model(job) for job in jobs]
