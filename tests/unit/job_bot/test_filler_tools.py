import asyncio
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from job_bot.agent.filler_tools import fill_text_field, select_dropdown_option
from job_bot.schemas import DropdownSnapshot


def test_fill_text_field_accepts_canonical_phone_match() -> None:
    locator = AsyncMock()
    locator.count.return_value = 1
    locator.is_enabled.return_value = True
    locator.is_editable.return_value = True
    locator.input_value.return_value = "(301) 742-4626"

    asyncio.run(
        fill_text_field(
            locator,
            "301-742-4626",
            canonicalizer=lambda value: re.sub(r"\D", "", value),
        )
    )


def test_select_dropdown_option_queries_an_empty_autocomplete(monkeypatch) -> None:
    dropdown = AsyncMock()
    page = Mock()
    listbox = Mock()
    options = Mock()
    option = AsyncMock()
    options.nth.return_value = option
    options.evaluate_all = AsyncMock(
        return_value=[
            {
                "index": 0,
                "label": "New York, New York, United States",
                "value": None,
                "element_id": None,
                "disabled": False,
                "selected": False,
            }
        ]
    )
    listbox.get_by_role.return_value = options
    page.locator.return_value = listbox

    assertion = SimpleNamespace(
        to_be_visible=AsyncMock(),
        to_be_enabled=AsyncMock(),
        to_be_hidden=AsyncMock(),
        to_have_attribute=AsyncMock(),
    )
    monkeypatch.setattr(
        "job_bot.agent.filler_tools.extract_dropdown_options",
        AsyncMock(
            return_value=DropdownSnapshot(
                kind="autocomplete",
                options=[],
                complete=False,
                listbox_id="location-listbox",
            )
        ),
    )
    monkeypatch.setattr("job_bot.agent.filler_tools.expect", Mock(return_value=assertion))

    asyncio.run(
        select_dropdown_option(
            page,
            dropdown,
            "New York",
            query="New York, NY, United States",
        )
    )

    dropdown.press_sequentially.assert_awaited_once()
    assert dropdown.press_sequentially.await_args.args[0] == "New York, NY, United States"
    option.click.assert_awaited_once_with(timeout=5_000)
