from unittest.mock import Mock

import pytest

from job_bot.openai_client import _reset_openai_client_for_tests, get_openai_client


def test_get_openai_client_returns_singleton(monkeypatch) -> None:
    created_clients: list[object] = []

    def fake_openai(*, api_key: str, base_url: str | None = None) -> object:
        client = Mock()
        client.api_key = api_key
        client.base_url = base_url
        created_clients.append(client)
        return client

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("job_bot.openai_client.OpenAI", fake_openai)
    _reset_openai_client_for_tests()

    first = get_openai_client()
    second = get_openai_client()

    assert first is second
    assert len(created_clients) == 1


def test_get_openai_client_recreates_when_config_changes(monkeypatch) -> None:
    created_clients: list[object] = []

    def fake_openai(*, api_key: str, base_url: str | None = None) -> object:
        client = Mock()
        client.api_key = api_key
        client.base_url = base_url
        created_clients.append(client)
        return client

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("job_bot.openai_client.OpenAI", fake_openai)
    _reset_openai_client_for_tests()

    first = get_openai_client(base_url="https://api.example.com/v1")
    second = get_openai_client(base_url="https://api.example.com/v2")

    assert first is not second
    assert len(created_clients) == 2


def test_get_openai_client_raises_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _reset_openai_client_for_tests()

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        get_openai_client()
