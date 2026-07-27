from __future__ import annotations

import asyncio
from types import SimpleNamespace

from langchain.messages import AIMessage
from langgraph.runtime import Runtime

from job_bot.adt import ApplicationStage, JobAgentState, JobPageType
from job_bot.agent.nodes import (
    infer_application_stage,
    open_job_page,
    should_invoke_tool,
    tool_call_node,
)
from job_bot.agent.react_applier import build_agent


class FakePage:
    def __init__(self) -> None:
        self.navigation: tuple[str, str] | None = None

    async def goto(self, url: str, *, wait_until: str) -> object:
        self.navigation = (url, wait_until)
        return SimpleNamespace(status=200)


class FakeSession:
    def __init__(self) -> None:
        self.started = False
        self.current_page = FakePage()

    async def start(self) -> None:
        self.started = True

    def page(self) -> FakePage:
        return self.current_page


class FakeTool:
    name = "browser_click"

    def __init__(self) -> None:
        self.arguments: dict[str, object] | None = None

    async def ainvoke(self, arguments: dict[str, object]) -> dict[str, bool]:
        self.arguments = arguments
        return {"clicked": True}


def test_build_agent_has_no_model_or_credential_side_effect() -> None:
    assert type(build_agent()).__name__ == "CompiledStateGraph"


def test_open_job_page_awaits_session_and_navigates_to_job_url() -> None:
    session = FakeSession()
    state = JobAgentState(job_url="https://example.com/jobs/123")
    runtime = Runtime(context=SimpleNamespace(browser_session=session))

    update = asyncio.run(open_job_page(state, runtime))

    assert session.started is True
    assert session.current_page.navigation == (
        "https://example.com/jobs/123",
        "domcontentloaded",
    )
    assert "HTTP status: 200" in update["messages"][0].content


def test_tool_node_awaits_requested_tool_and_returns_observation() -> None:
    tool = FakeTool()
    message = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "browser_click",
                "args": {"selector": "#apply"},
                "id": "call-1",
                "type": "tool_call",
            }
        ],
    )
    state = JobAgentState(job_url="https://example.com", messages=[message])
    runtime = Runtime(context=SimpleNamespace(browser_tools=[tool]))

    update = asyncio.run(tool_call_node(state, runtime))

    assert tool.arguments == {"selector": "#apply"}
    assert update["messages"][0].tool_call_id == "call-1"
    assert '"clicked": true' in update["messages"][0].content
    assert should_invoke_tool(state) is True


def test_submission_confirmation_transitions_to_submitted() -> None:
    state = JobAgentState(
        job_url="https://example.com",
        application_stage=ApplicationStage.FORM_FILLING,
        job_page_type=JobPageType.SUBMISSION_CONFIRMATION,
    )

    update = asyncio.run(infer_application_stage(state, Runtime(context=SimpleNamespace())))

    assert update == {"application_stage": ApplicationStage.SUBMITTED}
