"""Redis-backed mapping from MAX user_id to mgp-backend session_id.

Sessions auto-expire 24h after the last write. The store is intentionally
async-only — both the webhook handler and the chat-proxy run inside the
asyncio event-loop, no sync codepath is needed.
"""

from __future__ import annotations

import uuid
from typing import Optional

from redis.asyncio import Redis


def _key(max_user_id: int | str) -> str:
    return f"max:user:{max_user_id}:session"


class SessionStore:
    """Tiny abstraction over redis-py's async client.

    Owning the Redis connection makes it easy to swap a real client for
    fakeredis in unit tests.
    """

    def __init__(self, redis: Redis, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    @classmethod
    def from_url(cls, url: str, ttl_seconds: int) -> "SessionStore":
        # decode_responses=True makes the API return ``str`` instead of ``bytes``.
        return cls(Redis.from_url(url, decode_responses=True), ttl_seconds)

    async def aclose(self) -> None:
        await self._redis.aclose()

    async def get_session(self, max_user_id: int | str) -> Optional[str]:
        return await self._redis.get(_key(max_user_id))

    async def get_or_create_session(self, max_user_id: int | str) -> tuple[str, bool]:
        """Return ``(session_id, created)``. Refreshes TTL on every hit."""
        existing = await self._redis.get(_key(max_user_id))
        if existing:
            await self._redis.expire(_key(max_user_id), self._ttl)
            return existing, False
        new_session = f"max-{max_user_id}-{uuid.uuid4().hex[:8]}"
        await self._redis.set(_key(max_user_id), new_session, ex=self._ttl)
        return new_session, True

    async def reset_session(self, max_user_id: int | str) -> None:
        await self._redis.delete(_key(max_user_id))

    async def ping(self) -> bool:
        return bool(await self._redis.ping())
