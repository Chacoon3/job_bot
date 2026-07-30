from typing import Protocol

from playwright.async_api import Page

from job_bot.schemas import FormField
from job_bot.utils.browser_tools import BrowserSession, Locator


def locate_by_accessible_name(
    page: Page,
    accessible_name: str,
    role: str | None = None,
) -> Locator:
    if role:
        return page.get_by_role(
            role,
            name=accessible_name,
            exact=True,
        )

    return page.get_by_label(
        accessible_name,
        exact=True,
    )


async def fill_text_field(locator: Locator, value: str) -> None:
    if await locator.count() != 1:
        raise LookupError(f"Expected exactly one text field, found {await locator.count()}")

    if not await locator.is_visible():
        raise ValueError("Text field is not visible")

    if not await locator.is_enabled():
        raise ValueError("Text field is disabled")

    if not await locator.is_editable():
        raise ValueError("Text field is not editable")

    await locator.fill(value)


class Filler(Protocol):
    async def fill(self, field: FormField, value: str) -> None: ...


class GreenHouseFiller:
    def __init__(self, browser_session: BrowserSession):
        self.browser_session = browser_session

    async def fill_text_field(self, field: FormField, value: str) -> None:
        locator = locate_by_accessible_name(
            self.browser_session.page,
            field.accessible_name,
            field.role,
        )
        await fill_text_field(locator, value)

    async def fill(self, field: FormField, value: str) -> None:
        match field.input_type:
            case "text":
                await self.fill_text_field(field, value)
            case "email":
                await self.fill_text_field(field, value)
            case "tel":
                await self.fill_text_field(field, value)
            case "url":
                await self.fill_text_field(field, value)
            case "number":
                await self.fill_text_field(field, value)
            case _:
                raise ValueError(f"Unsupported input type: {field.input_type}")
