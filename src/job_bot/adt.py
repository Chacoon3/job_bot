from __future__ import annotations

from enum import Enum, unique
from typing import Annotated, Optional

from langchain.messages import AnyMessage
from langgraph.graph import add_messages
from pydantic import BaseModel

from job_bot.utils.browser_tools import BrowserSession


@unique
class JobPageType(Enum, str):
    """Classify the current page type for job application workflow guidance."""

    JOB_DESCRIPTION = "job_description"
    ACCOUNT_LOGIN = "account_login"
    APPLICATION_FORM = "application_form"
    UNKNOWN = "unknown"

    def to_application_stage(self) -> ApplicationStage:
        return {
            JobPageType.JOB_DESCRIPTION: ApplicationStage.PRE_APPLICATION,
            JobPageType.ACCOUNT_LOGIN: ApplicationStage.LOGIN_PAGE,
            JobPageType.APPLICATION_FORM: ApplicationStage.FORM_FILLING,
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
    def next(self) -> frozenset["ApplicationStage"]:
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
                }
            ),
            ApplicationStage.SUBMITTED: frozenset(),
        }[self]

    def can_transition_to(self, target: "ApplicationStage") -> bool:
        return target in self.next


class JobAgentState(BaseModel):
    """State of the application agent, including the current page type and application stage."""

    messages: Annotated[list[AnyMessage], add_messages]
    application_stage: ApplicationStage
    job_page_type: JobPageType


class JobAgentContext(BaseModel):
    browser_session: Optional[BrowserSession] = None
    browser_tools: Optional[list] = None
