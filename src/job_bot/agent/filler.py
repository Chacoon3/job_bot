from abc import ABC, abstractmethod

from playwright.async_api import expect
from structlog import get_logger

from job_bot.agent.dropdown_regulator import get_dropdown_regulator_by_field_key
from job_bot.agent.filler_tools import (
    fill_text_field,
    locate_by_accessible_name,
    select_dropdown_option,
)
from job_bot.schemas import FormField, User
from job_bot.utils.browser_tools import BrowserSession


class BaseFiller(ABC):
    def __init__(self, browser_session: BrowserSession, user: User):
        self.browser_session = browser_session
        self.user = user

    @abstractmethod
    async def text(self, field: FormField, value: str) -> None: ...

    @abstractmethod
    async def select(self, field: FormField, value: str) -> None: ...

    @abstractmethod
    async def checkbox(self, field: FormField, value: bool) -> None: ...

    @abstractmethod
    async def radio(self, field: FormField, value: str) -> None: ...

    @abstractmethod
    async def textarea(self, field: FormField, value: str) -> None: ...

    @abstractmethod
    async def file_upload(self, field: FormField, value: str) -> None: ...

    async def fill_fields(self, fields: list[FormField]) -> None:
        for field in fields:
            try:
                filler = getattr(self, field.interaction_kind, None)
                if filler is None:
                    raise ValueError(
                        f"No filler found for interaction kind: {field.interaction_kind}"
                    )
                answer = self.user.get_answer(field.field_key)
                if answer is None:
                    raise ValueError(f"No answer found for field key: {field.field_key}")
                await filler(field, answer)
                get_logger().info(
                    "Field filled successfully",
                    field_name=field.accessible_name,
                    field_value=str(answer)[:5],
                )
            except Exception as e:
                get_logger().error(
                    "Error filling field",
                    field_key=field.field_key,
                    error=str(e),
                )


class GreenHouseFiller(BaseFiller):

    async def text(self, field: FormField, value: str) -> None:
        locator = locate_by_accessible_name(
            self.browser_session.page(),
            field.accessible_name,
            field.role,
        )
        await expect(locator).to_be_visible(timeout=5000)
        await fill_text_field(locator, value)

    async def select(self, field: FormField, value: str) -> None:
        dropdown_locator = locate_by_accessible_name(
            self.browser_session.page(),
            field.accessible_name,
            field.role,
        )

        get_logger().info(
            "Filling dropdown field",
            field_name=field.accessible_name,
            field_value=value,
        )

        await select_dropdown_option(
            self.browser_session.page(),
            dropdown_locator,
            value,
            regulator=get_dropdown_regulator_by_field_key(field.field_key),
        )

    async def checkbox(self, field: FormField, value: bool) -> None:
        pass

    async def radio(self, field: FormField, value: str) -> None:
        pass

    async def textarea(self, field: FormField, value: str) -> None:
        pass

    async def file_upload(self, field: FormField, value: str) -> None:
        pass
