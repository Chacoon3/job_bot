from __future__ import annotations

import logging
import os
import sys

import structlog
from structlog.typing import EventDict, WrappedLogger

LOG_LEVEL_ENV = "LOG_LEVEL"


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
    """Configure application and standard-library logs as structured JSON."""
    level_name = os.getenv(LOG_LEVEL_ENV, "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        level=level,
        stream=sys.stdout,
        force=True,
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            _order_log_keys,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
