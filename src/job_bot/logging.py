from __future__ import annotations

import logging
import os
import sys

import structlog
from structlog.typing import EventDict, WrappedLogger

LOG_LEVEL_ENV = "LOG_LEVEL"
APP_ENV_ENV = "APP_ENV"
LOCAL_APP_ENV = "local"
UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def _order_log_keys(
    _logger: WrappedLogger,
    _method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Put the common log keys first while preserving all remaining field order."""
    return {
        **{key: event_dict[key] for key in ("level", "event") if key in event_dict},
        **{key: value for key, value in event_dict.items() if key not in {"level", "event"}},
    }


def configure_logging() -> None:
    """Configure structlog and route standard-library logs through its renderer."""
    level_name = os.getenv(LOG_LEVEL_ENV, "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    renderer = (
        structlog.dev.ConsoleRenderer()
        if os.getenv(APP_ENV_ENV, "").strip().lower() == LOCAL_APP_ENV
        else structlog.processors.JSONRenderer()
    )
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _order_log_keys,
    ]

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                renderer,
            ],
            foreign_pre_chain=shared_processors,
        )
    )
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)
    for logger_name in UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.setLevel(logging.NOTSET)
        uvicorn_logger.propagate = True

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
