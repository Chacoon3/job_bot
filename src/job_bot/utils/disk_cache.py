from __future__ import annotations

import hashlib
import inspect
import os
import pickle
import time
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import Any, Callable, ParamSpec, TypeVar, cast, overload

P = ParamSpec("P")
R = TypeVar("R")

KeyBuilder = Callable[[Callable[..., Any], tuple[Any, ...], dict[str, Any]], str]


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float | None = None


class DiskCache:
    """File-backed decorator cache for Python callables.

    The cache stores each invocation result in an individual pickle file under
    the user-provided cache directory.
    """

    def __init__(
        self,
        cache_dir: str | os.PathLike[str],
        ttl: float | None = None,
    ) -> None:
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._default_ttl = ttl

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
        """Wrap a callable and persist call results to disk.

        Supports both decorator forms:
        - ``@cache.wrap``
        - ``@cache.wrap(key_builder=...)``
        """
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
        """Remove all cached entries from the cache directory."""
        for item in self._cache_dir.glob("*.pkl"):
            item.unlink(missing_ok=True)

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

    def _cache_file(self, key: str) -> Path:
        return self._cache_dir / f"{key}.pkl"

    def _read_cache(self, key: str) -> tuple[bool, Any]:
        path = self._cache_file(key)
        if not path.exists():
            return (False, None)

        try:
            with path.open("rb") as handle:
                payload = pickle.load(handle)

            if isinstance(payload, _CacheEntry):
                if payload.expires_at is not None and time.time() >= payload.expires_at:
                    path.unlink(missing_ok=True)
                    return (False, None)
                return (True, payload.value)

            # Backward compatibility for entries written before TTL support.
            return (True, payload)
        except Exception:
            # Ignore unreadable cache entries and recompute.
            return (False, None)

    def _write_cache(self, key: str, value: Any, ttl: float | None) -> None:
        if ttl is not None and ttl <= 0:
            return

        path = self._cache_file(key)
        temp_path = path.with_suffix(".tmp")
        expires_at = None if ttl is None else time.time() + ttl
        payload = _CacheEntry(value=value, expires_at=expires_at)
        with temp_path.open("wb") as handle:
            pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
        temp_path.replace(path)
