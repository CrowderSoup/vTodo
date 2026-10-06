"""Settings for the test suite: same as production settings, minus Redis.

The rate-limit and invite tests use the cache, so with the Redis cache they
needed a Redis server running. A per-process in-memory cache makes the suite
self-contained (CI, the home server's offline test sandbox)."""
from .settings import *  # noqa: F403

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "vtodo-tests",
    }
}
