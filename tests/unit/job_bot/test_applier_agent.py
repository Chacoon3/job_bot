import asyncio

from langchain.messages import AIMessage, AnyMessage, HumanMessage
from langchain_core.runnables import RunnableLambda
from langchain_core.tools import tool

from job_bot.agent.fill_form_agent import _get_answer_agent as _get_applier_agent
from job_bot.agent.fill_form_agent import _Runtime, _State


def test_applier_agent_receives_model_through_runtime_context() -> None:
    async def invoke_model(messages: list[HumanMessage]) -> AIMessage:
        assert messages[-1].content == "Fill this field"
        return AIMessage(content="done")

    context = _Runtime(model=RunnableLambda(invoke_model))
    state = _State(messages=[HumanMessage(content="Fill this field")])

    result = asyncio.run(_get_applier_agent().ainvoke(state, context=context))

    assert result["messages"][-1].content == "done"
    assert result["call_count"] == 1


def test_applier_agent_limits_successful_page_inspection_to_one() -> None:
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

    context = _Runtime(
        model=RunnableLambda(invoke_model),
        tool_registry={"inspect_page": inspect_page},
    )
    state = _State(messages=[HumanMessage(content="Infer the answer")])

    result = asyncio.run(_get_applier_agent().ainvoke(state, context=context))

    assert inspection_calls == 1
    assert result["successful_inspection_count"] == 1
    assert result["tool_call_count"] == 2
    assert result["failure_count"] == 1
    assert result["call_count"] == 3
    assert result["messages"][-1].content == "Yes"
