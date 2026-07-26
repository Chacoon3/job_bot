from sqlalchemy import select
from sqlalchemy.orm import Session

from job_bot.db.job_models import JobEntryRecord, db_range_to_interval_values
from job_bot.flow import Interval, JobEntry
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
        records = (
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
        return [self._to_job_entry(record) for record in records]

    @staticmethod
    def _to_job_entry(record: JobEntryRecord) -> JobEntry:
        experience_min, experience_max = db_range_to_interval_values(
            record.year_of_experience
        )
        pay_min, pay_max = db_range_to_interval_values(record.pay_range)
        return JobEntry(
            job_title=record.job_title,
            url=record.url,
            year_of_experience=Interval(
                minimum=experience_min,
                maximum=experience_max,
            ),
            company_name=record.company_name,
            job_location=record.job_location,
            jd_summary=record.jd_summary,
            pay_range=Interval(minimum=pay_min, maximum=pay_max),
            date_posted=record.date_posted,
        )
