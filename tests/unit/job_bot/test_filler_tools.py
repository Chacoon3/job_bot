import asyncio
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from job_bot.agent.filler_tools import (
    _dropdown_option_cache_key,
    _infer_field_key,
    fill_text_field,
    inspect_page,
    llm_infer_correct_dropdown_option,
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


def test_infer_field_key_only_classifies_resume_file_input_as_attachment() -> None:
    resume_group = "Resume/CV*"

    assert (
        _infer_field_key(
            {
                "accessible_name": "Attach",
                "element_id": "resume",
                "input_type": "file",
                "tag": "input",
                "group_label": resume_group,
            }
        )
        == "attach_resume_button"
    )

    for button_name in ("Attach", "Dropbox", "Google Drive", "Enter manually"):
        assert (
            _infer_field_key(
                {
                    "accessible_name": button_name,
                    "input_type": "button",
                    "tag": "button",
                    "group_label": resume_group,
                }
            )
            == "unknown"
        )


def test_inspect_page_decodes_selected_file_content() -> None:
    page = AsyncMock()
    page.evaluate.return_value = [
        {
            "tag": "input",
            "input_type": "file",
            "interaction_strategy": "upload_file",
            "control_kind": "input",
            "element_id": "resume",
            "accessible_name": "Attach",
            "group_label": "Resume/CV",
            "current_value": r"C:\fakepath\resume.pdf",
            "required": True,
            "uploaded_file": {
                "filename": "resume.pdf",
                "mime_type": "application/pdf",
                "size": 12,
                "content_base64": "cmVzdW1lIGJ5dGVz",
            },
        }
    ]

    inspection = asyncio.run(inspect_page(page))
    field = inspection.form_fields[0]

    assert field.field_key == "attach_resume_button"
    assert field.uploaded_file is not None
    assert field.uploaded_file.filename == "resume.pdf"
    assert field.uploaded_file.content == b"resume bytes"
    assert field.required


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


def test_llm_dropdown_inference_returns_generated_output(monkeypatch) -> None:
    response = SimpleNamespace(
        output_text="  New York, New York, United States  ",
        text=object(),
    )
    client = SimpleNamespace(
        responses=SimpleNamespace(create=AsyncMock(return_value=response)),
    )
    monkeypatch.setattr(
        "job_bot.agent.filler_tools.get_async_openai_client",
        Mock(return_value=client),
    )
    monkeypatch.setattr(
        "job_bot.agent.filler_tools.extract_dropdown_options",
        AsyncMock(return_value=DropdownSnapshot(kind="autocomplete", options=[])),
    )

    infer_without_cache = llm_infer_correct_dropdown_option.__wrapped__
    result = asyncio.run(infer_without_cache(Mock(), Mock(), "New York"))

    assert result == "New York, New York, United States"


def test_llm_dropdown_inference_converts_none_sentinel(monkeypatch) -> None:
    response = SimpleNamespace(output_text="None")
    client = SimpleNamespace(
        responses=SimpleNamespace(create=AsyncMock(return_value=response)),
    )
    monkeypatch.setattr(
        "job_bot.agent.filler_tools.get_async_openai_client",
        Mock(return_value=client),
    )
    monkeypatch.setattr(
        "job_bot.agent.filler_tools.extract_dropdown_options",
        AsyncMock(return_value=DropdownSnapshot(kind="autocomplete", options=[])),
    )

    infer_without_cache = llm_infer_correct_dropdown_option.__wrapped__
    result = asyncio.run(infer_without_cache(Mock(), Mock(), "Unknown"))

    assert result is None


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
