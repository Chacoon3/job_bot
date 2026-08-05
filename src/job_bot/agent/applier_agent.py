from operator import add
from typing import Annotated

from langchain.chat_models import BaseChatModel
from langchain.messages import AnyMessage, ToolMessage
from langchain_community.tools import BaseTool
from langgraph.graph import END, StateGraph, add_messages
from langgraph.runtime import Runtime
from pydantic import BaseModel
from structlog import get_logger

from job_bot.utils.browser_tools import BrowserSession, build_browser_tools


class _State(BaseModel):
    """
    A dictionary that holds the state of the application process.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    call_count: Annotated[int, add] = 0
    tool_call_count: Annotated[int, add] = 0
    failure_count: Annotated[int, add] = 0
    retry_count: Annotated[int, add] = 0


class _Runtime(BaseModel):
    """
    A Pydantic model that holds the runtime information of the application process.
    """

    browser_session: BrowserSession
    model: BaseChatModel
    tool_registry: dict[str, callable] = {}


def _act(state: _State, runtime: _Runtime) -> _State:
    """
    Performs an action in the application process.

    Args:
        state (_State): The current state of the application process.
        runtime (_Runtime): The runtime information of the application process.

    Returns:
        _State: The updated state of the application process.
    """

    # Here you would implement the logic to perform an action based on the current state and runtime.
    # This could involve interacting with the browser session, sending messages to the model, etc.

    resp = runtime.model.invoke(state.messages)
    return _State(messages=state.messages + [resp], call_count=1)


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
        tool: BaseTool = runtime.context.tool_registry.get(tool_call["name"])
        if tool is None:
            result = f"Tool not found: {tool_call['name']}"
            failed_calls += 1
            get_logger().error(
                "Unsupported tool requested.",
                tool_name=tool_call["name"],
                tool_args=tool_call["args"],
            )
        else:
            try:
                result = await tool.ainvoke(tool_call["args"])
                get_logger().info(
                    "Tool executed successfully.",
                    tool_name=tool_call["name"],
                    tool_args=tool_call["args"],
                )
            except Exception as exc:
                failed_calls += 1
                result = f"Tool execution failed: {type(exc).__name__}: {exc}"
                get_logger().error(
                    "Tool execution failed.",
                    tool_name=tool_call["name"],
                    tool_args=tool_call["args"],
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


def post_act_router(state: _State) -> str:
    if not state.messages:
        raise RuntimeError("Agent state contains no messages.")

    if state.failure_count >= MAX_CONSECUTIVE_FAILURES:
        get_logger().warning(
            "Too many consecutive failures. Ending the application process.",
            consecutive_failures=state.failure_count,
        )
        return END

    if state.call_count >= MAX_MODEL_ACTIONS:
        get_logger().warning(
            "Too many model actions. Ending the application process.",
            action_count=state.call_count,
        )
        return END

    last_message = state.messages[-1]

    if last_message.type == "ai" and last_message.tool_calls:
        return "use_tool"

    return "evaluate"


def build_applier_agent(
    model: BaseChatModel, browser_session: BrowserSession
) -> tuple[_State, _Runtime]:
    """
    Builds the applier agent with the given model and browser session.

    Args:
        model (BaseChatModel): The chat model to use for the agent.
        browser_session (BrowserSession): The browser session to use for the agent.

    Returns:
        tuple[_State, _Runtime]: The initial state and runtime of the applier agent.
    """

    model = model.bind_tools(build_browser_tools(browser_session))
    graph = StateGraph(_State, _Runtime)
    graph.add_node("act", _act)
    graph.add_node("use_tool", _use_tool)

    runtime = _Runtime(browser_session=browser_session, model=model, tool_registry=model.tools)
