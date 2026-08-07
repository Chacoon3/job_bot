from __future__ import annotations

from typing import Annotated, Literal, TypedDict

import redis
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from job_bot.api.dependencies import get_session
from job_bot.config import settings

router = APIRouter(prefix="/api", tags=["job_bot"])


HealthStatus = Literal["healthy", "unhealthy", "disabled"]


class ComponentHealth(TypedDict, total=False):
    status: HealthStatus
    detail: str


def _healthy(detail: str | None = None) -> ComponentHealth:
    result: ComponentHealth = {"status": "healthy"}

    if detail is not None:
        result["detail"] = detail

    return result


def _unhealthy(detail: str) -> ComponentHealth:
    return {
        "status": "unhealthy",
        "detail": detail,
    }


def _disabled(detail: str) -> ComponentHealth:
    return {
        "status": "disabled",
        "detail": detail,
    }


async def _check_database(session: AsyncSession) -> ComponentHealth:
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        get_logger().exception(
            "Database health check failed.",
            error_type=type(exc).__name__,
        )
        return _unhealthy(f"database check failed: {type(exc).__name__}")

    return _healthy()


def _check_redis() -> ComponentHealth:
    cfg = settings()

    if not cfg.REDIS_URL:
        return _disabled("REDIS_URL is not configured")

    client = redis.Redis.from_url(
        cfg.REDIS_URL,
        socket_timeout=cfg.REDIS_SOCKET_TIMEOUT_SECONDS,
        socket_connect_timeout=cfg.REDIS_SOCKET_TIMEOUT_SECONDS,
        decode_responses=True,
    )

    try:
        client.ping()
    except RedisError as exc:
        get_logger().exception(
            "Redis health check failed.",
            error_type=type(exc).__name__,
        )
        return _unhealthy(f"redis check failed: {type(exc).__name__}")
    finally:
        client.close()

    return _healthy()


@router.get("/health/live")
def liveness() -> dict[str, str]:
    """
    Report whether the application process is alive.

    This endpoint deliberately does not check external dependencies.
    """
    return {"status": "healthy"}


@router.get("/health/ready")
async def readiness(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> JSONResponse:
    """
    Report whether the application is ready to serve traffic.

    Readiness requires all enabled dependencies to be healthy.
    Disabled optional dependencies do not make the service unhealthy.
    """
    components: dict[str, ComponentHealth] = {
        "db": await _check_database(session),
        "redis": _check_redis(),
    }

    unhealthy = any(component["status"] == "unhealthy" for component in components.values())

    overall_status = "unhealthy" if unhealthy else "healthy"

    return JSONResponse(
        status_code=(status.HTTP_503_SERVICE_UNAVAILABLE if unhealthy else status.HTTP_200_OK),
        content={
            "status": overall_status,
            "components": components,
        },
    )
