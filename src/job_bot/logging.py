from __future__ import annotations

import logging
import sys

import structlog
from opentelemetry import trace
from structlog.typing import EventDict, WrappedLogger

from job_bot.config import setting_value, settings

LOG_LEVEL_ENV = "LOG_LEVEL"
APP_ENV_ENV = "APP_ENV"
LOCAL_APP_ENV = "local"
UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def _add_trace_context(
    _logger: WrappedLogger,
    _method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Correlate logs emitted inside an active OpenTelemetry span."""
    span_context = trace.get_current_span().get_span_context()
    if span_context.is_valid:
        event_dict["trace_id"] = format(span_context.trace_id, "032x")
        event_dict["span_id"] = format(span_context.span_id, "016x")
    return event_dict


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
    cfg = settings()
    level_name = cfg.LOG_LEVEL.upper()
    level = getattr(logging, level_name, logging.INFO)
    app_env = (setting_value(APP_ENV_ENV) or "").strip().lower()
    renderer = (
        structlog.dev.ConsoleRenderer()
        if app_env == LOCAL_APP_ENV
        else structlog.processors.JSONRenderer()
    )
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        _add_trace_context,
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
