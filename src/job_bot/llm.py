import importlib
import os
from abc import ABC, abstractmethod
from typing import Any, cast

from langchain.chat_models.base import BaseChatModel


def _resolve_secret(explicit: str | None, env_var: str) -> str:
    value = explicit or os.getenv(env_var)
    if not value:
        raise RuntimeError(f"Missing credential. Set {env_var} or pass it explicitly.")
    return value


def _import_attr(module_name: str, attr_name: str) -> Any:
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise RuntimeError(
            f"Missing dependency '{module_name}'. Install it to use this provider."
        ) from exc
    try:
        return getattr(module, attr_name)
    except AttributeError as exc:
        raise RuntimeError(f"Dependency '{module_name}' does not expose '{attr_name}'.") from exc


class LLMProvider(ABC):
    @abstractmethod
    def get_model(self) -> BaseChatModel:
        raise NotImplementedError


class OpenAILLMProvider(LLMProvider):
    def __init__(
        self,
        model: str = "gpt-4o-mini",
        temperature: float = 0.0,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.api_key = api_key
        self.base_url = base_url

    def get_model(self) -> BaseChatModel:
        chat_openai_cls = _import_attr("langchain_openai", "ChatOpenAI")
        return cast(
            BaseChatModel,
            chat_openai_cls(
                model=self.model,
                temperature=self.temperature,
                api_key=_resolve_secret(self.api_key, "OPENAI_API_KEY"),
                base_url=self.base_url,
            ),
        )


class GeminiLLMProvider(LLMProvider):
    def __init__(
        self,
        model: str = "gemini-2.5-flash",
        temperature: float = 0.0,
        api_key: str | None = None,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.api_key = api_key

    def get_model(self) -> BaseChatModel:
        chat_google_cls = _import_attr("langchain_google_genai", "ChatGoogleGenerativeAI")
        return cast(
            BaseChatModel,
            chat_google_cls(
                model=self.model,
                temperature=self.temperature,
                api_key=_resolve_secret(self.api_key, "GOOGLE_API_KEY"),
            ),
        )


class AnthropicLLMProvider(LLMProvider):
    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        temperature: float = 0.0,
        api_key: str | None = None,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.api_key = api_key

    def get_model(self) -> BaseChatModel:
        chat_anthropic_cls = _import_attr("langchain_anthropic", "ChatAnthropic")
        return cast(
            BaseChatModel,
            chat_anthropic_cls(
                model_name=self.model,
                temperature=self.temperature,
                api_key=_resolve_secret(self.api_key, "ANTHROPIC_API_KEY"),
            ),
        )


class HuggingFaceRemoteLLMProvider(LLMProvider):
    def __init__(
        self,
        model: str,
        temperature: float = 0.0,
        api_token: str | None = None,
        endpoint_url: str | None = None,
        provider: str | None = None,
        max_new_tokens: int = 512,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.api_token = api_token
        self.endpoint_url = endpoint_url
        self.provider = provider
        self.max_new_tokens = max_new_tokens

    def get_model(self) -> BaseChatModel:
        endpoint_cls = _import_attr("langchain_huggingface", "HuggingFaceEndpoint")
        chat_hf_cls = _import_attr("langchain_huggingface", "ChatHuggingFace")
        llm = endpoint_cls(
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
        return cast(BaseChatModel, chat_hf_cls(llm=llm))


class OllamaLLMProvider(LLMProvider):
    def __init__(
        self,
        model: str = "llama3.1",
        temperature: float = 0.0,
        base_url: str | None = None,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.base_url = base_url or os.getenv("OLLAMA_BASE_URL")

    def get_model(self) -> BaseChatModel:
        chat_ollama_cls = _import_attr("langchain_ollama", "ChatOllama")
        return cast(
            BaseChatModel,
            chat_ollama_cls(
                model=self.model,
                temperature=self.temperature,
                base_url=self.base_url,
            ),
        )
