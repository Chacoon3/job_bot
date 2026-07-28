from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.dialects.postgresql import Range

from job_bot.db.greenhouse_models import GreenhouseBoard
from job_bot.db.job_models import JobEntry


class JobEntrySchema(BaseModel):
    """Transport-safe representation of a persisted or discovered job."""

    id: int | None = None
    source: str = "openai_web_search"
    job_title: str
    url: str
    year_of_experience_minimum: int = Field(ge=0)
    year_of_experience_maximum: int = Field(ge=0)
    company_name: str
    job_location: str
    jd_summary: str
    pay_range_minimum: int = Field(ge=0)
    pay_range_maximum: int = Field(ge=0)
    date_posted: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_orm_model(cls, job: JobEntry) -> JobEntrySchema:
        return cls(
            id=job.id,
            source=job.source,
            job_title=job.job_title,
            url=job.url,
            year_of_experience_minimum=job.year_of_experience.lower,
            year_of_experience_maximum=job.year_of_experience.upper,
            company_name=job.company_name,
            job_location=job.job_location,
            jd_summary=job.jd_summary,
            pay_range_minimum=job.pay_range.lower,
            pay_range_maximum=job.pay_range.upper,
            date_posted=job.date_posted,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )

    def to_orm_model(self) -> JobEntry:
        return JobEntry(
            id=self.id,
            source=self.source,
            job_title=self.job_title,
            url=self.url,
            year_of_experience=Range(
                self.year_of_experience_minimum,
                self.year_of_experience_maximum,
                bounds="[]",
            ),
            company_name=self.company_name,
            job_location=self.job_location,
            jd_summary=self.jd_summary,
            pay_range=Range(
                self.pay_range_minimum,
                self.pay_range_maximum,
                bounds="[]",
            ),
            date_posted=self.date_posted,
        )


class GreenhouseBoardSchema(BaseModel):
    """Transport-safe representation of a persisted Greenhouse board."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    token: str
    company_name: str | None
    board_url: str
    api_url: str
    active_job_count: int
    sample_job_titles: list[str]
    discovered_urls: list[str]
    crawl_indexes: list[str]
    verified_at: datetime
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_model(cls, board: GreenhouseBoard) -> GreenhouseBoardSchema:
        return cls.model_validate(board)


class ApplicationStatus(BaseModel):
    job: JobEntrySchema
    status: Literal["applied", "failed"]
    message: str | None = None


class EducationDegree(BaseModel):
    degree: str
    field_of_study: str
    institution: str
    duration_minimum: int
    duration_maximum: int
    gpa: float


class CandidateProfile(BaseModel):
    name: str
    email: str
    phone_area_code: str
    phone: str
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None
    education: list[EducationDegree]
    resume_text: str
    require_sponsorship: bool = True
    summary: str

    def to_prompt_text(self) -> str:
        """Convert the candidate profile to a prompt text for LLMs."""

        education_str = "\n".join(
            [
                f"- {edu.degree} in {edu.field_of_study} from {edu.institution} "
                f"({edu.duration_minimum}-{edu.duration_maximum} years, GPA: {edu.gpa})"
                for edu in self.education
            ]
        )
        return (
            f"Name: {self.name}\n"
            f"Email: {self.email}\n"
            f"Phone Area Code: {self.phone_area_code}\n"
            f"Phone: {self.phone}\n"
            f"LinkedIn: {self.linkedin_url}\n"
            f"GitHub: {self.github_url}\n"
            f"Portfolio: {self.portfolio_url}\n"
            f"Require Sponsorship: {'Yes' if self.require_sponsorship else 'No'}\n"
            f"Education:\n{education_str}\n"
            f"Resume Text:\n{self.resume_text}\n"
            f"Summary:\n{self.summary}"
        )
