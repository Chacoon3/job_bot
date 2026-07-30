import asyncio
from unittest.mock import AsyncMock, Mock

from job_bot.agent.filler import GreenHouseFiller
from job_bot.schemas import FormField


def test_greenhouse_filler_uses_the_active_page(monkeypatch) -> None:
    locator = Mock()
    locator.count = AsyncMock(return_value=1)
    locator.wait_for = AsyncMock()
    locator.is_enabled = AsyncMock(return_value=True)
    locator.is_editable = AsyncMock(return_value=True)
    locator.click = AsyncMock()
    locator.press = AsyncMock()
    locator.press_sequentially = AsyncMock()
    locator.input_value = AsyncMock(return_value="Zizheng")

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
    delays = iter([42, 57, 81, 66, 103, 49, 74])
    monkeypatch.setattr("job_bot.agent.filler.random.randint", lambda _start, _end: next(delays))

    asyncio.run(GreenHouseFiller(browser_session).fill(field, "Zizheng"))

    browser_session.page.assert_called_once_with()
    page.get_by_label.assert_called_once_with("First Name", exact=True)
    locator.wait_for.assert_awaited_once_with(state="visible", timeout=5000)
    locator.click.assert_awaited_once_with()
    assert [call.args[0] for call in locator.press.await_args_list] == [
        "ControlOrMeta+A",
        "Backspace",
        "Tab",
    ]
    assert [
        (call.args[0], call.kwargs["delay"]) for call in locator.press_sequentially.await_args_list
    ] == [
        ("Z", 42),
        ("i", 57),
        ("z", 81),
        ("h", 66),
        ("e", 103),
        ("n", 49),
        ("g", 74),
    ]
    locator.input_value.assert_awaited_once_with()
