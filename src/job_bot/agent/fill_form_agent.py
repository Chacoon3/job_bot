from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Callable
from functools import cache
from operator import add
from typing import Annotated, Any, Literal

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
from job_bot.llm import model_fingerprint
from job_bot.schemas import AgentInferredFormAnswer, FormAnswer, FormField, User
from job_bot.utils.caching import AppRedisCache
from job_bot.utils.hash_helper import model_schema_key

ANSWER_CACHE_VERSION = 1
ANSWER_CACHE_TTL_SECONDS = 60 * 60 * 24 * 7


def _tool_cache_payload(tool: BaseTool) -> dict[str, Any]:
    """Return the stable parts of a tool definition that affect agent behavior."""
    return {
        "type": f"{type(tool).__module__}.{type(tool).__qualname__}",
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.get_input_schema().model_json_schema(),
        "response_format": tool.response_format,
        "return_direct": tool.return_direct,
    }


def _agent_answer_cache_key(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> str:
    """Key agent answers by semantic inputs and their validation schemas."""
    bound = inspect.signature(func).bind(*args, **kwargs)
    model: BaseChatModel = bound.arguments["model"]
    tools: list[BaseTool] = bound.arguments["tools"]
    fields: list[FormField] = bound.arguments["fields"]
    user: User = bound.arguments["user"]
    payload = {
        "cache_version": ANSWER_CACHE_VERSION,
        "model": model_fingerprint(model),
        "tools": [_tool_cache_payload(tool) for tool in tools],
        "fields": [field.model_dump(mode="json") for field in fields],
        "user": user.model_dump(mode="json"),
        "schemas": {
            "field": model_schema_key(FormField),
            "user": model_schema_key(User),
            "answer": model_schema_key(FormAnswer),
            "agent_answer": model_schema_key(AgentInferredFormAnswer),
        },
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return f"agent_infer_answer_v{ANSWER_CACHE_VERSION}_{digest}"


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


@AppRedisCache.cached(
    key_builder=_agent_answer_cache_key,
    ttl=ANSWER_CACHE_TTL_SECONDS,
)
async def agent_infer_interactive_element_answer(
    model: BaseChatModel, tools: list[BaseTool], fields: list[FormField], user: User
) -> list[FormAnswer]:
    """
    Ask the agent to infer the answer for an interactive form element on a web page.

    Args:
        model (BaseChatModel): The chat model to use for the agent.
        tools (list[BaseTool]): The list of tools to use for the agent.
        fields (list[FormField]): The form fields to infer the answer for.
        user (User): The user information.

    Returns:
        list[_FormAnswer]: The inferred answer for the form fields.
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
                    "After analyzing the webpage content, return the answer in the format of a "
                    "JSON array of objects with the accessible name and the answer. "
                    f"The inner object's schema should be {FormAnswer.model_json_schema()}. "
                    "Do not take any action on the web page or fill in the form field yourself. "
                    "If the form elements include privacy consent like receiving marketing emails "
                    "or agreeing to text messages, answer 'No' or 'Decline' for those fields as "
                    "long as it does not stop the form submission. Note that your answer should be "
                    "application-ready. The user will directly copy and paste your answer into the "
                    "form fields. "
                    "The user's information is in JSON format as follows:\n"
                    f"{user.model_dump_json()}"
                )
            ),
            HumanMessage(
                content=(
                    "Based on the information about me, come up with the correct answer "
                    "for the following form fields denoted by their accessible names "
                    f"'{', '.join(field.accessible_name for field in fields)}'."
                )
            ),
        ],
        structured_output_type=AgentInferredFormAnswer,
    )

    result = await _get_answer_agent().ainvoke(state, context=runtime)
    return result["structured_output"].answers if result["structured_output"] else []


async def agent_infer_application_status(
    model: BaseChatModel, tools: list[BaseTool]
) -> Literal["success", "failure", "unknown"]:
    """
    Ask the agent to infer the application status based on the model's messages.

    Args:
        model (BaseChatModel): The chat model to use for the agent.
        tools (list[BaseTool]): The list of tools to use for the agent.

    Returns:
        Literal['success', 'failure', 'unknown']: The inferred application status.
    """
    tool_registry = {tool.name: tool for tool in tools}
    model_with_browser_tools = model.bind_tools(tools)
    runtime = _Runtime(
        model_with_browser_tools=model_with_browser_tools, model=model, tool_registry=tool_registry
    )

    class ApplicationStatusAnswer(BaseModel):
        status: Literal["success", "failure", "unknown"]

    state = _State(
        messages=[
            SystemMessage(
                content=(
                    "You are a browser automation assistant."
                    "Your task is to inspect the webpage and determine whether the application was successful or failed."
                )
            ),
        ],
        structured_output_type=ApplicationStatusAnswer,
    )

    result = await _get_answer_agent().ainvoke(state, context=runtime)
    return result["structured_output"].status if result["structured_output"] else "unknown"
