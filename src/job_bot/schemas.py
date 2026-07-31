from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
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


JobFormFieldKey = Literal[
    # Identity
    "first_name",
    "last_name",
    # Contact
    "email",
    "phone_country",
    "phone",
    "address_line_1",
    "address_line_2",
    "city",
    "state",
    "postal_code",
    "country",
    # Application materials
    "attach_resume_button",
    "attach_cover_letter_button",
    # Online profiles
    "linkedin_url",
    "github_url",
    "portfolio_url",
    "website_url",
    # Work authorization
    "authorized_to_work",
    "requires_sponsorship",
    "visa_status",
    # Job preferences
    "desired_salary",
    "available_start_date",
    "willing_to_relocate",
    "referral_source",
    # Voluntary demographic / EEO
    "gender",
    "is_hispanic_or_latino",
    "race",
    "disability_status",
    "veteran_status",
    # Consent
    "privacy_consent",
    "communications_consent",
    "terms_acknowledgement",
    # Long-tail fields
    "custom_question",
    "unknown",
    # final options
    "submit_button",
]


YesNoOption = Literal["yes", "no", "decline"]
VeteranOption = Literal["yes", "no", "decline"]
DisabilityOption = Literal["yes", "no", "decline"]
VeteranStatusOption = VeteranOption
DisabilityStatusOption = DisabilityOption
GenderOption = Literal["male", "female", "nonbinary", "self_describe", "decline"]
RaceEthnicityOption = Literal[
    "american_indian_alaska_native",
    "asian",
    "black",
    "hispanic_latino",
    "native_hawaiian_pacific_islander",
    "white",
    "two_or_more",
    "other",
    "decline",
]


class User(BaseModel):
    """All application and identity information owned by a user."""

    first_name: str
    last_name: str
    email: EmailStr
    phone_country: str
    phone: str
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None

    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None
    website_url: str | None = None

    @field_validator("email", mode="after")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        """Store a canonical, case-insensitive email identity."""
        return str(value).casefold()

    authorized_to_work: YesNoOption = "yes"
    requires_sponsorship: YesNoOption = "yes"
    visa_status: str | None = None

    willing_to_relocate: YesNoOption = "yes"
    gender: GenderOption | None = None
    is_hispanic_or_latino: YesNoOption = "no"
    race: RaceEthnicityOption = "asian"
    disability_status: DisabilityStatusOption = "no"
    veteran_status: VeteranStatusOption = "no"

    education: list[EducationDegree]
    resume_text: str
    summary: str

    def to_prompt_text(self) -> str:
        """Convert the user to prompt text for LLMs."""

        education_str = "\n".join(
            [
                f"- {edu.degree} in {edu.field_of_study} from {edu.institution} "
                f"({edu.duration_minimum}-{edu.duration_maximum} years, GPA: {edu.gpa})"
                for edu in self.education
            ]
        )
        return (
            f"Name: {self.first_name} {self.last_name}\n"
            f"Email: {self.email}\n"
            f"Phone Country Code: {self.phone_country}\n"
            f"Phone: {self.phone}\n"
            f"LinkedIn: {self.linkedin_url}\n"
            f"GitHub: {self.github_url}\n"
            f"Portfolio: {self.portfolio_url}\n"
            f"Requires Sponsorship: {self.requires_sponsorship.title()}\n"
            f"Education:\n{education_str}\n"
            f"Summary:\n{self.summary}"
        )

    def get_answer(self, field_key: JobFormFieldKey) -> Any:
        """Get the answer for a given field key."""
        return getattr(self, field_key, None)


class UserResponse(BaseModel):
    user_id: UUID
    user: User
    resume_filename: str
    created_at: datetime
    updated_at: datetime


InteractionKind = Literal[
    "text",
    "textarea",
    "select",
    "autocomplete",
    "radio",
    "checkbox",
    "file_upload",
    "button",
    "contenteditable",
    "date",
    "unknown",
]


class FormOption(BaseModel):
    label: str
    value: str | None = None
    selected: bool = False
    disabled: bool = False


class FormField(BaseModel):
    # 内部稳定标识，不一定等于 DOM id
    field_key: JobFormFieldKey | None = None

    interaction_kind: InteractionKind = "unknown"

    # DOM 身份信息
    element_id: str | None = None
    input_name: str | None = None
    test_id: str | None = None

    # 控件语义
    tag: str
    role: str | None = None
    input_type: str | None = None
    accessible_name: str | None = None
    labels: list[str] = Field(default_factory=list)
    placeholder: str | None = None

    # 控件数据
    current_value: str | bool | list[str] | None = None
    options: list[FormOption] = Field(default_factory=list)

    # 控件状态
    required: bool = False
    visible: bool = True
    enabled: bool = True
    editable: bool = False
    readonly: bool = False
    checked: bool | None = None
    multiple: bool = False

    # 作用域与结构
    form_id: str | None = None
    group_key: str | None = None
    group_label: str | None = None
    component: Literal[
        "standalone",
        "phone_country",
        "phone_number",
        "date_month",
        "date_day",
        "date_year",
        "other",
    ] = "standalone"

    # iframe 信息
    frame_url: str | None = None
    frame_name: str | None = None


class DropdownOption(BaseModel):
    index: int
    label: str
    value: str | None = None
    element_id: str | None = None
    disabled: bool = False

    # Some custom dropdowns do not expose selection semantically.
    selected: bool | None = None

    def __str__(self) -> str:
        return (
            f"DropdownOption(index={self.index}, label={self.label}, "
            f"value={self.value}, selected={self.selected})"
        )

    def __repr__(self) -> str:
        return self.__str__()


class DropdownSnapshot(BaseModel):
    kind: Literal[
        "native_select",
        "finite_combobox",
        "autocomplete",
    ]

    options: list[DropdownOption] = Field(default_factory=list)

    # True: all options are known.
    # False: known to be partial.
    # None: completeness cannot be determined.
    complete: bool | None = None

    listbox_id: str | None = None
