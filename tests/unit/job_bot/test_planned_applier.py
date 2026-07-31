import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from job_bot.agent.planned_applier import (
    FormField,
    _PageInspection,
    agent_flow,
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
    client.responses.parse = AsyncMock(
        return_value=SimpleNamespace(output_parsed=_PageInspection(form_fields=[field]))
    )
    monkeypatch.setattr(
        "job_bot.agent.planned_applier.get_async_openai_client",
        lambda: client,
    )
    monkeypatch.setenv("JOB_BOT_LLM_MODEL", "test-model")
    url = "https://example.com/apply?test=extract"

    fields = asyncio.run(inspect_page.__wrapped__(url))

    assert fields == [field]
    client.responses.parse.assert_called_once()
    request = client.responses.parse.call_args.kwargs
    assert request["model"] == "test-model"
    assert request["tools"] == [{"type": "web_search"}]
    assert request["text_format"] is _PageInspection
    assert url in request["input"][1]["content"]


def test_inspect_page_rejects_unparsed_response(monkeypatch) -> None:
    client = Mock()
    client.responses.parse = AsyncMock(return_value=SimpleNamespace(output_parsed=None))
    monkeypatch.setattr(
        "job_bot.agent.planned_applier.get_async_openai_client",
        lambda: client,
    )
    monkeypatch.setenv("JOB_BOT_LLM_MODEL", "test-model")

    with pytest.raises(RuntimeError, match="Unexpected page inspection response type"):
        asyncio.run(inspect_page.__wrapped__("https://example.com/apply?test=unparsed"))


def test_agent_flow_keeps_page_after_navigation(monkeypatch) -> None:
    field = _form_field()
    navigation_response = object()
    page = SimpleNamespace(goto=AsyncMock(return_value=navigation_response))
    filler = SimpleNamespace(fill_fields=AsyncMock())
    user = SimpleNamespace()
    browser_sessions = []

    class FakeBrowserSession:
        def __init__(self, playwright: object, headless: bool) -> None:
            self.playwright = playwright
            self.headless = headless
            browser_sessions.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        def page(self):
            return page

    inspect = AsyncMock(return_value=[field])
    filler_factory = Mock(return_value=filler)
    monkeypatch.setattr("job_bot.agent.planned_applier.BrowserSession", FakeBrowserSession)
    monkeypatch.setattr("job_bot.agent.planned_applier.inspect_page", inspect)
    monkeypatch.setattr("job_bot.agent.planned_applier.GreenHouseFiller", filler_factory)
    monkeypatch.setattr("job_bot.agent.planned_applier.asyncio.sleep", AsyncMock())

    playwright = SimpleNamespace()
    asyncio.run(agent_flow("https://example.com/apply", playwright, user))

    page.goto.assert_awaited_once_with(
        "https://example.com/apply",
        wait_until="domcontentloaded",
    )
    filler_factory.assert_called_once_with(browser_sessions[0], user)
    filler.fill_fields.assert_awaited_once_with([field])
