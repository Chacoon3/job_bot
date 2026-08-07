import pytest
from fastapi import HTTPException

from job_bot.api import dependencies


def test_browser_automation_guard_rejects_lightweight_runtime(monkeypatch) -> None:
    monkeypatch.setattr(
        dependencies,
        "settings",
        lambda: type("Settings", (), {"BROWSER_AUTOMATION_ENABLED": False})(),
    )

    with pytest.raises(HTTPException) as exc_info:
        dependencies.require_browser_automation()

    assert exc_info.value.status_code == 503


def test_browser_automation_guard_allows_worker_runtime(monkeypatch) -> None:
    monkeypatch.setattr(
        dependencies,
        "settings",
        lambda: type("Settings", (), {"BROWSER_AUTOMATION_ENABLED": True})(),
    )

    assert dependencies.require_browser_automation() is None
