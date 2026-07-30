from __future__ import annotations

import os
from functools import cache
from threading import Lock

from openai import AsyncOpenAI, OpenAI

_client_lock = Lock()


@cache
def get_openai_client(api_key: str | None = None, base_url: str | None = None) -> OpenAI:
    resolved_api_key = api_key or os.getenv("OPENAI_API_KEY")
    if not resolved_api_key:
        raise RuntimeError("Missing required environment variable: OPENAI_API_KEY")

    with _client_lock:
        _client = OpenAI(api_key=resolved_api_key, base_url=base_url)

    return _client


@cache
def get_async_openai_client(api_key: str | None = None, base_url: str | None = None) -> AsyncOpenAI:
    resolved_api_key = api_key or os.getenv("OPENAI_API_KEY")
    if not resolved_api_key:
        raise RuntimeError("Missing required environment variable: OPENAI_API_KEY")

    with _client_lock:
        _async_client = AsyncOpenAI(api_key=resolved_api_key, base_url=base_url)

    return _async_client
