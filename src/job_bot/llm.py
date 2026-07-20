import os
from abc import ABC, abstractmethod
from typing import cast

from langchain.chat_models.base import BaseChatModel
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_huggingface import (
    ChatHuggingFace,
    HuggingFaceEndpoint,
)
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI


def _resolve_secret(explicit: str | None, env_var: str) -> str:
    value = explicit or os.getenv(env_var)
    if not value:
        raise RuntimeError(f"Missing credential. Set {env_var} or pass it explicitly.")
    return value


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
        return cast(
            BaseChatModel,
            ChatOpenAI(
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
        return cast(
            BaseChatModel,
            ChatGoogleGenerativeAI(
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
        return cast(
            BaseChatModel,
            ChatAnthropic(
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
        llm = HuggingFaceEndpoint(
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
        return cast(BaseChatModel, ChatHuggingFace(llm=llm))


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
        return cast(
            BaseChatModel,
            ChatOllama(
                model=self.model,
                temperature=self.temperature,
                base_url=self.base_url,
            ),
        )
