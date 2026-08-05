import asyncio
import inspect
from collections.abc import Awaitable, Callable
from functools import wraps
from time import time
from typing import Literal, ParamSpec, TypeVar, cast, overload

from structlog import get_logger

P = ParamSpec("P")
T = TypeVar("T")

LogLevel = Literal[
    "debug",
    "info",
    "warning",
    "error",
    "critical",
]


@overload
def log_upon_exit(
    func: Callable[P, Awaitable[T]],
    *,
    log_level: LogLevel = "info",
    message: str = "",
) -> Callable[P, Awaitable[T]]: ...


@overload
def log_upon_exit(
    func: Callable[P, T],
    *,
    log_level: LogLevel = "info",
    message: str = "",
) -> Callable[P, T]: ...


def log_upon_exit(
    func: Callable[P, T] | Callable[P, Awaitable[T]],
    *,
    log_level: LogLevel = "info",
    message: str = "",
) -> Callable[P, T] | Callable[P, Awaitable[T]]:
    """Log when the decorated sync or async function exits."""

    logger = get_logger()
    log = getattr(logger, log_level)

    def log_exit() -> None:
        log_message = f"Function {func.__qualname__} has exited."
        if message:
            log_message += f" {message}"
        log(log_message)

    if inspect.iscoroutinefunction(func):
        async_func = cast(Callable[P, Awaitable[T]], func)

        @wraps(async_func)
        async def async_wrapper(
            *args: P.args,
            **kwargs: P.kwargs,
        ) -> T:
            try:
                return await async_func(*args, **kwargs)
            finally:
                log_exit()

        return async_wrapper

    sync_func = cast(Callable[P, T], func)

    @wraps(sync_func)
    def sync_wrapper(
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> T:
        try:
            return sync_func(*args, **kwargs)
        finally:
            log_exit()

    return sync_wrapper


@overload
def with_retry(
    *,
    attempts: int = 3,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    delay_seconds: float = 0.0,
    backoff_factor: float = 1.0,
    log_level: LogLevel = "warning",
    message: str = "",
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]: ...


@overload
def with_retry(
    *,
    attempts: int = 3,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    delay_seconds: float = 0.0,
    backoff_factor: float = 1.0,
    log_level: LogLevel = "warning",
    message: str = "",
) -> Callable[[Callable[P, T]], Callable[P, T]]: ...


def with_retry(
    *,
    attempts: int = 3,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    delay_seconds: float = 0.0,
    backoff_factor: float = 1.0,
    log_level: LogLevel = "warning",
    message: str = "",
) -> Callable[
    [Callable[P, T] | Callable[P, Awaitable[T]]],
    Callable[P, T] | Callable[P, Awaitable[T]],
]:
    """Retry a decorated sync or async function when it raises retryable exceptions."""

    if attempts < 1:
        raise ValueError("attempts must be at least 1.")
    if delay_seconds < 0:
        raise ValueError("delay_seconds must be greater than or equal to 0.")
    if backoff_factor <= 0:
        raise ValueError("backoff_factor must be greater than 0.")

    logger = get_logger()

    def decorator(
        func: Callable[P, T] | Callable[P, Awaitable[T]],
    ) -> Callable[P, T] | Callable[P, Awaitable[T]]:
        log = getattr(logger, log_level)

        def get_delay(attempt_number: int) -> float:
            return delay_seconds * (backoff_factor ** (attempt_number - 1))

        def log_retry(exception: BaseException, attempt_number: int) -> None:
            log_message = (
                f"Retrying {func.__qualname__} after attempt "
                f"{attempt_number}/{attempts} raised "
                f"{exception.__class__.__name__}."
            )
            if message:
                log_message += f" {message}"
            log(log_message, next_delay=get_delay(attempt_number))

        if inspect.iscoroutinefunction(func):
            async_func = cast(Callable[P, Awaitable[T]], func)

            @wraps(async_func)
            async def async_wrapper(
                *args: P.args,
                **kwargs: P.kwargs,
            ) -> T:
                for attempt_number in range(1, attempts + 1):
                    try:
                        return await async_func(*args, **kwargs)
                    except exceptions as exception:
                        if attempt_number == attempts:
                            raise
                        log_retry(exception, attempt_number)
                        next_delay = get_delay(attempt_number)
                        if next_delay > 0:
                            await asyncio.sleep(next_delay)

                raise RuntimeError("Retry loop exited unexpectedly.")

            return async_wrapper

        sync_func = cast(Callable[P, T], func)

        @wraps(sync_func)
        def sync_wrapper(
            *args: P.args,
            **kwargs: P.kwargs,
        ) -> T:
            for attempt_number in range(1, attempts + 1):
                try:
                    return sync_func(*args, **kwargs)
                except exceptions as exception:
                    if attempt_number == attempts:
                        raise
                    log_retry(exception, attempt_number)
                    next_delay = get_delay(attempt_number)
                    if next_delay > 0:
                        time.sleep(next_delay)

            raise RuntimeError("Retry loop exited unexpectedly.")

        return sync_wrapper

    return decorator
