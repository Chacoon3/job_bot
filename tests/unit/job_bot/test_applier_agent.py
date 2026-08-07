import asyncio

from langchain.chat_models import BaseChatModel
from langchain.messages import AIMessage, AnyMessage, HumanMessage
from langchain_core.runnables import RunnableLambda
from langchain_core.tools import tool
from pydantic import BaseModel

from job_bot.agent.agent_graph import _Runtime, _State, get_react_agent_with_structured_output
from job_bot.schemas import AgentInferredFormAnswer


class _StatusAnswer(BaseModel):
    status: str


class FakeChatModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "test"

    def _generate(self, *_args, **_kwargs):
        raise AssertionError("The bound model should handle agent actions.")

    def with_structured_output(self, _schema):
        return RunnableLambda(lambda _messages: AgentInferredFormAnswer(answers=[]))


def _runtime(model_with_browser_tools: RunnableLambda) -> _Runtime:
    return _Runtime(
        model=FakeChatModel(),
        model_with_browser_tools=model_with_browser_tools,
    )


def test_applier_agent_receives_model_through_runtime_context() -> None:
    async def invoke_model(messages: list[HumanMessage]) -> AIMessage:
        assert messages[-1].content == "Fill this field"
        return AIMessage(content="done")

    context = _runtime(RunnableLambda(invoke_model))
    state = _State(
        messages=[HumanMessage(content="Fill this field")],
        structured_output_type=_StatusAnswer,
    )

    result = asyncio.run(get_react_agent_with_structured_output().ainvoke(state, context=context))

    assert result["messages"][-1].content == "done"
    assert result["call_count"] == 1


def test_applier_agent_executes_each_requested_tool() -> None:
    model_calls = 0
    inspection_calls = 0

    async def invoke_model(messages: list[AnyMessage]) -> AIMessage:
        nonlocal model_calls
        model_calls += 1
        if model_calls <= 2:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "inspect_page",
                        "args": {},
                        "id": f"inspection-{model_calls}",
                        "type": "tool_call",
                    }
                ],
            )
        return AIMessage(content="Yes")

    @tool
    def inspect_page() -> str:
        """Inspect the current application page."""
        nonlocal inspection_calls
        inspection_calls += 1
        return "The field asks whether the candidate resides in the United States."

    context = _runtime(RunnableLambda(invoke_model))
    context.tool_registry = {"inspect_page": inspect_page}
    state = _State(
        messages=[HumanMessage(content="Infer the answer")],
        structured_output_type=_StatusAnswer,
    )

    result = asyncio.run(get_react_agent_with_structured_output().ainvoke(state, context=context))

    assert inspection_calls == 2
    assert result["tool_call_count"] == 2
    assert result["failure_count"] == 0
    assert result["call_count"] == 3
    assert result["messages"][-1].content == "Yes"
