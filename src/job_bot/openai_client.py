from __future__ import annotations

import os
from threading import Lock

from openai import OpenAI

_client: OpenAI | None = None
_client_config: tuple[str, str | None] | None = None
_client_lock = Lock()


def get_openai_client(api_key: str | None = None, base_url: str | None = None) -> OpenAI:
    resolved_api_key = api_key or os.getenv("OPENAI_API_KEY")
    if not resolved_api_key:
        raise RuntimeError("Missing required environment variable: OPENAI_API_KEY")

    config = (resolved_api_key, base_url)

    global _client
    global _client_config

    with _client_lock:
        if _client is None or _client_config != config:
            _client = OpenAI(api_key=resolved_api_key, base_url=base_url)
            _client_config = config

    return _client


def _reset_openai_client_for_tests() -> None:
    global _client
    global _client_config
    with _client_lock:
        _client = None
        _client_config = None
