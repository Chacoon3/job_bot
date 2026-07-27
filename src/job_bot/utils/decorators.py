import inspect
from collections.abc import Awaitable, Callable
from functools import wraps
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
