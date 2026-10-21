from config.settings import cache_config


def test_unset_broker_keeps_the_cache_in_memory():
    backend = cache_config("")["default"]["BACKEND"]
    assert backend == "django.core.cache.backends.locmem.LocMemCache"


def test_configured_broker_uses_redis():
    cache = cache_config("redis://localhost:6379/0")["default"]
    assert cache["BACKEND"] == "django.core.cache.backends.redis.RedisCache"
    assert cache["LOCATION"] == "redis://localhost:6379/0"
