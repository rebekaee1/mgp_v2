"""Redis-backed cache: external image URL → MAX media token.

A 7-day TTL (configurable) means the same hotel photo is uploaded to MAX at
most once a week, regardless of how many user searches surface it. Keys are
hashed so we never put long tourvisor URLs into Redis logs.
"""

from __future__ import annotations

import hashlib
from typing import Optional

import structlog
from redis.asyncio import Redis


class ImageCache:
    """Async wrapper around an existing redis client.

    The redis client is expected to be ``redis.asyncio.Redis``-compatible:
    ``get(key)`` returns ``str | None`` (with ``decode_responses=True`` already
    set on the connection) and ``set(key, value, ex=ttl)`` accepts a TTL in
    seconds.
    """

    KEY_PREFIX = "max:image_token:"

    def __init__(self, redis_client, *, ttl_seconds: int = 604800) -> None:
        self._redis = redis_client
        self._ttl = ttl_seconds
        self._log = structlog.get_logger("max_bridge.image_cache")

    @classmethod
    def from_url(cls, url: str, *, ttl_seconds: int = 604800) -> "ImageCache":
        return cls(Redis.from_url(url, decode_responses=True), ttl_seconds=ttl_seconds)

    async def aclose(self) -> None:
        try:
            await self._redis.aclose()
        except AttributeError:
            # fakeredis FakeRedis doesn't always expose aclose() — best effort.
            pass

    @classmethod
    def _key(cls, image_url: str) -> str:
        digest = hashlib.sha1(image_url.encode("utf-8")).hexdigest()
        return cls.KEY_PREFIX + digest

    async def get(self, image_url: str) -> Optional[str]:
        if not image_url:
            return None
        try:
            value = await self._redis.get(self._key(image_url))
        except Exception:
            self._log.exception("image_cache_get_failed")
            return None
        return value or None

    async def set(self, image_url: str, token: str) -> None:
        if not image_url or not token:
            return
        try:
            await self._redis.set(self._key(image_url), token, ex=self._ttl)
        except Exception:
            self._log.exception("image_cache_set_failed")
