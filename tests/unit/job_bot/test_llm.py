from job_bot.config import settings
from job_bot.llm import GeminiLLMProvider, OpenAILLMProvider


def test_provider_base_resolves_default_model_from_settings(monkeypatch) -> None:
    monkeypatch.setenv("JOB_BOT_LLM_MODEL", "configured-model")
    settings.cache_clear()

    assert OpenAILLMProvider().model == "configured-model"
    assert GeminiLLMProvider().model == "configured-model"


def test_explicit_model_overrides_configured_default(monkeypatch) -> None:
    monkeypatch.setenv("JOB_BOT_LLM_MODEL", "configured-model")
    settings.cache_clear()

    assert OpenAILLMProvider(model="explicit-model").model == "explicit-model"


def test_openai_provider_can_disable_parallel_tool_calls() -> None:
    model = OpenAILLMProvider(
        api_key="test-key",
        parallel_tool_calls=False,
    ).get_model()

    assert model.model_kwargs["parallel_tool_calls"] is False
