from __future__ import annotations

import hashlib
import importlib
import inspect
import pickle
from functools import wraps
from typing import Any, Callable, ParamSpec, TypeVar, cast, overload

P = ParamSpec("P")
R = TypeVar("R")

KeyBuilder = Callable[[Callable[..., Any], tuple[Any, ...], dict[str, Any]], str]


class RedisCache:
    """Redis-backed decorator cache for Python callables.

    Cache operations are fail-open: Redis outages should not break request
    handling, they only disable cache hits for the affected operations.
    """

    def __init__(
        self,
        url: str | None = None,
        *,
        prefix: str = "job_bot:cache",
        ttl: float | None = None,
        socket_timeout: float = 1.0,
        client: Any | None = None,
    ) -> None:
        self._prefix = prefix
        self._default_ttl = ttl

        if client is not None:
            self._client = client
            return

        if not url:
            raise ValueError("A Redis URL is required when no client is provided")

        # Lazy dynamic import so tests can inject a fake client without redis installed.
        redis = importlib.import_module("redis")

        self._client = redis.Redis.from_url(
            url,
            socket_timeout=socket_timeout,
            decode_responses=False,
        )

    @overload
    def wrap(
        self,
        func: Callable[P, R],
        *,
        key_builder: KeyBuilder | None = None,
        ttl: float | None = None,
    ) -> Callable[P, R]: ...

    @overload
    def wrap(
        self,
        func: None = None,
        *,
        key_builder: KeyBuilder | None = None,
        ttl: float | None = None,
    ) -> Callable[[Callable[P, R]], Callable[P, R]]: ...

    def wrap(
        self,
        func: Callable[P, R] | None = None,
        *,
        key_builder: KeyBuilder | None = None,
        ttl: float | None = None,
    ) -> Callable[P, R] | Callable[[Callable[P, R]], Callable[P, R]]:
        """Wrap a callable and store call results in Redis."""
        if func is None:
            return lambda target: self._build_wrapper(
                target,
                key_builder=key_builder,
                ttl=ttl,
            )

        return self._build_wrapper(func, key_builder=key_builder, ttl=ttl)

    def cached(
        self,
        func: Callable[P, R] | None = None,
        *,
        key_builder: KeyBuilder | None = None,
        ttl: float | None = None,
    ) -> Callable[P, R] | Callable[[Callable[P, R]], Callable[P, R]]:
        """Alias for ``wrap`` with a cachetools-like method name."""
        return self.wrap(func, key_builder=key_builder, ttl=ttl)

    def __call__(
        self,
        func: Callable[P, R] | None = None,
        *,
        key_builder: KeyBuilder | None = None,
        ttl: float | None = None,
    ) -> Callable[P, R] | Callable[[Callable[P, R]], Callable[P, R]]:
        """Allow direct decorator usage via ``@cache``."""
        return self.wrap(func, key_builder=key_builder, ttl=ttl)

    def clear(self) -> None:
        """Remove all entries for this cache prefix."""
        pattern = f"{self._prefix}:*"
        try:
            keys = list(self._client.scan_iter(match=pattern))
            if keys:
                self._client.delete(*keys)
        except Exception:
            # Cache clear should not fail application logic.
            return

    def _build_wrapper(
        self,
        func: Callable[P, R],
        key_builder: KeyBuilder | None,
        ttl: float | None,
    ) -> Callable[P, R]:
        effective_ttl = self._default_ttl if ttl is None else ttl

        if inspect.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                key = self._build_key(func, args, kwargs, key_builder)
                cached = self._read_cache(key)
                if cached[0]:
                    return cast(R, cached[1])

                result = await cast(Any, func)(*args, **kwargs)
                self._write_cache(key, result, ttl=effective_ttl)
                return cast(R, result)

            return cast(Callable[P, R], async_wrapper)

        @wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            key = self._build_key(func, args, kwargs, key_builder)
            cached = self._read_cache(key)
            if cached[0]:
                return cast(R, cached[1])

            result = func(*args, **kwargs)
            self._write_cache(key, result, ttl=effective_ttl)
            return result

        return sync_wrapper

    def _build_key(
        self,
        func: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        key_builder: KeyBuilder | None,
    ) -> str:
        if key_builder is not None:
            return key_builder(func, args, kwargs)

        func_id = f"{func.__module__}.{func.__qualname__}".encode("utf-8")
        sanitized_args = self._sanitize_method_args(func, args)
        args_blob = self._to_stable_bytes(sanitized_args)
        kwargs_blob = self._to_stable_bytes(self._ordered_kwargs(kwargs))

        digest = hashlib.sha256()
        digest.update(func_id)
        digest.update(b"\x00")
        digest.update(args_blob)
        digest.update(b"\x00")
        digest.update(kwargs_blob)
        return digest.hexdigest()

    def _sanitize_method_args(
        self, func: Callable[..., Any], args: tuple[Any, ...]
    ) -> tuple[Any, ...]:
        if not args:
            return args

        params = list(inspect.signature(func).parameters.values())
        if not params:
            return args

        first_name = params[0].name
        if first_name in {"self", "cls"}:
            return args[1:]
        return args

    def _ordered_kwargs(self, kwargs: dict[str, Any]) -> tuple[tuple[str, Any], ...]:
        return tuple(sorted(kwargs.items(), key=lambda item: item[0]))

    def _to_stable_bytes(self, value: Any) -> bytes:
        try:
            return pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        except Exception:
            return repr(value).encode("utf-8")

    def _qualified_key(self, key: str) -> str:
        return f"{self._prefix}:{key}"

    def _read_cache(self, key: str) -> tuple[bool, Any]:
        try:
            payload = self._client.get(self._qualified_key(key))
            if payload is None:
                return (False, None)
            return (True, pickle.loads(payload))
        except Exception:
            return (False, None)

    def _write_cache(self, key: str, value: Any, ttl: float | None) -> None:
        if ttl is not None and ttl <= 0:
            return

        try:
            payload = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
            qualified = self._qualified_key(key)
            if ttl is None:
                self._client.set(qualified, payload)
                return

            ttl_ms = max(1, int(ttl * 1000))
            self._client.set(qualified, payload, px=ttl_ms)
        except Exception:
            return
