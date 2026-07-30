from typing import Protocol

from playwright.async_api import expect
from structlog import get_logger

from job_bot.agent.filler_tools import (
    extract_dropdown_options,
    fill_text_field,
    locate_by_accessible_name,
    select_dropdown_option,
)
from job_bot.schemas import CandidateProfile, FormField, InteractionKind
from job_bot.utils.browser_tools import BrowserSession


class Filler(Protocol):
    async def fill(self, field: FormField, value: str) -> None: ...


class GreenHouseFiller:
    def __init__(self, browser_session: BrowserSession, candidate_profile: CandidateProfile):
        self.browser_session = browser_session
        self.candidate_profile = candidate_profile

    async def fill_text_field(self, field: FormField, value: str) -> None:
        locator = locate_by_accessible_name(
            self.browser_session.page(),
            field.accessible_name,
            field.role,
        )
        await expect(locator).to_be_visible(timeout=5000)
        await fill_text_field(locator, value)

    async def fill(self, field: FormField, value: str) -> None:
        field_interact_type: InteractionKind = field.interaction_kind
        match field_interact_type:
            case "text":
                await self.fill_text_field(field, value)
            case "select":
                dropdown_locator = locate_by_accessible_name(
                    self.browser_session.page(),
                    field.accessible_name,
                    field.role,
                )
                dropdown_snapshot = await extract_dropdown_options(
                    self.browser_session.page(),
                    dropdown_locator,
                )

                get_logger().info(
                    "dropdown options",
                    dropdown_name=field.accessible_name,
                    options=dropdown_snapshot.options[:5],
                )

                dropdown_answer = self.candidate_profile.get_answer(field.field_key)
                if dropdown_answer is None:
                    raise ValueError(f"No answer found for field key: {field.field_key}")
                await select_dropdown_option(
                    self.browser_session.page(),
                    dropdown_locator,
                    dropdown_answer,
                    regulator=None,
                )
            case _:
                raise ValueError(f"Unsupported interaction kind: {field.interaction_kind}")
