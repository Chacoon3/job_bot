import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from job_bot.applier.greenhouse_applier import GreenHouseFiller
from job_bot.schemas import FormField


def test_greenhouse_filler_uses_the_active_page(monkeypatch) -> None:
    locator = Mock()
    page = Mock()
    browser_session = Mock()
    browser_session.page.return_value = page
    field = FormField(
        tag="input",
        interaction_kind="text",
        input_type="text",
        accessible_name="First Name",
        required=True,
        editable=True,
    )
    locate = Mock(return_value=locator)
    fill_text = AsyncMock()
    visible_assertion = SimpleNamespace(to_be_visible=AsyncMock())
    monkeypatch.setattr("job_bot.applier.greenhouse_applier.locate_by_accessible_name", locate)
    monkeypatch.setattr("job_bot.applier.greenhouse_applier.fill_text_field", fill_text)
    monkeypatch.setattr(
        "job_bot.applier.greenhouse_applier.expect",
        Mock(return_value=visible_assertion),
    )

    filler = GreenHouseFiller(Mock(), Mock(), "https://example.com/apply")
    filler.browser_session = browser_session

    asyncio.run(filler.fill(field, "Zizheng"))

    browser_session.page.assert_called_once_with()
    locate.assert_called_once_with(page, "First Name", None)
    visible_assertion.to_be_visible.assert_awaited_once_with(timeout=5000)
    fill_text.assert_awaited_once_with(locator, "Zizheng")
