from job_bot.utils import caching
from job_bot.utils.disk_cache import DiskCache


def test_redis_cache_falls_back_to_disk_without_redis_url(monkeypatch, tmp_path) -> None:
    fake_settings = type(
        "Settings",
        (),
        {
            "REDIS_URL": None,
            "DISK_CACHE_DIR": str(tmp_path),
        },
    )()
    monkeypatch.setattr(caching, "settings", lambda: fake_settings)
    monkeypatch.setattr(caching, "setting_value", lambda _name: None)

    cache = caching._build_redis_cache()

    assert isinstance(cache, DiskCache)
