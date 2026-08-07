from __future__ import annotations

from functools import cache
from importlib import import_module
from threading import Lock
from typing import Any

from job_bot.config import settings

_client_lock = Lock()


def OpenAI(*args: Any, **kwargs: Any) -> Any:  # pylint: disable=invalid-name
    """Construct a sync client without importing the OpenAI SDK at startup."""
    return import_module("openai").OpenAI(*args, **kwargs)


def AsyncOpenAI(*args: Any, **kwargs: Any) -> Any:  # pylint: disable=invalid-name
    """Construct an async client without importing the OpenAI SDK at startup."""
    return import_module("openai").AsyncOpenAI(*args, **kwargs)


@cache
def get_openai_client(api_key: str | None = None, base_url: str | None = None) -> Any:
    configured_api_key = settings().OPENAI_API_KEY
    resolved_api_key = api_key or (
        configured_api_key.get_secret_value() if configured_api_key is not None else None
    )
    if not resolved_api_key:
        raise RuntimeError("Missing required environment variable: OPENAI_API_KEY")

    with _client_lock:
        _client = OpenAI(api_key=resolved_api_key, base_url=base_url)

    return _client


@cache
def get_async_openai_client(api_key: str | None = None, base_url: str | None = None) -> Any:
    configured_api_key = settings().OPENAI_API_KEY
    resolved_api_key = api_key or (
        configured_api_key.get_secret_value() if configured_api_key is not None else None
    )
    if not resolved_api_key:
        raise RuntimeError("Missing required environment variable: OPENAI_API_KEY")

    with _client_lock:
        _async_client = AsyncOpenAI(api_key=resolved_api_key, base_url=base_url)

    return _async_client
