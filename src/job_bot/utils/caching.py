from __future__ import annotations

import os
from typing import Any

from job_bot.utils.disk_cache import DiskCache
from job_bot.utils.json_file_writer import JsonFileWriter
from job_bot.utils.redis_cache import RedisCache


def _read_float_env(name: str) -> float | None:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _build_app_cache() -> Any:
    backend = os.getenv("APP_CACHE_BACKEND", "disk").strip().lower()
    default_ttl = _read_float_env("APP_CACHE_TTL_SECONDS")

    if backend == "redis":
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        redis_prefix = os.getenv("REDIS_CACHE_PREFIX", "job_bot:cache")
        redis_timeout = _read_float_env("REDIS_SOCKET_TIMEOUT_SECONDS")
        socket_timeout = 1.0 if redis_timeout is None else redis_timeout

        return RedisCache(
            redis_url,
            prefix=redis_prefix,
            ttl=default_ttl,
            socket_timeout=socket_timeout,
        )

    cache_dir = os.getenv("DISK_CACHE_DIR", "./.cache")
    return DiskCache(cache_dir, ttl=default_ttl)


AppCache = _build_app_cache()

# Backwards-compatible name used by existing imports.
AppDiskCache = AppCache

AppJsonLogger = JsonFileWriter("./local_files/json/")
