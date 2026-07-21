from job_bot.llm import OpenAILLMProvider


def test_openai_provider_can_disable_parallel_tool_calls() -> None:
    model = OpenAILLMProvider(
        api_key="test-key",
        parallel_tool_calls=False,
    ).get_model()

    assert model.model_kwargs["parallel_tool_calls"] is False
