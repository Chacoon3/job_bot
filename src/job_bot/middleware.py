from __future__ import annotations

from time import perf_counter_ns
from uuid import uuid4

import structlog
from fastapi import FastAPI
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = structlog.get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


class RequestLoggingMiddleware:
    """Log common request and response metadata for every HTTP request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

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
            except Exception:
                logger.exception(
                    "http_request_failed",
                    method=method,
                    path=path,
                    duration_ms=_duration_ms(started_at),
                )
                raise

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
