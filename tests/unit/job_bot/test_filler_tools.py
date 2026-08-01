import asyncio
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from job_bot.agent.filler_tools import (
    _dropdown_option_cache_key,
    _infer_field_key,
    fill_text_field,
    select_dropdown_option,
)
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


def test_infer_field_key_treats_phone_sms_prompt_as_communications_consent() -> None:
    field_key = _infer_field_key(
        {
            "accessible_name": (
                "By selecting YES, I consent to receive recruiting SMS messages from "
                "PerfectServe at the phone number provided on my job application."
            ),
            "input_name": "question_123",
            "element_id": "question_123",
            "input_type": "text",
            "interaction_strategy": "select_combobox",
        }
    )

    assert field_key == "communications_consent"


def test_infer_field_key_does_not_treat_ethnicity_as_city() -> None:
    field_key = _infer_field_key(
        {
            "accessible_name": "Are you Hispanic/Latino?",
            "input_name": "job_application[ethnicity]",
            "element_id": "job_application_ethnicity",
            "input_type": "text",
            "interaction_strategy": "select_combobox",
        }
    )

    assert field_key == "is_hispanic_or_latino"


def test_infer_field_key_recognizes_city_identifier_boundaries() -> None:
    assert _infer_field_key({"input_name": "job_application[location_city]"}) == "city"


def test_dropdown_option_cache_key_uses_bound_arguments() -> None:
    def infer(page, locator, expected_value):
        raise AssertionError("The cache key builder must not call the function")

    page = SimpleNamespace(url="https://boards.example/jobs/123")

    positional_key = _dropdown_option_cache_key(
        infer,
        (page, "get_by_label('Location')", "New York"),
        {},
    )
    keyword_key = _dropdown_option_cache_key(
        infer,
        (),
        {
            "page": page,
            "locator": "get_by_label('Location')",
            "expected_value": "New York",
        },
    )
    different_value_key = _dropdown_option_cache_key(
        infer,
        (page, "get_by_label('Location')", "Boston"),
        {},
    )

    assert positional_key == keyword_key
    assert positional_key != different_value_key


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
