from __future__ import annotations

from time import perf_counter_ns
from uuid import uuid4

import structlog
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from job_bot.config import settings

logger = structlog.get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
LOCAL_APP_ENV = "local"


class RequestLoggingMiddleware:
    """Log common request and response metadata for every HTTP request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.render_server_errors = _should_render_server_errors()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        request_id = headers.get(REQUEST_ID_HEADER) or str(uuid4())
        method = scope["method"]
        path = scope["path"]
        client = scope.get("client")
        client_host = client[0] if client else None
        started_at = perf_counter_ns()
        status_code: int | None = None

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        with structlog.contextvars.bound_contextvars(request_id=request_id):
            logger.info(
                "http_request_started",
                method=method,
                path=path,
                client_host=client_host,
            )
            try:
                await self.app(scope, receive, send_with_request_id)
            except Exception as exc:
                status_code = 500
                logger.exception(
                    "http_request_failed",
                    method=method,
                    path=path,
                    duration_ms=_duration_ms(started_at),
                )
                response = JSONResponse(
                    status_code=status_code,
                    content=_server_error_payload(exc, self.render_server_errors),
                )
                await response(scope, receive, send_with_request_id)

            logger.info(
                "http_request_completed",
                method=method,
                path=path,
                status_code=status_code,
                duration_ms=_duration_ms(started_at),
            )


def register_middleware(app: FastAPI) -> None:
    """Register all application middleware in one place."""

    app.add_middleware(RequestLoggingMiddleware)


def _duration_ms(started_at: int) -> float:
    return round((perf_counter_ns() - started_at) / 1_000_000, 3)


def _server_error_payload(exc: Exception, render_server_errors: bool) -> dict[str, str]:
    if render_server_errors:
        return {
            "detail": str(exc) or "Internal Server Error",
            "error": exc.__class__.__name__,
        }
    return {"detail": "Internal Server Error"}


def _should_render_server_errors() -> bool:
    return settings().APP_ENV.strip().lower() == LOCAL_APP_ENV
