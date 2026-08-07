from __future__ import annotations

from functools import cache
from operator import add
from typing import Annotated

from langchain.chat_models import BaseChatModel
from langchain.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langchain_community.tools import BaseTool
from langchain_core.language_models.base import LanguageModelInput
from langchain_core.runnables import Runnable
from langgraph.graph import END, START, StateGraph, add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from pydantic import BaseModel, ConfigDict, Field
from structlog import get_logger

from job_bot.config import settings


class _State(BaseModel):
    """
    A dictionary that holds the state of the application process.
    """

    messages: Annotated[list[AnyMessage], add_messages] = Field(default_factory=list)
    call_count: Annotated[int, add] = 0
    tool_call_count: Annotated[int, add] = 0
    failure_count: Annotated[int, add] = 0
    retry_count: Annotated[int, add] = 0
    structured_output_type: type[BaseModel] | None = None
    structured_output: BaseModel | None = None


class _Runtime(BaseModel):
    """
    A Pydantic model that holds the runtime information of the application process.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    model: BaseChatModel
    model_with_browser_tools: Runnable[LanguageModelInput, AIMessage]
    tool_registry: dict[str, BaseTool] = Field(default_factory=dict)


async def _act(state: _State, runtime: Runtime[_Runtime]) -> _State:
    """
    Performs an action in the application process.

    Args:
        state (_State): The current state of the application process.
        runtime (_Runtime): The runtime information of the application process.

    Returns:
        _State: The updated state of the application process.
    """

    # Here you would implement the logic to perform an action based on the
    # current state and runtime.
    # This could involve interacting with the browser session, sending messages to the model, etc.

    msg = await runtime.context.model_with_browser_tools.ainvoke(state.messages)
    return _State(messages=[msg], call_count=1)


async def _use_tool(
    state: _State,
    runtime: Runtime[_Runtime],
) -> _State:
    last_message = state.messages[-1]

    if last_message.type != "ai":
        raise RuntimeError("use_tool expects the last message to be an AIMessage.")

    tool_messages: list[ToolMessage] = []
    failed_calls = 0

    for tool_call in last_message.tool_calls:
        tool: BaseTool | None = runtime.context.tool_registry.get(tool_call["name"])
        if tool is None:
            result = f"Tool not found: {tool_call['name']}"
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
                result = (
                    f"Tool '{tool_call['name']}' failed. "
                    "Inspect the field again or choose another supported interaction."
                )
                get_logger().exception(
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

    return _State(
        messages=tool_messages,
        call_count=0,
        tool_call_count=len(tool_messages),
        failure_count=failed_calls,
    )


async def _evaluate(state: _State, runtime: Runtime[_Runtime]) -> _State:
    """
    Translates the model output to structured data for the form fields.

    Args:
        state (_State): The current state of the application process.
        runtime (_Runtime): The runtime information of the application process.

    Returns:
        _State: The updated state of the application process.
    """
    if not state.messages:
        raise RuntimeError("Agent state contains no messages.")
    structured = runtime.context.model.with_structured_output(state.structured_output_type)
    msg: BaseModel = await structured.ainvoke(
        state.messages
        + [
            HumanMessage(
                content=(
                    "Based on the above, convert the answers to an object. "
                    f"The schema is {state.structured_output_type.model_json_schema()}. "
                    "Return the object as JSON and nothing else."
                )
            )
        ]
    )
    return _State(call_count=0, structured_output=msg)


def post_act_router(state: _State) -> str:
    if not state.messages:
        raise RuntimeError("Agent state contains no messages.")

    if state.failure_count >= settings().AGENT_MAX_FAILURES:
        get_logger().warning(
            "Too many failures. Ending the application process.",
            failure_count=state.failure_count,
        )
        return END

    if state.call_count >= settings().AGENT_MAX_ACTIONS:
        get_logger().warning(
            "Too many model actions. Ending the application process.",
            action_count=state.call_count,
        )
        return END

    last_message = state.messages[-1]

    if last_message.type == "ai" and last_message.tool_calls:
        return "use_tool"

    return "evaluate"


@cache
def get_react_agent_with_structured_output() -> CompiledStateGraph[_State, _Runtime]:
    """
    Builds and returns the compiled answer agent.

    Returns:
        CompiledStateGraph[_State, _Runtime]: The compiled answer agent.
    """
    graph = StateGraph(_State, context_schema=_Runtime)
    graph.add_node("act", _act)
    graph.add_node("use_tool", _use_tool)
    graph.add_node("evaluate", _evaluate)

    graph.add_edge(START, "act")
    graph.add_conditional_edges("act", post_act_router)
    graph.add_edge("use_tool", "act")
    graph.add_edge("evaluate", END)

    agent = graph.compile()
    return agent
