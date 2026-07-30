from __future__ import annotations

import json

import structlog

from job_bot.logging import configure_logging


def test_configure_logging_orders_level_and_event_before_other_fields(capsys) -> None:
    configure_logging()

    structlog.get_logger("test").info("job_found", job_id="123", company="Example")

    log_record = json.loads(capsys.readouterr().out)

    assert list(log_record)[:2] == ["level", "event"]
    assert log_record["level"] == "info"
    assert log_record["event"] == "job_found"
    assert log_record["job_id"] == "123"
    assert log_record["company"] == "Example"
