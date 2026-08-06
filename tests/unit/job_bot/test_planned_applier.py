import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from job_bot.agent.mixed_job_agent import (
    FormField,
    PageInspection,
    _load_page_inspections,
    _save_page_inspections,
    agent_flow,
    inspect_page,
)
from job_bot.utils.caching import AppRedisCache as AppCache
from job_bot.utils.hash_helper import schema_string_key


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


def test_load_page_inspections_reads_versioned_database_records() -> None:
    inspection = PageInspection(form_fields=[_form_field()])
    session = Mock()
    session.scalars.return_value.all.return_value = [
        SimpleNamespace(inspection=inspection.model_dump(mode="json"))
    ]
    url = "https://example.com/apply?test=redis-cache"
    version = "test-version"

    result = _load_page_inspections(session, url, version)

    assert result == [inspection]
    session.scalars.assert_called_once()


def test_save_page_inspections_invalidates_cached_query(monkeypatch) -> None:
    session = Mock()
    session.scalar.return_value = SimpleNamespace(job_id=123)
    delete = Mock()
    monkeypatch.setattr(AppCache, "delete", delete)

    _save_page_inspections(
        session,
        "https://example.com/apply?test=invalidate",
        "test-version",
        [PageInspection(form_fields=[_form_field()])],
    )

    session.commit.assert_called_once_with()
    delete.assert_called_once()


def test_inspect_page_generates_and_saves_versioned_inspection(monkeypatch) -> None:
    field = _form_field()
    session = Mock()
    saved: dict[str, object] = {}
    client = Mock()
    client.responses.parse = AsyncMock(
        return_value=SimpleNamespace(output_parsed=PageInspection(form_fields=[field]))
    )
    monkeypatch.setattr(
        "job_bot.agent.planned_applier.get_async_openai_client",
        lambda: client,
    )
    monkeypatch.setenv("JOB_BOT_LLM_MODEL", "test-model")
    monkeypatch.setattr("job_bot.agent.planned_applier._load_page_inspections", lambda *_: [])
    monkeypatch.setattr(
        "job_bot.agent.planned_applier._save_page_inspections",
        lambda received_session, url, version, inspections: saved.update(
            session=received_session,
            url=url,
            version=version,
            inspections=inspections,
        ),
    )
    url = "https://example.com/apply?test=extract"

    inspections = asyncio.run(inspect_page(url, session))

    assert inspections == [PageInspection(form_fields=[field])]
    assert saved == {
        "session": session,
        "url": url,
        "version": schema_string_key(url + "test-model", PageInspection),
        "inspections": inspections,
    }
    client.responses.parse.assert_called_once()
    request = client.responses.parse.call_args.kwargs
    assert request["model"] == "test-model"
    assert request["tools"] == [{"type": "web_search"}]
    assert request["text_format"] is PageInspection
    assert url in request["input"][1]["content"]


def test_inspect_page_returns_matching_database_inspections(monkeypatch) -> None:
    url = "https://example.com/apply?test=cached"
    session = Mock()
    cached = [PageInspection(form_fields=[_form_field()])]
    load = Mock(return_value=cached)
    save = Mock()
    client_factory = Mock()
    monkeypatch.setenv("JOB_BOT_LLM_MODEL", "test-model")
    monkeypatch.setattr("job_bot.agent.planned_applier._load_page_inspections", load)
    monkeypatch.setattr("job_bot.agent.planned_applier._save_page_inspections", save)
    monkeypatch.setattr("job_bot.agent.planned_applier.get_async_openai_client", client_factory)

    result = asyncio.run(inspect_page(url, session))

    assert result == cached
    load.assert_called_once_with(
        session, url, schema_string_key(url + "test-model", PageInspection)
    )
    save.assert_not_called()
    client_factory.assert_not_called()


def test_inspect_page_rejects_unparsed_response(monkeypatch) -> None:
    session = Mock()
    client = Mock()
    client.responses.parse = AsyncMock(return_value=SimpleNamespace(output_parsed=None))
    monkeypatch.setattr(
        "job_bot.agent.planned_applier.get_async_openai_client",
        lambda: client,
    )
    monkeypatch.setenv("JOB_BOT_LLM_MODEL", "test-model")
    monkeypatch.setattr("job_bot.agent.planned_applier._load_page_inspections", lambda *_: [])

    with pytest.raises(RuntimeError, match="Unexpected page inspection response type"):
        asyncio.run(inspect_page("https://example.com/apply?test=unparsed", session))


def test_agent_flow_keeps_page_after_navigation(monkeypatch) -> None:
    field = _form_field()
    navigation_response = object()
    page = SimpleNamespace(goto=AsyncMock(return_value=navigation_response))
    filler = SimpleNamespace(apply=AsyncMock())
    user = SimpleNamespace()
    file_set = SimpleNamespace()
    session = Mock()
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

    inspection = PageInspection(form_fields=[field])
    inspect = AsyncMock(return_value=inspection)
    filler_factory = Mock(return_value=filler)
    monkeypatch.setattr("job_bot.agent.planned_applier.BrowserSession", FakeBrowserSession)
    monkeypatch.setattr("job_bot.agent.planned_applier.inspect_active_page", inspect)
    monkeypatch.setattr("job_bot.agent.planned_applier.GreenHouseFiller", filler_factory)
    monkeypatch.setattr("job_bot.agent.planned_applier.asyncio.sleep", AsyncMock())

    playwright = SimpleNamespace()
    asyncio.run(agent_flow("https://example.com/apply", playwright, user, file_set, session))

    page.goto.assert_awaited_once_with(
        "https://example.com/apply",
        wait_until="domcontentloaded",
    )
    inspect.assert_awaited_once_with(page)
    filler_factory.assert_called_once_with(browser_sessions[0], user, [inspection], file_set)
    filler.apply.assert_awaited_once_with()
