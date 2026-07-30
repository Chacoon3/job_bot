from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from job_bot.agent.planned_applier import (
    FormField,
    _AgentContext,
    _AgentState,
    _PageInspection,
    inspect_page,
)


def _form_field() -> FormField:
    return FormField(
        field_id="email",
        tag="input",
        role="textbox",
        input_type="email",
        accessible_name="Email address",
        labels=["Email"],
        current_value=None,
        options=[],
        required=True,
        editable=True,
        visible=True,
        frame_url="https://example.com/apply",
        locator_hint='input[name="email"]',
    )


def test_inspect_page_extracts_form_fields_into_state_update(monkeypatch) -> None:
    field = _form_field()
    client = Mock()
    client.responses.parse.return_value = SimpleNamespace(
        output_parsed=_PageInspection(form_fields=[field])
    )
    monkeypatch.setattr(
        "job_bot.agent.planned_applier.get_openai_client",
        lambda: client,
    )
    monkeypatch.setenv("JOB_BOT_LLM_MODEL", "test-model")
    state = _AgentState(messages=[], job_url="https://example.com/apply")

    update = inspect_page(state, _AgentContext())

    assert update == {"form_fields": [field]}
    client.responses.parse.assert_called_once()
    request = client.responses.parse.call_args.kwargs
    assert request["model"] == "test-model"
    assert request["tools"] == [{"type": "web_search"}]
    assert request["text_format"] is _PageInspection
    assert state.job_url in request["input"][1]["content"]


def test_inspect_page_rejects_unparsed_response(monkeypatch) -> None:
    client = Mock()
    client.responses.parse.return_value = SimpleNamespace(output_parsed=None)
    monkeypatch.setattr(
        "job_bot.agent.planned_applier.get_openai_client",
        lambda: client,
    )
    state = _AgentState(messages=[], job_url="https://example.com/apply")

    with pytest.raises(RuntimeError, match="Unexpected page inspection response type"):
        inspect_page(state, _AgentContext())
