from job_bot.config import settings


def test_settings_are_cached_until_explicitly_cleared(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "first")
    settings.cache_clear()

    first = settings()
    monkeypatch.setenv("APP_ENV", "second")

    assert settings() is first
    assert settings().APP_ENV == "first"

    settings.cache_clear()
    assert settings().APP_ENV == "second"
