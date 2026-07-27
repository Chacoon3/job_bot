from __future__ import annotations

import json

from langchain.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain.tools import BaseTool
from langgraph.runtime import Runtime
from pydantic import BaseModel

from job_bot.adt import JobAgentContext, JobAgentState, JobPageType


class PageTypeClassification(BaseModel):
    page_type: JobPageType


def should_invoke_tool(state: JobAgentState) -> bool:
    """Route an AI tool request to the tool node; otherwise finish."""

    if not state.messages:
        return False
    last_message = state.messages[-1]
    return isinstance(last_message, AIMessage) and bool(last_message.tool_calls)


def _browser_tool(context: JobAgentContext, name: str) -> BaseTool:
    if not context.browser_tools:
        raise RuntimeError("Browser tools are not initialized in the runtime context.")
    tool = next((item for item in context.browser_tools if item.name == name), None)
    if tool is None:
        raise RuntimeError(f"Required browser tool is not available: {name}")
    return tool


async def tool_call_node(
    state: JobAgentState,
    runtime: Runtime[JobAgentContext],
) -> dict[str, object]:
    """Execute the model's requested browser tools asynchronously."""

    if not state.messages or not isinstance(state.messages[-1], AIMessage):
        raise RuntimeError("Tool node requires a final AI message.")

    registry = {tool.name: tool for tool in runtime.context.browser_tools or []}
    tool_messages: list[ToolMessage] = []
    for tool_call in state.messages[-1].tool_calls:
        tool = registry.get(tool_call["name"])
        if tool is None:
            raise ValueError(f"Tool call '{tool_call['name']}' is not supported")
        observation = await tool.ainvoke(tool_call["args"])
        content = observation if isinstance(observation, str) else json.dumps(observation)
        tool_messages.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
    return {"messages": tool_messages}


async def open_job_page(
    state: JobAgentState,
    runtime: Runtime[JobAgentContext],
) -> dict[str, object]:
    """Start the browser session and navigate to the requested job URL."""

    session = runtime.context.browser_session
    if session is None:
        raise RuntimeError("Browser session is not initialized in the runtime context.")
    if not state.job_url:
        raise RuntimeError("No job URL was supplied.")

    await session.start()
    response = await session.page().goto(state.job_url, wait_until="domcontentloaded")
    status = response.status if response is not None else "unknown"
    return {
        "messages": [AIMessage(content=f"Navigated to {state.job_url}; HTTP status: {status}.")]
    }


async def infer_page_type(
    state: JobAgentState,
    runtime: Runtime[JobAgentContext],
) -> dict[str, object]:
    """Inspect the live page and classify it from the resulting snapshot."""

    model = runtime.context.model
    if model is None:
        raise RuntimeError("Model is not initialized in the runtime context.")

    inspection = await _browser_tool(
        runtime.context,
        "browser_inspect_page",
    ).ainvoke({"frame_index": 0})
    structured = model.with_structured_output(PageTypeClassification)
    classification = await structured.ainvoke(
        [
            SystemMessage(
                content=(
                    "Classify the inspected job-application page. Use "
                    "submission_confirmation only for clear evidence that the application was "
                    "submitted, and application_error for a failed submission or blocking "
                    "validation state. Otherwise prefer application_form over account_login, "
                    "account_login over job_description, and use unknown when unsupported."
                )
            ),
            HumanMessage(content=f"Current browser snapshot:\n{inspection}"),
        ]
    )
    if not isinstance(classification, PageTypeClassification):
        raise TypeError(f"Unexpected page type response: {type(classification).__name__}")
    page_type = classification.page_type
    return {
        "job_page_type": page_type,
        "messages": [
            HumanMessage(content=f"Browser snapshot:\n{inspection}"),
            AIMessage(content=f"Page type: {page_type.value}"),
        ],
    }


async def infer_application_stage(
    state: JobAgentState,
    _runtime: Runtime[JobAgentContext],
) -> dict[str, object]:
    """Validate and apply the state transition implied by the current page."""

    page_type = state.job_page_type
    if page_type is JobPageType.UNKNOWN:
        return {}

    expected_stage = page_type.to_application_stage()
    if state.application_stage == expected_stage:
        return {}
    if not state.application_stage.can_transition_to(expected_stage):
        raise RuntimeError(
            f"Invalid transition from {state.application_stage} to {expected_stage} "
            f"based on page type {page_type}."
        )
    return {"application_stage": expected_stage}


async def complete_page(
    state: JobAgentState,
    runtime: Runtime[JobAgentContext],
) -> dict[str, object]:
    """Ask the tool-bound model for the next safe action on the current page."""

    model = runtime.context.model
    tools = runtime.context.browser_tools
    if model is None:
        raise RuntimeError("Model is not initialized in the runtime context.")
    if not tools:
        raise RuntimeError("Browser tools are not initialized in the runtime context.")

    page_prompt_map = {
        JobPageType.JOB_DESCRIPTION: (
            "Inspect the job page snapshot, find the Apply control for this job, and take "
            "one browser action. Ignore job alerts, newsletters, and unrelated sign-ups."
        ),
        JobPageType.ACCOUNT_LOGIN: (
            "Use only credentials explicitly supplied in the context. If none are available, "
            "or CAPTCHA or MFA blocks progress, stop and clearly report the blocker."
        ),
        JobPageType.APPLICATION_FORM: (
            "Complete one safe logical application step using only supplied candidate data. "
            "Never invent information or opt into marketing. Inspect again after the action. "
            "Review before submitting and stop only after a clear confirmation."
        ),
        JobPageType.SUBMISSION_CONFIRMATION: (
            "The application is confirmed submitted. Make no tool call and briefly report "
            "the successful submission."
        ),
        JobPageType.APPLICATION_ERROR: (
            "Inspect the reported submission or validation error. Correct it only when the "
            "required value is explicitly supplied; otherwise make no tool call and report it."
        ),
        JobPageType.UNKNOWN: (
            "Use the page snapshot to identify a safe next action. If the page is a "
            "confirmation, expired posting, access error, or human-verification challenge, "
            "make no tool call and report the outcome."
        ),
    }
    bound_model = model.bind_tools(tools, parallel_tool_calls=False)
    response = await bound_model.ainvoke(
        [
            SystemMessage(
                content=(
                    "You are a careful job-application browser agent. Make at most one tool "
                    "call per response. Use only selectors returned by browser inspection."
                )
            ),
            *state.messages,
            HumanMessage(content=page_prompt_map[state.job_page_type]),
        ]
    )
    return {"messages": [response]}
