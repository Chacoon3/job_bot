import asyncio

from langchain_core.tools import tool

from job_bot.agent import fill_form_agent
from job_bot.agent.fill_form_agent import _agent_answer_cache_key
from job_bot.data.schemas import FormAnswer, FormField, User
from job_bot.utils.redis_cache import RedisCache


class FakeModel:
    def __init__(self, name: str = "test-model") -> None:
        self._identifying_params = {"model_name": name}

    def bind_tools(self, _tools):
        return self


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}

    def get(self, key: str):
        return self.values.get(key)

    def set(self, key: str, value: bytes, **_kwargs) -> None:
        self.values[key] = value


@tool
def inspect_page(query: str) -> str:
    """Inspect the active page for a query."""
    return query


@tool
def inspect_page_with_limit(query: str, limit: int) -> str:
    """Inspect the active page for a query with a result limit."""
    return f"{query}:{limit}"


def _user(summary: str = "Engineer") -> User:
    return User(
        first_name="Alex",
        last_name="Doe",
        email="alex@example.com",
        phone_country="United States",
        phone="555-0100",
        education=[],
        resume_text="Python engineer",
        summary=summary,
    )


def _key(
    *,
    model: FakeModel | None = None,
    tools=None,
    fields=None,
    user: User | None = None,
) -> str:
    return _agent_answer_cache_key(
        fill_form_agent.agent_infer_interactive_element_answer,
        (
            model or FakeModel(),
            tools or [inspect_page],
            fields or [FormField(tag="input", accessible_name="First name")],
            user or _user(),
        ),
        {},
    )


def test_answer_cache_key_is_stable_for_equivalent_inputs() -> None:
    assert _key() == _key()


def test_answer_cache_key_changes_with_each_semantic_input() -> None:
    baseline = _key()

    assert _key(model=FakeModel("other-model")) != baseline
    assert _key(tools=[inspect_page_with_limit]) != baseline
    assert _key(fields=[FormField(tag="select", accessible_name="Country")]) != baseline
    assert _key(user=_user(summary="Platform engineer")) != baseline


def test_answer_cache_key_changes_when_input_schema_changes(monkeypatch) -> None:
    baseline = _key()
    original = fill_form_agent.model_schema_key

    monkeypatch.setattr(
        fill_form_agent,
        "model_schema_key",
        lambda model: f"changed:{original(model)}",
    )

    assert _key() != baseline


def test_agent_answer_is_reused_from_cache(monkeypatch) -> None:
    calls = 0
    expected = [FormAnswer(field_accessible_name="First name", answer="Alex")]

    class _StructuredOutput:
        def __init__(self, answers):
            self.answers = answers

    class FakeAgent:
        async def ainvoke(self, _state, *, context):
            nonlocal calls
            calls += 1
            return {"structured_output": _StructuredOutput(expected)}

    monkeypatch.setattr(
        fill_form_agent,
        "get_react_agent_with_structured_output",
        lambda: FakeAgent(),
    )
    monkeypatch.setattr(fill_form_agent, "_Runtime", lambda **kwargs: kwargs)
    uncached = fill_form_agent.agent_infer_interactive_element_answer.__wrapped__
    cached = RedisCache(client=FakeRedis()).cached(
        uncached,
        key_builder=_agent_answer_cache_key,
    )
    arguments = (
        FakeModel(),
        [inspect_page],
        [FormField(tag="input", accessible_name="First name")],
        _user(),
    )

    first = asyncio.run(cached(*arguments))
    second = asyncio.run(cached(*arguments))

    assert first == expected
    assert second == expected
    assert calls == 1
