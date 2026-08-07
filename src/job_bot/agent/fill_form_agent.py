from __future__ import annotations

from functools import cache
from operator import add
from typing import Annotated

from langchain.chat_models import BaseChatModel
from langchain.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_community.tools import BaseTool
from langchain_core.language_models.base import LanguageModelInput
from langchain_core.runnables import Runnable
from langgraph.graph import END, START, StateGraph, add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from pydantic import BaseModel, ConfigDict, Field
from structlog import get_logger

from job_bot.config import settings
from job_bot.schemas import FormField, User


class _State(BaseModel):
    """
    A dictionary that holds the state of the application process.
    """

    messages: Annotated[list[AnyMessage], add_messages] = Field(default_factory=list)
    call_count: Annotated[int, add] = 0
    tool_call_count: Annotated[int, add] = 0
    failure_count: Annotated[int, add] = 0
    retry_count: Annotated[int, add] = 0
    answers: Annotated[list[_FormAnswer], add] = Field(default_factory=list)


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

    # Here you would implement the logic to perform an action based on the current state and runtime.
    # This could involve interacting with the browser session, sending messages to the model, etc.

    msg = await runtime.context.model_with_browser_tools.ainvoke(state.messages)
    return _State(messages=[msg], call_count=1, answers=state.answers)


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
    translates the model output to structured data for the form fields.

    Args:
        state (_State): The current state of the application process.
        runtime (_Runtime): The runtime information of the application process.

    Returns:
        _State: The updated state of the application process.
    """
    if not state.messages:
        raise RuntimeError("Agent state contains no messages.")
    structured = runtime.context.model.with_structured_output(_AgentInferredFormAnswer)
    msg = await structured.ainvoke(
        state.messages
        + [HumanMessage(content="Provide the inferred answers for the form fields in JSON format.")]
    )
    return _State(call_count=0, answers=msg)


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
def _get_answer_agent() -> CompiledStateGraph[_State, _Runtime]:
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


class _FormAnswer(BaseModel):
    """
    A Pydantic model that holds the inferred answer for a form field.
    """

    field_accessible_name: str = Field(..., description="The name of the form field.")
    answer: str = Field(..., description="The inferred answer for the form field.")


class _AgentInferredFormAnswer(BaseModel):
    """
    A Pydantic model that holds the inferred answer for a form field.
    """

    answers: list[_FormAnswer] = Field(..., description="The inferred answers for the form fields.")


async def agent_infer_interactive_element_answer(
    model: BaseChatModel, tools: list[BaseTool], fields: list[FormField], user: User
) -> str:
    """
    Ask the agent to infer the answer for an interactive form element on a web page.

    Args:
        model (BaseChatModel): The chat model to use for the agent.
        tools (list[BaseTool]): The list of tools to use for the agent.
        fields (list[FormField]): The form fields to infer the answer for.
        user (User): The user information.

    Returns:
        str: The inferred answer for the form fields.
    """
    tool_registry = {tool.name: tool for tool in tools}
    model_with_browser_tools = model.bind_tools(tools)
    runtime = _Runtime(
        model_with_browser_tools=model_with_browser_tools, model=model, tool_registry=tool_registry
    )

    state = _State(
        messages=[
            SystemMessage(
                content=(
                    "You are a browser automation assistant. Use only supplied "
                    "candidate data and never invent answers. Your task is to infer the "
                    "correct answer for a list of form fields based on the user's information and "
                    "the accessible names of the form fields. "
                    "Call inspect_page to understand the context of the fields. "
                    "After receiving the inspection result, return the answer as plain text and stop. "
                    "Do not take any action on the web page or fill in the form field yourself. "
                    "The user's information is in JSON format as follows:\n"
                    f"{user.model_dump_json()}"
                )
            ),
            HumanMessage(
                content=(
                    "Based on the information about me, come up with the correct answer "
                    "for the following form fields denoted by their accessible names "
                    f"'{', '.join(field.accessible_name for field in fields)}'. Return the answer as plain text and nothing else."
                )
            ),
        ]
    )

    resp = await _get_answer_agent().ainvoke(state, context=runtime)
    return resp["messages"][-1].content
