from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Callable
from typing import Any, Literal

from langchain.chat_models import BaseChatModel
from langchain.messages import HumanMessage, SystemMessage
from langchain_community.tools import BaseTool
from pydantic import BaseModel

from job_bot.agent.agent_graph import _Runtime, _State, get_react_agent_with_structured_output
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

    result = await get_react_agent_with_structured_output().ainvoke(state, context=runtime)
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

    result = await get_react_agent_with_structured_output().ainvoke(state, context=runtime)
    return result["structured_output"].status if result["structured_output"] else "unknown"
