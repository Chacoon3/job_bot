import asyncio
from unittest.mock import AsyncMock, Mock

from job_bot.agent.filler import GreenHouseFiller
from job_bot.schemas import FormField


def test_greenhouse_filler_uses_the_active_page() -> None:
    locator = Mock()
    locator.count = AsyncMock(return_value=1)
    locator.is_visible = AsyncMock(return_value=True)
    locator.is_enabled = AsyncMock(return_value=True)
    locator.is_editable = AsyncMock(return_value=True)
    locator.fill = AsyncMock()

    page = Mock()
    page.get_by_label.return_value = locator
    browser_session = Mock()
    browser_session.page.return_value = page
    field = FormField(
        tag="input",
        input_type="text",
        accessible_name="First Name",
        required=True,
        editable=True,
    )

    asyncio.run(GreenHouseFiller(browser_session).fill(field, "Zizheng"))

    browser_session.page.assert_called_once_with()
    page.get_by_label.assert_called_once_with("First Name", exact=True)
    locator.fill.assert_awaited_once_with("Zizheng")
