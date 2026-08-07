import json
from abc import ABC, abstractmethod
from hashlib import sha256
from importlib import import_module
from typing import Any

import regex
from langchain_core.language_models.chat_models import BaseChatModel

from job_bot.config import setting_value, settings


def _resolve_secret(explicit: str | None, env_var: str) -> str:
    value = explicit or setting_value(env_var)
    if not value:
        raise RuntimeError(f"Missing credential. Set {env_var} or pass it explicitly.")
    return value


class LLMProvider(ABC):
    def __init__(self, model: str | None = None) -> None:
        self.model = model or settings().JOB_BOT_LLM_MODEL

    @abstractmethod
    def get_model(self) -> Any:
        raise NotImplementedError


class OpenAILLMProvider(LLMProvider):
    def __init__(
        self,
        model: str | None = None,
        temperature: float = 0.0,
        api_key: str | None = None,
        base_url: str | None = None,
        parallel_tool_calls: bool | None = None,
    ) -> None:
        super().__init__(model)
        self.temperature = temperature
        self.api_key = api_key
        self.base_url = base_url
        self.parallel_tool_calls = parallel_tool_calls

    def get_model(self) -> Any:
        # Provider SDKs are intentionally loaded only when this provider is used.
        from langchain_openai import ChatOpenAI

        model_args = {}
        if self.parallel_tool_calls is not None:
            model_args["parallel_tool_calls"] = self.parallel_tool_calls
        if regex.search("^gpt-.*-luna$", self.model or ""):
            model_args["reasoning_effort"] = "none"
        return ChatOpenAI(
            model=self.model,
            temperature=self.temperature,
            api_key=_resolve_secret(self.api_key, "OPENAI_API_KEY"),
            base_url=self.base_url,
            model_kwargs=model_args,
        )


class GeminiLLMProvider(LLMProvider):
    def __init__(
        self,
        model: str | None = None,
        temperature: float = 0.0,
        api_key: str | None = None,
    ) -> None:
        super().__init__(model)
        self.temperature = temperature
        self.api_key = api_key

    def get_model(self) -> Any:
        chat_google = import_module("langchain_google_genai").ChatGoogleGenerativeAI
        return chat_google(
            model=self.model,
            temperature=self.temperature,
            api_key=_resolve_secret(self.api_key, "GOOGLE_API_KEY"),
        )


class AnthropicLLMProvider(LLMProvider):
    def __init__(
        self,
        model: str | None = None,
        temperature: float = 0.0,
        api_key: str | None = None,
    ) -> None:
        super().__init__(model)
        self.temperature = temperature
        self.api_key = api_key

    def get_model(self) -> Any:
        chat_anthropic = import_module("langchain_anthropic").ChatAnthropic
        return chat_anthropic(
            model_name=self.model,
            temperature=self.temperature,
            api_key=_resolve_secret(self.api_key, "ANTHROPIC_API_KEY"),
        )


class HuggingFaceRemoteLLMProvider(LLMProvider):
    def __init__(
        self,
        model: str | None = None,
        temperature: float = 0.0,
        api_token: str | None = None,
        endpoint_url: str | None = None,
        provider: str | None = None,
        max_new_tokens: int = 512,
    ) -> None:
        super().__init__(model)
        self.temperature = temperature
        self.api_token = api_token
        self.endpoint_url = endpoint_url
        self.provider = provider
        self.max_new_tokens = max_new_tokens

    def get_model(self) -> Any:
        huggingface = import_module("langchain_huggingface")
        llm = huggingface.HuggingFaceEndpoint(
            model=self.model,
            endpoint_url=self.endpoint_url,
            provider=self.provider,
            huggingfacehub_api_token=_resolve_secret(
                self.api_token,
                "HUGGINGFACEHUB_API_TOKEN",
            ),
            temperature=self.temperature,
            max_new_tokens=self.max_new_tokens,
        )
        return huggingface.ChatHuggingFace(llm=llm)


class OllamaLLMProvider(LLMProvider):
    def __init__(
        self,
        model: str | None = None,
        temperature: float = 0.0,
        base_url: str | None = None,
    ) -> None:
        super().__init__(model)
        self.temperature = temperature
        self.base_url = base_url or settings().OLLAMA_BASE_URL

    def get_model(self) -> Any:
        chat_ollama = import_module("langchain_ollama").ChatOllama
        return chat_ollama(
            model=self.model,
            temperature=self.temperature,
            base_url=self.base_url,
        )


def model_fingerprint(model: BaseChatModel) -> str:
    payload = {
        "type": f"{type(model).__module__}.{type(model).__qualname__}",
        "params": model._identifying_params,  # pylint: disable=protected-access; intended use
    }

    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )

    return sha256(canonical.encode()).hexdigest()
