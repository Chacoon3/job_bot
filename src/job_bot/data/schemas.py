from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from job_bot.countries import regulate_country, regulate_phone_country_code
from job_bot.data.data_policy import ExposurePolicy, Sensitive, StoragePolicy
from job_bot.db.greenhouse_models import GreenhouseBoard
from job_bot.db.job_models import Job

# Profile fields must be available to the application-filling LLM, but should
# not be emitted verbatim in operational logs.  More sensitive profile details
# (address, demographics, and document content) are redacted from logs.
_CONTACT_DATA = Sensitive(
    storage=StoragePolicy.ENCRYPT,
    logging=ExposurePolicy.MASK,
    llm=ExposurePolicy.PLAIN,
)
_PRIVATE_PROFILE_DATA = Sensitive(
    storage=StoragePolicy.ENCRYPT,
    llm=ExposurePolicy.PLAIN,
)
_PRIVATE_DOCUMENT_DATA = Sensitive(storage=StoragePolicy.ENCRYPT)
_FORM_VALUE_DATA = Sensitive(storage=StoragePolicy.ENCRYPT)


class JobEntrySchema(BaseModel):
    """Transport-safe representation of a persisted or discovered job."""

    id: UUID | None = None
    source: str | None = None
    job_title: str
    url: str
    company_name: str
    job_location: str
    jd_summary: str
    date_posted: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_orm_model(cls, job: Job) -> JobEntrySchema:
        return cls(
            id=job.job_id,
            source=job.source,
            job_title=job.job_title,
            url=job.url,
            company_name=job.company_name,
            job_location=job.job_location,
            jd_summary=job.jd_summary,
            date_posted=job.date_posted,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )

    def to_orm_model(self) -> Job:
        values = dict(
            source=self.source,
            job_title=self.job_title,
            url=self.url,
            company_name=self.company_name,
            job_location=self.job_location,
            jd_summary=self.jd_summary,
            date_posted=self.date_posted,
        )
        if self.id is not None:
            values["job_id"] = self.id
        return Job(**values)


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


JobBoardProvider = Literal["greenhouse", "lever", "ashby", "workday"]


class JobBoardSchema(BaseModel):
    """Provider-neutral representation of a persisted job board."""

    provider: JobBoardProvider
    company: str | None
    board_token: str
    api_base: str

    @classmethod
    def from_greenhouse(cls, board: GreenhouseBoard) -> JobBoardSchema:
        return cls(
            provider="greenhouse",
            company=board.company_name,
            board_token=board.token,
            api_base=board.api_url,
        )


class ApplicationStatus(BaseModel):
    job: JobEntrySchema
    status: Literal["applied", "failed"]
    message: str | None = None


class EducationDegree(BaseModel):
    degree: Annotated[str, _PRIVATE_PROFILE_DATA]
    field_of_study: Annotated[str, _PRIVATE_PROFILE_DATA]
    institution: Annotated[str, _PRIVATE_PROFILE_DATA]
    duration_minimum: Annotated[int, _PRIVATE_PROFILE_DATA]
    duration_maximum: Annotated[int, _PRIVATE_PROFILE_DATA]
    gpa: Annotated[float, _PRIVATE_PROFILE_DATA]


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
    "application-irrelevant",
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

    first_name: Annotated[str, _CONTACT_DATA]
    last_name: Annotated[str, _CONTACT_DATA]
    email: Annotated[EmailStr, _CONTACT_DATA]
    phone_country: Annotated[str, _CONTACT_DATA] = Field(min_length=1, max_length=255)
    phone: Annotated[str, _CONTACT_DATA]
    address_line_1: Annotated[str | None, _PRIVATE_PROFILE_DATA] = None
    address_line_2: Annotated[str | None, _PRIVATE_PROFILE_DATA] = None
    city: Annotated[str | None, _PRIVATE_PROFILE_DATA] = None
    state: Annotated[str | None, _PRIVATE_PROFILE_DATA] = None
    postal_code: Annotated[str | None, _PRIVATE_PROFILE_DATA] = None
    country: Annotated[str | None, _PRIVATE_PROFILE_DATA] = Field(default=None, max_length=255)

    linkedin_url: Annotated[str | None, _PRIVATE_PROFILE_DATA] = None
    github_url: Annotated[str | None, _PRIVATE_PROFILE_DATA] = None
    portfolio_url: Annotated[str | None, _PRIVATE_PROFILE_DATA] = None
    website_url: Annotated[str | None, _PRIVATE_PROFILE_DATA] = None

    @field_validator("email", mode="after")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        """Store a canonical, case-insensitive email identity."""
        return str(value).casefold()

    @field_validator("phone_country", mode="before")
    @classmethod
    def normalize_phone_country(cls, value: str) -> str:
        """Store phone-country inputs as canonical full country names."""
        canonical = regulate_phone_country_code(value)
        if canonical.startswith("raw:"):
            raise ValueError("phone_country must identify a country")
        return canonical

    @field_validator("country", mode="before")
    @classmethod
    def normalize_country(cls, value: str | None) -> str | None:
        """Store address-country inputs as canonical full country names."""
        if value is None:
            return None
        canonical = regulate_country(value)
        if canonical.startswith("raw:"):
            raise ValueError("country must identify a country")
        return canonical

    authorized_to_work: Annotated[YesNoOption, _PRIVATE_PROFILE_DATA] = "yes"
    requires_sponsorship: Annotated[YesNoOption, _PRIVATE_PROFILE_DATA] = "yes"
    visa_status: Annotated[str | None, _PRIVATE_PROFILE_DATA] = None

    willing_to_relocate: Annotated[YesNoOption, _PRIVATE_PROFILE_DATA] = "yes"
    gender: Annotated[GenderOption | None, _PRIVATE_PROFILE_DATA] = None
    is_hispanic_or_latino: Annotated[YesNoOption, _PRIVATE_PROFILE_DATA] = "no"
    race: Annotated[RaceEthnicityOption, _PRIVATE_PROFILE_DATA] = "asian"
    disability_status: Annotated[DisabilityStatusOption, _PRIVATE_PROFILE_DATA] = "no"
    veteran_status: Annotated[VeteranStatusOption, _PRIVATE_PROFILE_DATA] = "no"

    education: Annotated[list[EducationDegree], _PRIVATE_PROFILE_DATA]
    resume_text: Annotated[str, _PRIVATE_DOCUMENT_DATA]
    summary: Annotated[str, _PRIVATE_PROFILE_DATA]

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
            f"Phone Country: {self.phone_country}\n"
            f"Phone: {self.phone}\n"
            f"LinkedIn: {self.linkedin_url}\n"
            f"GitHub: {self.github_url}\n"
            f"Portfolio: {self.portfolio_url}\n"
            f"Requires Sponsorship: {self.requires_sponsorship.title()}\n"
            f"Education:\n{education_str}\n"
            f"Summary:\n{self.summary}"
        )


class UserResponse(BaseModel):
    user_id: UUID
    user: User
    resume_filename: str
    created_at: datetime
    updated_at: datetime


InteractionStrategy = Literal[
    "fill",
    "select_native",
    "select_combobox",
    "select_radio",
    "toggle_checkbox",
    "upload_file",
    "click",
    "fill_contenteditable",
    "pick_date",
    "unsupported",
]

ControlKind = Literal[
    "input",
    "textarea",
    "select",
    "button",
    "contenteditable",
    "unknown",
]


class FormOption(BaseModel):
    label: str
    value: str | None = None
    selected: bool = False
    disabled: bool = False


class InspectedFile(BaseModel):
    """Content and metadata read from a browser file input."""

    filename: Annotated[str, _PRIVATE_DOCUMENT_DATA]
    content: Annotated[bytes, _PRIVATE_DOCUMENT_DATA] = Field(repr=False)
    mime_type: str
    size: int = Field(ge=0)


class FormField(BaseModel):
    # 内部稳定标识，不一定等于 DOM id
    field_key: JobFormFieldKey | None = None

    interaction_strategy: InteractionStrategy = "unsupported"

    control_kind: ControlKind = "unknown"

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
    current_value: Annotated[str | bool | list[str] | None, _FORM_VALUE_DATA] = None
    uploaded_file: InspectedFile | None = None
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


class UploadableFile(BaseModel):
    """A user-provided file that can be uploaded without writing it to disk."""

    model_config = ConfigDict(frozen=True)

    filename: Annotated[str, _PRIVATE_DOCUMENT_DATA] = Field(min_length=1)
    content: Annotated[bytes, _PRIVATE_DOCUMENT_DATA] = Field(min_length=1, repr=False)
    mime_type: str = Field(default="application/octet-stream", min_length=1)


class ApplicationFileSet(BaseModel):
    resume: UploadableFile | None = None
    cover_letter: UploadableFile | None = None


class PageInspection(BaseModel):
    form_fields: list[FormField] = Field(default_factory=list)


class FormSuggestion(BaseModel):
    field_key: JobFormFieldKey
    value: Annotated[str | bool | None, _FORM_VALUE_DATA] = None


class InferredFormAnswers(BaseModel):
    answers: list[FormSuggestion] = Field(default_factory=list)


class FormAnswer(BaseModel):
    """
    A Pydantic model that holds the inferred answer for a form field.
    """

    field_accessible_name: str = Field(..., description="The name of the form field.")
    answer: Annotated[str, _FORM_VALUE_DATA] = Field(
        ..., description="The inferred answer for the form field."
    )


class AgentInferredFormAnswer(BaseModel):
    """
    A Pydantic model that holds the inferred answer for a form field.
    """

    answers: list[FormAnswer] = Field(..., description="The inferred answers for the form fields.")
