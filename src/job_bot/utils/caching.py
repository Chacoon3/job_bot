from __future__ import annotations

from job_bot.config import setting_value, settings
from job_bot.utils.disk_cache import DiskCache
from job_bot.utils.json_file_writer import JsonFileWriter
from job_bot.utils.redis_cache import RedisCache


def _read_float_env(name: str) -> float | None:
    raw = setting_value(name)
    if raw is None or raw.strip() == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _build_redis_cache() -> RedisCache:
    default_ttl = _read_float_env("APP_CACHE_TTL_SECONDS")

    cfg = settings()
    redis_url = cfg.REDIS_URL
    if not redis_url:
        raise ValueError("REDIS_URL environment variable is required for RedisCache")
    redis_prefix = cfg.REDIS_CACHE_PREFIX
    redis_timeout = _read_float_env("REDIS_SOCKET_TIMEOUT_SECONDS")
    socket_timeout = 1.0 if redis_timeout is None else redis_timeout

    return RedisCache(
        redis_url,
        prefix=redis_prefix,
        ttl=default_ttl,
        socket_timeout=socket_timeout,
    )


def _build_disk_cache() -> DiskCache:
    cache_dir = settings().DISK_CACHE_DIR
    default_ttl = _read_float_env("APP_CACHE_TTL_SECONDS")
    return DiskCache(cache_dir, ttl=default_ttl)


AppRedisCache = _build_redis_cache()

# Backwards-compatible name used by existing imports.
AppDiskCache = _build_disk_cache()

AppJsonLogger = JsonFileWriter("./local_files/json/")
