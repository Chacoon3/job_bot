from __future__ import annotations

import asyncio
import random
from enum import StrEnum
from functools import cache
from typing import Annotated

from langchain.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph, add_messages
from langgraph.graph.state import START, CompiledStateGraph
from langgraph.runtime import Runtime
from playwright.async_api import async_playwright
from pydantic import BaseModel
from structlog import get_logger

from job_bot.agent.prompts import JOB_APPSYS_MSG_TEXT
from job_bot.data.adt import JobAgentContext
from job_bot.data.schemas import UploadableFile, User
from job_bot.llm import LLMProvider
from job_bot.utils.browser_tools import BrowserSession, build_browser_tools
from job_bot.utils.decorators import log_upon_exit


class ApplicationStatus(StrEnum):
    """Classify the current status of a job application."""

    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    ERROR = "error"


class ApplicationEvaluation(BaseModel):
    status: ApplicationStatus
    reason: str


MAX_MODEL_ACTIONS = 40
MAX_CONSECUTIVE_FAILURES = 5
GRAPH_RECURSION_LIMIT = 100


class JobAppState(BaseModel):
    messages: Annotated[list[AnyMessage], add_messages]
    job_url: str = None
    action_count: int = 0
    consecutive_failures: int = 0
    evaluation: ApplicationEvaluation | None = None
    profile: User | None = None


@log_upon_exit
async def init(state: JobAppState, runtime: Runtime[JobAgentContext]) -> dict:
    if runtime.context.browser_session is None:
        raise RuntimeError("A started browser session must be provided in the agent context.")

    return JobAppState(
        messages=[
            SystemMessage(content=JOB_APPSYS_MSG_TEXT),
            HumanMessage(
                content=(
                    f"Here is a brief summary of my profile: "
                    f"{state.profile.to_prompt_text()}.\n"
                    f"Complete the job application at the url: {state.job_url}."
                )
            ),
        ],
        job_url=state.job_url,
    )


@log_upon_exit
async def act(state: JobAppState, runtime: Runtime[JobAgentContext]) -> dict:
    resp = await runtime.context.model.ainvoke(state.messages)
    return JobAppState(
        messages=[resp],
        action_count=state.action_count + 1,
        consecutive_failures=state.consecutive_failures,
    )


@log_upon_exit
async def evaluate(
    state: JobAppState,
    runtime: Runtime[JobAgentContext],
) -> dict:
    evaluator = runtime.context.model.with_structured_output(ApplicationEvaluation)
    evaluation_history = [
        message for message in state.messages if not isinstance(message, SystemMessage)
    ]

    result = await evaluator.ainvoke(
        [
            SystemMessage(
                content=(
                    "Evaluate whether the job application has been "
                    "submitted, is still in progress, or has failed."
                )
            ),
            *evaluation_history,
        ]
    )

    return JobAppState(evaluation=result, action_count=state.action_count + 1)


@log_upon_exit
async def use_tool(
    state: JobAppState,
    runtime: Runtime[JobAgentContext],
) -> dict:
    last_message = state.messages[-1]

    if not isinstance(last_message, AIMessage):
        raise RuntimeError("use_tool expects the last message to be an AIMessage.")

    tool_registry = {tool.name: tool for tool in runtime.context.browser_tools}

    tool_messages: list[ToolMessage] = []
    failed_calls = 0

    if len(last_message.tool_calls) > 1:
        get_logger().warning(
            "Multiple tool calls detected in the last message. ", tool_calls=last_message.tool_calls
        )

    for tool_call in last_message.tool_calls:
        await asyncio.sleep(random.random())
        tool = tool_registry.get(tool_call["name"])
        if tool is None:
            result = f"Unsupported tool: {tool_call['name']}"
            failed_calls += 1
            get_logger().error(
                "Unsupported tool requested.",
                tool_name=tool_call["name"],
            )
        else:
            try:
                result = await tool.ainvoke(tool_call["args"])
                get_logger().info(
                    "Tool executed successfully.",
                    tool_name=tool_call["name"],
                )
            except Exception as exc:
                failed_calls += 1
                result = f"Tool execution failed: " f"{type(exc).__name__}: {exc}"
                get_logger().error(
                    "Tool execution failed.",
                    tool_name=tool_call["name"],
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )

        tool_messages.append(
            ToolMessage(
                content=str(result),
                tool_call_id=tool_call["id"],
                name=tool_call["name"],
            )
        )

    return JobAppState(
        messages=tool_messages,
        action_count=state.action_count,
        consecutive_failures=(state.consecutive_failures + failed_calls if failed_calls else 0),
    )


def post_act_router(state: JobAppState) -> str:
    if not state.messages:
        raise RuntimeError("Agent state contains no messages.")

    if state.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
        get_logger().warning(
            "Too many consecutive failures. Ending the application process.",
            consecutive_failures=state.consecutive_failures,
        )
        return END

    if state.action_count >= MAX_MODEL_ACTIONS:
        get_logger().warning(
            "Too many model actions. Ending the application process.",
            action_count=state.action_count,
        )
        return END

    last_message = state.messages[-1]

    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "use_tool"

    return "evaluate"


def post_tool_router(state: JobAppState) -> str:
    if state.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
        get_logger().warning(
            "Too many consecutive tool failures. Ending the application process.",
            consecutive_failures=state.consecutive_failures,
        )
        return END
    if state.action_count >= MAX_MODEL_ACTIONS:
        return END
    return "act"


def post_evaluate_router(state: JobAppState) -> str:
    if state.evaluation is None:
        raise RuntimeError("Application evaluation is missing.")

    if state.evaluation.status is ApplicationStatus.IN_PROGRESS:
        if state.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            return END
        if state.action_count >= MAX_MODEL_ACTIONS:
            return END
        return "act"

    return END


@cache
def build_applier_agent() -> CompiledStateGraph:

    graph = StateGraph(JobAppState, context_schema=JobAgentContext)
    graph.add_node("init", init)
    graph.add_node("act", act)
    graph.add_node("use_tool", use_tool)
    graph.add_node("evaluate", evaluate)

    graph.add_edge(START, "init")
    graph.add_edge("init", "act")
    graph.add_conditional_edges("act", post_act_router)
    graph.add_conditional_edges("use_tool", post_tool_router)
    graph.add_conditional_edges("evaluate", post_evaluate_router)

    return graph.compile()


async def apply_for_job(
    job_url: str,
    profile: User,
    resume: UploadableFile,
    model_provider: LLMProvider,
):
    agent = build_applier_agent()

    async with async_playwright() as playwright:
        async with BrowserSession(playwright=playwright, headless=False) as session:
            session.state["resume"] = resume
            browser_tools = build_browser_tools(session)
            model = model_provider.get_model().bind_tools(browser_tools)
            context = JobAgentContext(
                job_url=job_url, browser_session=session, browser_tools=browser_tools, model=model
            )
            return await agent.ainvoke(
                JobAppState(
                    job_url=job_url,
                    messages=[],
                    profile=profile,
                ),
                config={"recursion_limit": GRAPH_RECURSION_LIMIT},
                context=context,
            )
