from __future__ import annotations

from enum import Enum, unique
from typing import Annotated

from langchain.messages import AIMessage, AnyMessage
from langchain.tools import BaseTool
from langchain_core.language_models.base import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable
from langgraph.graph import add_messages
from pydantic import BaseModel, ConfigDict, Field

from job_bot.utils.browser_tools import BrowserSession


@unique
class JobPageType(str, Enum):
    """Classify the current page type for job application workflow guidance."""

    JOB_DESCRIPTION = "job_description"
    ACCOUNT_LOGIN = "account_login"
    APPLICATION_FORM = "application_form"
    SUBMISSION_CONFIRMATION = "submission_confirmation"
    APPLICATION_ERROR = "application_error"
    UNKNOWN = "unknown"

    def to_application_stage(self) -> ApplicationStage:
        return {
            JobPageType.JOB_DESCRIPTION: ApplicationStage.PRE_APPLICATION,
            JobPageType.ACCOUNT_LOGIN: ApplicationStage.LOGIN_PAGE,
            JobPageType.APPLICATION_FORM: ApplicationStage.FORM_FILLING,
            JobPageType.SUBMISSION_CONFIRMATION: ApplicationStage.SUBMITTED,
            JobPageType.APPLICATION_ERROR: ApplicationStage.SUBMISSION_ERROR,
            JobPageType.UNKNOWN: ApplicationStage.PRE_APPLICATION,
        }[self]


@unique
class ApplicationStage(str, Enum):
    """Classify the current stage of a job application workflow."""

    PRE_APPLICATION = "pre_application"
    LOGIN_PAGE = "login_page"
    FORM_FILLING = "form_filling"
    SUBMISSION_ERROR = "submission_error"
    SUBMITTED = "submitted"

    @property
    def next(self) -> frozenset[ApplicationStage]:
        return {
            ApplicationStage.PRE_APPLICATION: frozenset(
                {
                    ApplicationStage.LOGIN_PAGE,
                    ApplicationStage.FORM_FILLING,
                }
            ),
            ApplicationStage.LOGIN_PAGE: frozenset(
                {
                    ApplicationStage.FORM_FILLING,
                }
            ),
            ApplicationStage.FORM_FILLING: frozenset(
                {
                    ApplicationStage.SUBMITTED,
                    ApplicationStage.SUBMISSION_ERROR,
                }
            ),
            ApplicationStage.SUBMISSION_ERROR: frozenset(
                {
                    ApplicationStage.FORM_FILLING,
                    ApplicationStage.SUBMITTED,
                }
            ),
            ApplicationStage.SUBMITTED: frozenset(),
        }[self]

    def can_transition_to(self, target: ApplicationStage) -> bool:
        return target in self.next


class JobAgentState(BaseModel):
    """State of the application agent, including the current page type and application stage."""

    job_url: str
    messages: Annotated[list[AnyMessage], add_messages] = Field(default_factory=list)
    application_stage: ApplicationStage = ApplicationStage.PRE_APPLICATION
    job_page_type: JobPageType = JobPageType.UNKNOWN


class JobAgentContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    browser_session: BrowserSession | None = None
    browser_tools: list[BaseTool] | None = None
    model: Runnable[LanguageModelInput, AIMessage] | None = None

    resume: bytes
    resume_text: str
